import json
import random

import pytest

from fake_hrana import HranaServer
from harness import World, make_players, random_strategy
from util import run, check_card_consistency
from core.backend.turso.db import TursoDB, DatabaseError


@run
async def test_turso_client_types_batches_and_errors():
    srv = HranaServer().start()
    try:
        db = TursoDB(url=srv.url.replace("http://", "http://"), token="secret-token")
        await db.init_db()
        await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, big INTEGER, f REAL, s TEXT, n TEXT)")
        snowflake = 1523349130934489201
        res = await db.execute("INSERT INTO t (big, f, s, n) VALUES (?, ?, ?, ?)", [snowflake, 1.5, "héllo 🏏", None])
        assert res["affected"] == 1 and res["last_id"] == 1
        row = await db.fetchone("SELECT * FROM t")
        assert row == {"id": 1, "big": snowflake, "f": 1.5, "s": "héllo 🏏", "n": None}
        # atomic batch: second statement fails -> first must be rolled back
        with pytest.raises(DatabaseError):
            await db.batch([("INSERT INTO t (big) VALUES (?)", [1]), ("INSERT INTO nope VALUES (1)", [])])
        assert len(await db.fetch("SELECT * FROM t")) == 1
        out = await db.batch([("INSERT INTO t (big) VALUES (?)", [2]), ("UPDATE t SET s = ? WHERE big = ?", ["x", 2])])
        assert out[0]["affected"] == 1 and out[1]["affected"] == 1
        with pytest.raises(DatabaseError):
            await db.execute("SELECT * FROM missing_table")
        bad = TursoDB(url=srv.url, token="wrong")
        with pytest.raises(Exception):
            await bad.execute("SELECT 1")
        await db.close()
    finally:
        srv.stop()


@run
async def test_full_match_on_turso_backend():
    random.seed(9)
    srv = HranaServer().start()
    try:
        db = TursoDB(url=srv.url, token="secret-token")
        w = World(db=db)
        await w.setup()
        ch = w.channel()
        a = make_players(w, ["Tia", "Uma", "Vic"], strategy=random_strategy)
        b = make_players(w, ["Wes", "Xan", "Yul"], strategy=random_strategy)
        mi = await w.setup_match(ch, a, b, overs=10, days=4)
        await w.finish(mi, timeout=90)
        assert mi.phase == "finished"
        for c in mi.innings_scorecards.values():
            check_card_consistency(c)
        row = await db.fetchone("SELECT status, data FROM matches WHERE match_id = ?", [mi.match_id])
        assert row["status"] == "completed"
        assert json.loads(row["data"])["result"]["text"] == mi.game.result_text()
        profs = await db.fetch("SELECT * FROM profiles")
        assert len(profs) == 6 and all(p["matches_played"] == 1 for p in profs)
        assert await db.fetch("SELECT * FROM ongoing_matches") == []
        assert srv.requests < 400, f"too many DB round trips: {srv.requests}"
    finally:
        srv.stop()
