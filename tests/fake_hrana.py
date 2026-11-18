"""Minimal Turso/libSQL Hrana-over-HTTP v2 server (POST /v2/pipeline) backed by sqlite3, for tests.

Implements 'execute', 'batch' (with ok/not/and/or conditions) and 'close', the typed value encoding,
and bearer-token auth — enough to exercise the bot's TursoDB client and the website's API functions.
"""
import base64
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _decode_arg(v):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v["base64"])
    return v.get("value")


def _encode_val(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


class HranaServer:
    def __init__(self, token="secret-token"):
        self.token = token
        self.conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        self.requests = 0
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                if self.path != "/v2/pipeline":
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != f"Bearer {server.token}":
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error":"unauthorized"}')
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests += 1
                with server.lock:
                    out = {"baton": None, "base_url": None, "results": [server.handle(r) for r in body["requests"]]}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                self.send_response(204)
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()

    def _exec(self, stmt):
        args = [_decode_arg(a) for a in stmt.get("args", [])]
        cur = self.conn.execute(stmt["sql"], args)
        cols = [{"name": d[0], "decltype": None} for d in (cur.description or [])]
        rows = [[_encode_val(v) for v in row] for row in cur.fetchall()] if cur.description else []
        return {"cols": cols, "rows": rows, "affected_row_count": max(cur.rowcount, 0),
                "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid is not None else None}

    def _cond(self, cond, results, errors):
        if cond is None:
            return True
        t = cond["type"]
        if t == "ok":
            return results[cond["step"]] is not None
        if t == "error":
            return errors[cond["step"]] is not None
        if t == "not":
            return not self._cond(cond["cond"], results, errors)
        if t == "and":
            return all(self._cond(c, results, errors) for c in cond["conds"])
        if t == "or":
            return any(self._cond(c, results, errors) for c in cond["conds"])
        raise ValueError(t)

    def handle(self, req):
        t = req["type"]
        if t == "close":
            return {"type": "ok", "response": {"type": "close"}}
        if t == "execute":
            try:
                return {"type": "ok", "response": {"type": "execute", "result": self._exec(req["stmt"])}}
            except sqlite3.Error as e:
                return {"type": "error", "error": {"message": f"SQLite error: {e}", "code": "SQLITE_ERROR"}}
        if t == "batch":
            steps = req["batch"]["steps"]
            results = [None] * len(steps)
            errors = [None] * len(steps)
            for i, step in enumerate(steps):
                if not self._cond(step.get("condition"), results, errors):
                    continue
                try:
                    results[i] = self._exec(step["stmt"])
                except sqlite3.Error as e:
                    errors[i] = {"message": f"SQLite error: {e}"}
            return {"type": "ok", "response": {"type": "batch", "result": {"step_results": results, "step_errors": errors}}}
        return {"type": "error", "error": {"message": f"unknown request {t}"}}
