import asyncio
import json
import os
import random
import tempfile

import discord

from harness import World, make_players, Player, never_out, wait_until, random_strategy
from util import run, check_card_consistency, match_row
from core.backend.turso.db import SQLiteDB
from core.backend.persistence import restore_matches


def _second_world(first: World, db_path: str) -> World:
    """A fresh bot process sharing the same Discord objects and database."""
    w2 = World(db=SQLiteDB(db_path))
    w2.guild = first.guild
    for ch in first.channels:
        w2.bot.channels[ch.id] = ch
        ch.listeners.clear()
        ch.listeners.append(lambda m, ch=ch: w2._on_channel(ch, m))
        w2.channels.append(ch)
    for uid, u in first.bot.users.items():
        w2.bot.users[uid] = u
    return w2


@run
async def test_restart_after_pause_resumes_exactly():
    path = os.path.join(tempfile.mkdtemp(), "bsw.sqlite3")
    w = World(db=SQLiteDB(path))
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1", "A2"], strategy=never_out)
    b = make_players(w, ["B0", "B1", "B2"], strategy=never_out)
    mi = await w.setup_match(ch, a, b, overs=10, days=4, innings_overs=3)
    await wait_until(lambda: mi.overs >= 1 and mi.balls_this_over >= 2)
    await w.cmd("pause", a[0], ch)
    await wait_until(lambda: mi.task is not None and mi.paused)
    await asyncio.sleep(0.4)
    await w.bot.store.flush(mi)
    before = (mi.score, mi.wickets, mi.overs, mi.balls_this_over, mi.curr_batsman.id, mi.curr_bowler.id, mi.match_id)
    mi.task.cancel()   # the old process dies
    try:
        await mi.task
    except asyncio.CancelledError:
        pass

    w2 = _second_world(w, path)
    await w2.setup()
    for p in a + b:
        p.world = w2
    n = await restore_matches(w2.bot)
    assert n == 1
    mi2 = w2.bot.active_matches[ch.id]
    after = (mi2.score, mi2.wickets, mi2.overs, mi2.balls_this_over, mi2.curr_batsman.id, mi2.curr_bowler.id, mi2.match_id)
    assert after == before
    assert mi2.paused and "Match restored" in ch.messages[-1].text()
    row = mi2.game.row(mi2.curr_batsman)
    assert row["runs"] > 0 and row["balls"] > 0, "per-player figures restored"
    await w2.cmd("resume", a[0], ch)
    await w2.finish(mi2)
    assert mi2.phase == "finished"
    for c in mi2.innings_scorecards.values():
        check_card_consistency(c)
    assert mi2.innings_scorecards[1]["balls"] == 18
    r = await match_row(w2.db, mi2.match_id)
    assert r["status"] == "completed"


@run
async def test_hard_crash_restores_last_saved_ball():
    random.seed(5)
    path = os.path.join(tempfile.mkdtemp(), "bsw.sqlite3")
    w = World(db=SQLiteDB(path))
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1", "A2"], strategy=random_strategy)
    b = make_players(w, ["B0", "B1", "B2"], strategy=random_strategy)
    mi = await w.setup_match(ch, a, b, overs=10, days=4)
    await wait_until(lambda: mi.innings >= 2 and mi.phase == "innings" and mi.overs * 6 + mi.balls_this_over >= 2, timeout=30)
    mi.task.cancel()   # no pause, no flush: kill -9
    try:
        await mi.task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(1.2)   # let the coalescing writer finish whatever it had in flight

    w2 = _second_world(w, path)
    await w2.setup()
    for p in a + b:
        p.world = w2
    assert await restore_matches(w2.bot) == 1
    mi2 = w2.bot.active_matches[ch.id]
    assert mi2.innings >= 2 and 1 in mi2.innings_scorecards
    await w2.cmd("resume", b[0], ch)
    await w2.finish(mi2)
    assert mi2.phase == "finished"
    for c in mi2.innings_scorecards.values():
        check_card_consistency(c)


