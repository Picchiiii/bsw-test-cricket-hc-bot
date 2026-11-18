"""Database access.

Two interchangeable backends with the same async API:
  * TursoDB  – Turso / libSQL over the HTTP pipeline API (production; also what the website reads)
  * SQLiteDB – a local SQLite file (development / tests / running without Turso)

API (both):  execute(sql, args) -> {"rows": [dict], "affected": int, "last_id": int}
             fetch(sql, args) -> [dict]          fetchone(sql, args) -> dict | None
             batch([(sql, args), ...])           atomic: all statements succeed or none do
"""
import asyncio
import base64
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request

from dotenv import load_dotenv

try:  # httpx is preferred (connection pooling); urllib is the zero-dependency fallback
    import httpx
except Exception:  # pragma: no cover - depends on environment
    httpx = None

load_dotenv()
logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas.sql")


class DatabaseError(Exception):
    pass


def _split_statements(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


# ─────────────────────────────────────────────────────────────── Turso (HTTP)
def _encode(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, (dict, list, tuple)):
        return {"type": "text", "value": json.dumps(value, separators=(",", ":"))}
    return {"type": "text", "value": str(value)}


def _decode(cell):
    if cell is None:
        return None
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


def _result_to_dict(result: dict) -> dict:
    cols = [c.get("name") for c in result.get("cols", [])]
    rows = [{cols[i]: _decode(cell) for i, cell in enumerate(row)} for row in result.get("rows", [])]
    last_id = result.get("last_insert_rowid")
    return {"rows": rows, "affected": int(result.get("affected_row_count") or 0),
            "last_id": int(last_id) if last_id not in (None, "") else None}


class TursoDB:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = url or os.getenv("TURSO_DATABASE_URL")
        self.token = token or os.getenv("TURSO_AUTH_TOKEN")
        if not self.url:
            raise DatabaseError("TURSO_DATABASE_URL is not set")
        self.url = self.url.replace("libsql://", "https://")
        self.url = self.url.replace("wss://", "https://").replace("ws://", "http://")
        self.url = self.url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.client = None
        if httpx is not None:
            self.client = httpx.AsyncClient(timeout=15.0, headers=self._headers)

    async def close(self):
        if self.client is not None:
            await self.client.aclose()

    async def _post(self, payload: dict) -> dict:
        endpoint = f"{self.url}/v2/pipeline"
        if self.client is not None:
            response = await self.client.post(endpoint, json=payload)
            response.raise_for_status()
            return response.json()

        def do():
            req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=self._headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                raise DatabaseError(f"Turso HTTP {e.code}: {e.read()[:300]!r}") from e
        return await asyncio.to_thread(do)

    @staticmethod
    def _stmt(sql, args):
        return {"sql": sql, "args": [_encode(a) for a in (args or [])]}

    async def execute(self, sql: str, args: list | None = None) -> dict:
        payload = {"requests": [{"type": "execute", "stmt": self._stmt(sql, args)}, {"type": "close"}]}
        res = await self._post(payload)
        first = res["results"][0]
        if first.get("type") != "ok":
            raise DatabaseError(first.get("error", {}).get("message", "unknown Turso error"))
        return _result_to_dict(first["response"]["result"])

    async def fetch(self, sql: str, args: list | None = None) -> list[dict]:
        return (await self.execute(sql, args))["rows"]

    async def fetchone(self, sql: str, args: list | None = None):
        rows = await self.fetch(sql, args)
        return rows[0] if rows else None

    async def batch(self, statements: list[tuple[str, list]]) -> list[dict]:
        """Atomic batch: BEGIN, each step only if the previous succeeded, COMMIT, else ROLLBACK."""
        if not statements:
            return []
        steps = [{"stmt": {"sql": "BEGIN"}}]
        for i, (sql, args) in enumerate(statements):
            steps.append({"stmt": self._stmt(sql, args), "condition": {"type": "ok", "step": i}})
        commit_idx = len(steps)
        steps.append({"stmt": {"sql": "COMMIT"}, "condition": {"type": "ok", "step": commit_idx - 1}})
        steps.append({"stmt": {"sql": "ROLLBACK"}, "condition": {"type": "not", "cond": {"type": "ok", "step": commit_idx}}})
        payload = {"requests": [{"type": "batch", "batch": {"steps": steps}}, {"type": "close"}]}
        res = await self._post(payload)
        first = res["results"][0]
        if first.get("type") != "ok":
            raise DatabaseError(first.get("error", {}).get("message", "unknown Turso error"))
        result = first["response"]["result"]
        errors = [e for e in result.get("step_errors", []) if e]
        if errors:
            raise DatabaseError(errors[0].get("message", "batch failed"))
        out = []
        for step in result.get("step_results", [])[1:1 + len(statements)]:
            out.append(_result_to_dict(step) if step else {"rows": [], "affected": 0, "last_id": None})
        return out

    async def init_db(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schemas = f.read()
        for stmt in _split_statements(schemas):
            await self.execute(stmt)
        await migrate(self)


# ─────────────────────────────────────────────────────────────── SQLite (local)
class SQLiteDB:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("SQLITE_PATH", "bsw.sqlite3")
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self._lock = asyncio.Lock()

    async def close(self):
        self._conn.close()

    @staticmethod
    def _args(args):
        out = []
        for a in args or []:
            if isinstance(a, (dict, list, tuple)):
                a = json.dumps(a, separators=(",", ":"))
            elif isinstance(a, bool):
                a = int(a)
            out.append(a)
        return out

    def _run(self, sql, args):
        cur = self._conn.execute(sql, self._args(args))
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        return {"rows": rows, "affected": cur.rowcount if cur.rowcount >= 0 else 0, "last_id": cur.lastrowid}

    async def execute(self, sql: str, args: list | None = None) -> dict:
        async with self._lock:
            try:
                return await asyncio.to_thread(self._run, sql, args)
            except sqlite3.Error as e:
                raise DatabaseError(str(e)) from e

    async def fetch(self, sql, args=None):
        return (await self.execute(sql, args))["rows"]

    async def fetchone(self, sql, args=None):
        rows = await self.fetch(sql, args)
        return rows[0] if rows else None

    async def batch(self, statements):
        def do():
            out = []
            self._conn.execute("BEGIN")
            try:
                for sql, args in statements:
                    out.append(self._run(sql, args))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return out
        async with self._lock:
            try:
                return await asyncio.to_thread(do)
            except sqlite3.Error as e:
                raise DatabaseError(str(e)) from e

    async def init_db(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schemas = f.read()
        for stmt in _split_statements(schemas):
            await self.execute(stmt)
        await migrate(self)


# ─────────────────────────────────────────────────────────────── migrations
# Columns added after a table may already exist in production: (table, column, declaration)
MIGRATIONS: list[tuple[str, str, str]] = [
    # tournaments: which tournament / fixture a match belongs to
    ("matches", "tournament_id", "TEXT"),
    ("matches", "fixture_id", "TEXT"),
    # richer per-match figures (tournament leaderboards)
    ("player_match_stats", "not_outs", "INTEGER DEFAULT 0"),
    ("player_match_stats", "fifties", "INTEGER DEFAULT 0"),
    ("player_match_stats", "hundreds", "INTEGER DEFAULT 0"),
    ("player_match_stats", "five_wickets", "INTEGER DEFAULT 0"),
    ("player_match_stats", "maidens", "INTEGER DEFAULT 0"),
    ("player_match_stats", "best_w", "INTEGER DEFAULT 0"),
    ("player_match_stats", "best_r", "INTEGER DEFAULT 0"),
]


async def migrate(db):
    for table, column, decl in MIGRATIONS:
        cols = {r["name"] for r in await db.fetch(f"PRAGMA table_info({table})")}
        if column not in cols:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id)")


def get_database():
    """Pick the backend from the environment: Turso if configured, otherwise local SQLite."""
    backend = (os.getenv("DB_BACKEND") or "").lower()
    if backend == "sqlite" or (backend != "turso" and not os.getenv("TURSO_DATABASE_URL")):
        logger.info("database: using local SQLite (%s)", os.getenv("SQLITE_PATH", "bsw.sqlite3"))
        return SQLiteDB()
    logger.info("database: using Turso")
    return TursoDB()