@run
async def test_lobby_and_stumps_survive_restart():
    path = os.path.join(tempfile.mkdtemp(), "bsw.sqlite3")
    w = World(db=SQLiteDB(path))
    w.auto_next_day = False
    await w.setup()
    lobby_ch = w.channel("lobby")
    play_ch = w.channel("play")
    a = make_players(w, ["A0", "A1"], strategy=never_out)
    b = make_players(w, ["B0", "B1"], strategy=never_out)
    c = make_players(w, ["C0", "C1"])
    await w.cmd("create", c[0], lobby_ch)
    await w.cmd("join", c[1], lobby_ch)
    await w.cmd("so", c[0], lobby_ch, 15)
    mi = await w.setup_match(play_ch, a, b, overs=1, days=2, innings_overs=0)
    await wait_until(lambda: mi.stumps_called)
    await w.bot.store.flush(mi)
    await w.bot.store.flush(w.bot.active_matches[lobby_ch.id])
    mi.task.cancel()
    try:
        await mi.task
    except asyncio.CancelledError:
        pass

    w2 = _second_world(w, path)
    w2.auto_next_day = False
    await w2.setup()
    for p in a + b + c:
        p.world = w2
    assert await restore_matches(w2.bot) == 2
    lobby = w2.bot.active_matches[lobby_ch.id]
    assert [p.name for p in lobby.players] == ["C0", "C1"] and lobby.match_settings["overs"] == 15
    assert "lobby has been restored" in lobby_ch.messages[-1].text()
    mi2 = w2.bot.active_matches[play_ch.id]
    assert mi2.stumps_called and mi2.crr_day == 1
    stumps_msg = play_ch.messages[-1]
    assert "Match restored — Stumps" in stumps_msg.text()
    await w2.click(stumps_msg, a[0], "Start next day")
    await w2.finish(mi2)
    assert mi2.crr_day == 2 and mi2.result["type"] == "draw"


@run
async def test_many_matches_at_once_do_not_interfere():
    random.seed(21)
    w = World()
    await w.setup()
    matches = []
    teams = []
    for i in range(4):
        ch = w.channel(f"m{i}")
        a = make_players(w, [f"M{i}A{j}" for j in range(3)], strategy=random_strategy)
        b = make_players(w, [f"M{i}B{j}" for j in range(3)], strategy=random_strategy)
        teams.append((a, b))
        matches.append((ch, await w.setup_match(ch, a, b, overs=10, days=3)))
    assert len(w.bot.active_matches) == 4
    # a player already in a match can't join another
    intruder = teams[0][0][1]
    w.bot.active_matches[matches[1][0].id].lobby_lock = False
    await w.cmd("join", intruder, matches[1][0])
    assert "already in a match" in matches[1][0].messages[-1].text() or "already started" in matches[1][0].messages[-1].text()
    await asyncio.gather(*(w.finish(mi, timeout=90) for _, mi in matches))
    for (ch, mi), (a, b) in zip(matches, teams):
        assert mi.phase == "finished"
        names = {p.member.name for p in a + b}
        for card in mi.innings_scorecards.values():
            check_card_consistency(card)
            assert {r["name"] for r in card["batting"]} <= names
            assert {r["name"] for r in card["bowling"]} <= names
    rows = await w.db.fetch("SELECT status FROM matches")
    assert len(rows) == 4 and all(r["status"] == "completed" for r in rows)
    profs = await w.db.fetch("SELECT matches_played FROM profiles")
    assert len(profs) == 24 and all(p["matches_played"] == 1 for p in profs)


@run
async def test_one_match_per_player_in_lobbies():
    w = World()
    await w.setup()
    ch1, ch2 = w.channel(), w.channel()
    p = make_players(w, ["P0", "P1", "P2", "P3"])
    await w.cmd("create", p[0], ch1)
    await w.cmd("join", p[3], ch1)          # becomes Team B captain
    await w.cmd("leave", p[3], ch1)
    assert "captain cannot leave" in ch1.messages[-1].text()
    await w.cmd("create", p[0], ch2)
    assert "already in a match" in ch2.messages[-1].text()
    await w.cmd("create", p[1], ch2)
    await w.cmd("join", p[2], ch1)
    await w.cmd("join", p[2], ch2)
    assert "already in a match" in ch2.messages[-1].text()
    await w.cmd("leave", p[2], ch1)
    await w.cmd("join", p[2], ch2)
    assert "has joined" in ch2.messages[-1].text()


@run
async def test_live_snapshot_for_website_updates_each_ball():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1", "A2"], strategy=never_out)
    b = make_players(w, ["B0", "B1", "B2"], strategy=never_out)
    mi = await w.setup_match(ch, a, b, innings_overs=0)
    await wait_until(lambda: mi.overs >= 1 and mi.balls_this_over >= 3)
    await w.bot.store.flush(mi)
    row = await match_row(w.db, mi.match_id)
    d = row["data"]
    assert row["status"] == "live"
    assert d["current"]["score"] == mi.score
    assert d["current"]["batter"]["name"] == mi.curr_batsman.name
    assert d["innings"][-1]["live"] is True
    assert d["commentary"] and d["teams"]["A"]["players"][0]["captain"] is True
    json.dumps(d)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)
