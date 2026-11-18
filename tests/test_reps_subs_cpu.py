"""Representatives (run cap, no bowling), substitutes (squad rule), CPU players and the JSON match sheet."""
import asyncio
import json
import os
import tempfile

import discord

from harness import World, make_players, never_out, wait_until, Player
from util import run, check_card_consistency, match_row
from core.backend.turso.db import SQLiteDB


def last(ch):
    return ch.messages[-1].text()


async def start_with(w, ch, players_a, players_b, reps=(), overs=2, days=4, bat_first="A", **settings):
    """Like World.setup_match, but marks `reps` and applies settings before the match starts."""
    host = players_a[0]
    await w.cmd("create", host, ch)
    mi = w.bot.active_matches[ch.id]
    for p in players_a[1:] + players_b:
        await w.cmd("join", p, ch, *(["rep"] if p in reps else []))
    mi.teamA = [p.member for p in players_a]
    mi.teamB = [p.member for p in players_b]
    mi.teamA_captain, mi.teamB_captain = mi.teamA[0], mi.teamB[0]
    await w.cmd("so", host, ch, 10)
    await w.cmd("sd", host, ch, days)
    mi.match_settings["overs"] = overs
    for k, v in settings.items():
        mi.match_settings[k] = v
    await w.cmd("toss", host, ch)
    toss = ch.messages[-1]
    await w.click(toss, toss.view.allowed_user, "Heads")
    await asyncio.sleep(0.01)
    bb = ch.messages[-1]
    winner = bb.view.allowed_user
    side = "A" if winner == mi.teamA_captain else "B"
    await w.click(bb, winner, "Bat" if side == bat_first else "Bowl")
    await w.cmd("start", host, ch)
    assert mi.game_started, last(ch)
    return mi


def all_cards(mi):
    return [mi.innings_scorecards[n] for n in sorted(mi.innings_scorecards)]


# ───────────────────────────────────────────────────────────────── representatives
@run
async def test_rep_retires_at_cap_as_a_wicket_and_never_bowls():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1", "Rep"], strategy=never_out)     # Rep is listed last → opens (harness picks last)
    b = make_players(w, ["B0", "B1"], strategy=never_out)
    mi = await start_with(w, ch, a, b, reps=[a[2]], rep_run_cap=7, innings_overs=2)
    assert a[2].member in mi.reps
    await w.finish(mi, timeout=90)
    first = mi.innings_scorecards[1]
    rep_row = next(r for r in first["batting"] if r["name"] == "Rep")
    assert rep_row["rep"] is True
    assert rep_row["runs"] == 7, "2+2+2 then only 1 of the next 2 counts"
    assert rep_row["is_out"] and rep_row["dismissal"] == "rep_retired"
    assert rep_row["status"] == "retired out (rep limit)"
    assert first["wickets"] >= 1 and first["fow"][0]["player"] == "Rep"
    assert len(first["batting"]) >= 2, "the next batter came in after the rep retired"
    for card in all_cards(mi):
        check_card_consistency(card)
        if card["bowling_team"] == "A":
            assert all(r["name"] != "Rep" for r in card["bowling"]), "reps can't bowl"
    assert "Rep limit reached" in ch.all_text()


@run
async def test_rep_retired_not_out_setting_and_all_out_rule():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "Rep"], strategy=never_out)
    b = make_players(w, ["B0", "B1"], strategy=never_out)
    mi = await start_with(w, ch, a, b, reps=[a[1]], rep_run_cap=5, rep_retire_counts_wicket=False, innings_overs=2)
    await wait_until(lambda: 1 in mi.innings_scorecards, timeout=30)
    first = mi.innings_scorecards[1]
    rep_row = next(r for r in first["batting"] if r["name"] == "Rep")
    assert rep_row["runs"] == 5 and not rep_row["is_out"] and rep_row["retired"] == "rep_cap"
    assert rep_row["status"] == "retired not out (rep limit)"
    # two batters, one retired: nobody left to partner → the innings closes with no wicket down
    assert first["wickets"] == 0 and first["runs"] == 5 and first["retired_not_out"] == 1
    check_card_consistency(first)
    await w.finish(mi, timeout=90)


@run
async def test_rep_settings_limits_and_start_checks():
    w = World()
    await w.setup()
    ch = w.channel()
    p = make_players(w, ["H", "B0", "R1", "R2"])
    await w.cmd("create", p[0], ch)
    mi = w.bot.active_matches[ch.id]
    assert mi.match_settings["rep_run_cap"] == 30 and mi.match_settings["rep_can_bowl"] is False
    await w.cmd("settings", p[0], ch, "rep_run_cap", 40)
    assert mi.match_settings["rep_run_cap"] == 40
    await w.cmd("settings", p[0], ch, "rep_run_cap", 501)
    assert "between 0 and 500" in last(ch)
    await w.cmd("settings", p[0], ch, "max_reps_per_team", 1)
    await w.cmd("join", p[1], ch)           # B0 → team B
    await w.cmd("join", p[2], ch, "rep")    # R1 → team A, rep
    assert "representative (R)" in last(ch)
    mi.teamA, mi.teamB = [p[0].member], [p[1].member, p[2].member]
    await w.cmd("join", p[3], ch, "rep")    # R2 → team A (smaller)... limit is per team
    assert p[3].member in mi.reps
    await w.cmd("setrep", p[0], ch, p[1].member)
    assert "Only" not in last(ch) and "already has 1" in last(ch), "B already has R1 as a rep"
    await w.cmd("setrep", p[1], ch, p[2].member, "off")
    assert "Only the host" in last(ch)
    await w.cmd("setrep", p[0], ch, p[2].member, "off")
    assert p[2].member not in mi.reps
    await w.cmd("setrep", p[0], ch)
    assert "Run cap: **40**" in last(ch)
    # a side made only of reps can't bowl → start is refused until reps may bowl
    mi.teamA, mi.teamB = [p[0].member, p[1].member], [p[3].member]
    mi.teamA_captain, mi.teamB_captain = p[0].member, p[3].member
    await w.cmd("so", p[0], ch, 10)
    await w.cmd("sd", p[0], ch, 1)
    mi.toss_winner, mi.batting_turn, mi.bowling_turn = p[0].member, "A", "B"
    await w.cmd("start", p[0], ch)
    assert "has only reps" in last(ch) and not mi.game_started
    await w.cmd("settings", p[0], ch, "rep_can_bowl", 1)
    assert mi.match_settings["rep_can_bowl"] is True
    await w.cmd("players", p[0], ch)
    assert "reps **can** bowl" in last(ch)


# ───────────────────────────────────────────────────────────────── substitutes
@run
async def test_lobby_substitute_can_be_anyone_outside_the_match():
    w = World()
    await w.setup()
    ch = w.channel()
    p = make_players(w, ["H", "B0", "A1", "B1"])
    extra = make_players(w, ["Benchy", "Stranger"])
    await w.cmd("create", p[0], ch)
    for x in p[1:]:
        await w.cmd("join", x, ch)
    mi = w.bot.active_matches[ch.id]
    # nobody already in the match can come on as a substitute
    await w.cmd("sub", p[0], ch, p[2].member, p[1].member)
    assert "already playing" in last(ch)
    await w.cmd("sub", p[1], ch, p[2].member, extra[1].member)
    assert "Only the host" in last(ch), "B's captain can't sub A's players"
    # a friendly: anyone who isn't in the match — no bench needed
    await w.cmd("sub", p[0], ch, p[2].member, extra[1].member)
    assert "comes in for" in last(ch)
    assert extra[1].member in mi.teamA and p[2].member not in mi.players
    await w.cmd("players", p[0], ch)
    assert "Stranger (sub)" in last(ch)
    # the optional bench still works (shows who's available) and its players can be brought on
    await w.cmd("join", extra[0], ch, "sub")
    assert "Say which team" in last(ch)
    await w.cmd("join", extra[0], ch, "sub", "b")
    assert "bench" in last(ch) and extra[0].member in mi.bench["B"]
    await w.cmd("players", p[0], ch)
    assert "Bench" in last(ch) and "Benchy" in last(ch)
    await w.cmd("sub", p[1], ch, p[3].member, extra[0].member)
    assert "comes in for" in last(ch) and not mi.bench["B"]
    await w.cmd("join", p[2], ch, "sub", "A")
    await w.cmd("leave", p[2], ch)
    assert "left" in last(ch) and not mi.bench["A"]
    await w.cmd("sub", p[0], ch)
    assert "Substitutes" in last(ch) and "Stranger for A1" in last(ch) and "isn't already in this match" in last(ch)


@run
async def test_squads_are_shown_when_play_resumes_and_a_missing_player_can_be_subbed():
    from core.backend.views.squad_view import SquadCheckView
    w = World()
    w.auto_next_day = False
    await w.setup()
    ch = w.channel()
    away = set()

    def strat(role, player, mi):
        if player.member.name in away:
            return None
        return never_out(role, player, mi)

    a = make_players(w, ["A0", "Absent"], strategy=strat)
    b = make_players(w, ["B0", "B1"], strategy=strat)
    newcomer = Player(w, "Newcomer", strategy=strat)
    await w.cmd("create", a[0], ch)
    mi = await _continue_lobby(w, ch, a, b, innings_overs=4, squad_check_seconds=5)
    mi.match_settings["overs"] = 1          # one over a day → stumps after every over
    await wait_until(lambda: mi.stumps_called, timeout=20)
    away.add("Absent")                      # day 2: Absent doesn't turn up
    await w.cmd("resume", a[0], ch)
    await wait_until(lambda: mi.squad_check_view is not None, timeout=5)
    prompt = next(m for m in reversed(ch.messages) if isinstance(m.view, SquadCheckView))
    text = prompt.text()
    assert "Squads — Day 2" in text and "Absent" in text and "B1" in text and "+sub" in text
    # nothing is bowled while the squads are up
    balls = mi.overs * 6 + mi.balls_this_over
    await asyncio.sleep(0.3)
    assert mi.overs * 6 + mi.balls_this_over == balls
    await w.cmd("sub", a[0], ch, "Absent", newcomer.member)
    assert "Substitution" in last(ch), last(ch)
    assert newcomer.member in mi.teamA and a[1].member not in mi.players
    # only the host or a captain can start play
    inter = await w.click(prompt, b[1], "Start play")
    assert "Only the host or a captain" in inter.response.sent[0]["content"]
    await w.click(prompt, b[0], "Start play")
    await wait_until(lambda: mi.squad_check_view is None, timeout=5)
    await wait_until(lambda: mi.overs * 6 + mi.balls_this_over > balls or mi.stumps_called, timeout=10)
    # next stumps: `+resume` twice — the second one starts play straight away
    await wait_until(lambda: mi.stumps_called, timeout=20)
    await w.cmd("resume", b[0], ch)
    await wait_until(lambda: mi.squad_check_view is not None, timeout=5)
    await w.cmd("resume", b[0], ch)
    assert "Play starts now" in last(ch)
    await wait_until(lambda: mi.squad_check_view is None, timeout=5)
    mi.match_abandoned = True
    mi.interrupt.set()
    mi.resume_event.set()
    await w.finish(mi, timeout=30)


@run
async def test_mid_match_substitute_takes_over_at_the_crease_and_both_get_stats():
    w = World()
    await w.setup()
    ch = w.channel()
    away = set()

    def strat(role, player, mi):
        if player.member.name in away:
            return None          # not available
        return never_out(role, player, mi)

    a = make_players(w, ["A0", "Gone"], strategy=strat)
    b = make_players(w, ["B0", "B1"], strategy=strat)
    sub = Player(w, "Fresh", strategy=strat)
    await w.cmd("create", a[0], ch)
    await w.cmd("join", sub, ch, "sub", "A")
    mi = await _continue_lobby(w, ch, a, b, innings_overs=2)
    await wait_until(lambda: mi.curr_batsman == a[1].member and mi.balls_this_over >= 1, timeout=20)
    away.add("Gone")
    await wait_until(lambda: mi.awaiting_ball and mi.curr_batsman == a[1].member, timeout=10)
    runs_before = mi.game.row(a[1].member)["runs"]
    await w.cmd("sub", a[0], ch, "Gone", "Fresh")
    assert "Substitution" in last(ch) and "takes over at the crease" in last(ch)
    assert mi.curr_batsman == sub.member and sub.member in mi.teamA and a[1].member not in mi.players
    await w.finish(mi, timeout=90)
    first = mi.innings_scorecards[1]
    gone = next(r for r in first["batting"] if r["name"] == "Gone")
    fresh = next(r for r in first["batting"] if r["name"] == "Fresh")
    assert gone["runs"] == runs_before and not gone["is_out"] and gone["subbed_out"]
    assert gone["status"].startswith("retired — substituted")
    assert fresh["sub_for"] == "Gone" and fresh["balls"] > 0
    assert first["substitutions"][0]["in_name"] == "Fresh"
    for card in all_cards(mi):
        check_card_consistency(card)
    profiles = {r["name"]: r for r in await w.db.fetch("SELECT name, matches_played, runs FROM profiles")}
    assert profiles["Gone"]["matches_played"] == 1 and profiles["Gone"]["runs"] >= runs_before
    assert profiles["Fresh"]["matches_played"] == 1
    row = await match_row(w.db, mi.match_id)
    assert row["data"]["substitutions"][0]["out_name"] == "Gone"
    assert row["data"]["teams"]["A"]["subbed_out"][0]["name"] == "Gone"


async def _continue_lobby(w, ch, a, b, **settings):
    """Fill an existing lobby (host = a[0]) with the rest of a and b, toss, A bats, start."""
    mi = w.bot.active_matches[ch.id]
    for p in a[1:] + b:
        await w.cmd("join", p, ch)
    mi.teamA = [p.member for p in a]
    mi.teamB = [p.member for p in b]
    mi.teamA_captain, mi.teamB_captain = mi.teamA[0], mi.teamB[0]
    await w.cmd("so", a[0], ch, 10)
    await w.cmd("sd", a[0], ch, 4)
    mi.match_settings["overs"] = 2
    mi.match_settings.update(settings)
    mi.toss_winner, mi.toss_decision = mi.teamA_captain, "bat"
    mi.batting_turn, mi.bowling_turn = "A", "B"
    mi.match_settings["team_batting_first"] = "bat"
    await w.cmd("start", a[0], ch)
    assert mi.game_started, last(ch)
    return mi


@run
async def test_rep_substitute_for_the_bowler_cannot_bowl_so_someone_else_finishes_the_over():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1"], strategy=never_out)
    b = make_players(w, ["B0", "B1", "B2"], strategy=never_out)
    newbie = Player(w, "RepSub", strategy=never_out)
    await w.cmd("create", a[0], ch)
    await w.cmd("join", newbie, ch, "sub", "B")
    mi = await _continue_lobby(w, ch, a, b, innings_overs=2)
    await wait_until(lambda: mi.awaiting_ball and mi.balls_this_over >= 2 and mi.overs == 0, timeout=20)
    bowler = mi.curr_bowler
    await w.cmd("sub", b[0], ch, bowler, newbie.member, "rep")
    assert "Reps can't bowl" in last(ch) or bowler == mi.curr_bowler, last(ch)
    assert mi.curr_bowler != newbie.member and mi.curr_bowler != bowler
    assert newbie.member in mi.reps
    await w.finish(mi, timeout=90)
    for card in all_cards(mi):
        check_card_consistency(card)
        if card["bowling_team"] == "B":
            assert all(r["name"] != "RepSub" for r in card["bowling"])
    first = mi.innings_scorecards[1]
    out_row = next(r for r in first["bowling"] if r["name"] == bowler.name)
    assert out_row["subbed_out"] and out_row["balls"] >= 2


@run
async def test_substitution_limits_and_switches():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1"], strategy=never_out)
    b = make_players(w, ["B0", "B1"], strategy=never_out)
    s1, s2 = Player(w, "S1", strategy=never_out), Player(w, "S2", strategy=never_out)
    await w.cmd("create", a[0], ch)
    await w.cmd("join", s1, ch, "sub", "A")
    await w.cmd("join", s2, ch, "sub", "A")
    mi = await _continue_lobby(w, ch, a, b, innings_overs=3, max_subs_per_team=1)
    await wait_until(lambda: mi.awaiting_ball, timeout=20)
    await w.cmd("sub", a[0], ch, a[1].member, s1.member)
    assert "Substitution" in last(ch)
    await wait_until(lambda: mi.awaiting_ball, timeout=20)
    await w.cmd("sub", a[0], ch, s1.member, s2.member)
    assert "used all 1" in last(ch)
    await w.cmd("sub", a[0], ch, a[0].member, a[1].member)
    assert "can't come back" in last(ch)
    mi.match_settings["subs_during_match"] = False
    await w.cmd("sub", a[0], ch, a[0].member, s2.member)
    assert "switched off" in last(ch)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi, timeout=30)


@run
async def test_tournament_substitute_must_be_on_the_roster_and_rep_rules_come_from_the_tournament():
    from tutil import world, make_teams, tour
    w, ch, admin = await world()
    teams = await make_teams(w, ch, admin, {"Lions": ["L1", "L2", "L3"], "Tigers": ["T1", "T2", "T3"]},
                             settings={"max_players": 2, "rep_run_cap": 12, "max_subs": 2, "rep_can_bowl": "on"})
    lobby = w.channel("match")
    L, T = teams["Lions"], teams["Tigers"]
    await w.cmd("create", L[0], lobby)
    await w.cmd("tm", L[0], lobby, "1")
    mi = w.bot.active_matches[lobby.id]
    assert mi.match_settings["rep_run_cap"] == 12 and mi.match_settings["rep_can_bowl"] is True
    assert mi.match_settings["max_subs_per_team"] == 2
    await w.cmd("join", L[1], lobby, "rep")
    await w.cmd("join", T[0], lobby)
    await w.cmd("join", T[1], lobby)
    assert L[1].member in mi.reps
    await w.cmd("join", L[2], lobby, "sub")
    assert "whole roster is the squad" in last(lobby)
    outsider = Player(w, "Outsider")
    await w.cmd("sub", L[0], lobby, L[1].member, outsider.member)
    assert "squad" in last(lobby) and "roster" in last(lobby) and "tour subs on" in last(lobby)
    await w.cmd("sub", L[0], lobby, L[1].member, T[2].member)
    assert "registered with" in last(lobby), "a Tigers player can't come on for the Lions"
    await w.cmd("sub", L[0], lobby, L[1].member, L[2].member)
    assert "comes in for" in last(lobby) and L[2].member in mi.team(mi.side_of(L[0].member))
    assert L[1].member not in mi.players
    # the tournament host switches on substitutes from outside the squad
    out = await tour(w, L[0], ch, "subs", "on")
    assert "is now" not in out, "only organisers can change it"
    out = await tour(w, admin, ch, "subs", "on")
    assert "is now" in out
    await w.cmd("sub", L[0], lobby, L[2].member, outsider.member)
    assert "comes in for" in last(lobby), last(lobby)
    await w.cmd("sub", L[0], lobby, L[0].member, T[2].member)
    assert "registered with" in last(lobby), "opponents are still refused"
    # the outside substitute stays in the lobby when the rosters are re-checked
    await w.bot.tournaments.refresh_rosters(mi)
    assert outsider.member in mi.players
    out = await tour(w, admin, ch, "subs", "off")
    assert "is now" in out
    await w.cmd("cpu", L[0], lobby, "add")
    assert "can't take part in tournament" in last(lobby)


# ───────────────────────────────────────────────────────────────── CPU players
@run
async def test_cpu_players_fill_a_lobby_and_play_a_full_match_without_counting():
    w = World()
    await w.setup()
    ch = w.channel()
    host = make_players(w, ["Host"], strategy=never_out)[0]
    await w.cmd("create", host, ch)
    mi = w.bot.active_matches[ch.id]
    await w.cmd("cpu", host, ch, "add", "B", "2")
    assert "Added" in ch.messages[-1].content
    cpus = [p for p in mi.players if getattr(p, "is_cpu", False)]
    assert len(cpus) == 2 and all(p in mi.teamB for p in cpus) and mi.teamB_captain in cpus
    await w.cmd("cpu", host, ch, "add", "A")
    assert len(mi.teamA) == 2 and mi.teamA_captain == host.member, "a human keeps the captaincy"
    await w.cmd("players", host, ch)
    assert "(CPU)" in last(ch)
    other = make_players(w, ["Guest"])[0]
    await w.cmd("cpu", other, ch, "add")
    assert "Only the host" in last(ch)
    await w.cmd("cpu", host, ch, "remove", mi.teamA[1].name)
    assert len(mi.teamA) == 1
    await w.cmd("so", host, ch, 10)
    await w.cmd("sd", host, ch, 2)
    mi.match_settings["overs"] = 2
    from core.backend.views.toss_view import TossView
    from core.backend.views.batball_view import BatBallView
    await w.cmd("toss", host, ch)
    toss = next((m for m in reversed(ch.messages) if isinstance(m.view, TossView)), None)
    if toss is not None and not toss.view.decided:      # (a CPU caller has already called it)
        assert toss.view.allowed_user == host.member
        await w.click(toss, host, "Heads")
        await asyncio.sleep(0.01)
    await wait_until(lambda: mi.toss_winner is not None, timeout=5)
    if mi.toss_winner == host.member:
        bb = next(m for m in reversed(ch.messages) if isinstance(m.view, BatBallView))
        await w.click(bb, host, "Bat")
    await wait_until(lambda: mi.batting_turn is not None, timeout=5)
    await w.cmd("start", host, ch)
    assert mi.game_started, last(ch)
    await w.finish(mi, timeout=90)
    assert mi.result and mi.result["type"] in ("win", "draw", "tie")
    for card in all_cards(mi):
        check_card_consistency(card)
    # CPUs got no DMs and the match didn't count
    assert await w.db.fetch("SELECT * FROM profiles") == []
    result_msg = next(m for m in reversed(ch.messages) if any(f.filename.endswith(".json") for f in m.files))
    sheet = json.loads(next(f for f in result_msg.files if f.filename.endswith(".json")).fp.getvalue())
    assert sheet["cpu_match"] is True
    assert any(p["cpu"] for p in sheet["players"])


@run
async def test_cpu_players_survive_a_restart():
    from core.backend.instance import MatchInstance
    from core.backend.cpu import CpuPlayer
    w = World()
    await w.setup()
    ch = w.channel()
    host = make_players(w, ["Host"])[0]
    await w.cmd("create", host, ch)
    await w.cmd("cpu", host, ch, "add", "B")
    mi = w.bot.active_matches[ch.id]
    state = json.loads(json.dumps(mi.to_state()))
    mi2 = await MatchInstance.from_state(w.bot, ch, state)
    cpu = mi2.teamB[0]
    assert isinstance(cpu, CpuPlayer) and cpu.name == mi.teamB[0].name and mi2.teamB_captain == cpu


# ───────────────────────────────────────────────────────────────── match sheet
@run
async def test_match_sheet_is_attached_with_the_result_and_can_be_downloaded_again():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1", "RepA"], strategy=never_out)
    b = make_players(w, ["B0", "B1"], strategy=never_out)
    mi = await start_with(w, ch, a, b, reps=[a[2]], rep_run_cap=6, innings_overs=2)
    await w.finish(mi, timeout=90)
    result_msg = next(m for m in reversed(ch.messages) if m.files)
    names = [f.filename for f in result_msg.files]
    assert f"match_{mi.match_id}.json" in names and "Match sheet" in result_msg.text()
    assert ch.messages[-2].embed and ch.messages[-2].embed.title.startswith("🏆"), "sheet follows the result card"
    sheet = json.loads(next(f for f in result_msg.files if f.filename.endswith(".json")).fp.getvalue())
    for key in ("match_id", "title", "rules", "toss", "teams", "result", "innings", "players", "substitutions"):
        assert key in sheet, key
    assert sheet["match_id"] == mi.match_id and sheet["status"] == "completed"
    assert sheet["rules"]["rep_run_cap"] == 6 and sheet["rules"]["rep_can_bowl"] is False
    rep = next(p for p in sheet["players"] if p["name"] == "RepA")
    assert rep["rep"] is True and rep["batting"]["highest"] <= 6
    assert len(sheet["innings"]) == len(mi.innings_scorecards)
    total = sum(p["batting"]["runs"] for p in sheet["players"]) + sum(c["extras"] for c in sheet["innings"])
    assert total == sum(c["runs"] for c in sheet["innings"])
    assert sheet["result"]["text"]
    # nothing private: no Discord server/channel ids in the sheet
    text = json.dumps(sheet)
    assert str(ch.id) not in text and str(ch.guild.id) not in text
    # again from the channel, and by id from the database
    await w.cmd("matchsheet", a[0], ch)
    assert ch.messages[-1].files[0].filename == f"match_{mi.match_id}.json"
    w.bot.recent_matches.clear()
    await w.cmd("matchsheet", a[0], ch, mi.match_id)
    again = json.loads(ch.messages[-1].files[0].fp.getvalue())
    assert again["match_id"] == mi.match_id and again["result"]["text"] == sheet["result"]["text"]
    await w.cmd("matchsheet", a[0], ch, "nope")
    assert "couldn't find" in last(ch)


# ───────────────────────────────────────────────────────────────── soak
@run
async def test_soak_concurrent_matches_with_reps_cpus_and_random_play():
    import random
    from harness import random_strategy
    from core.backend.cpu import new_cpu
    rng = random.Random(7)
    w = World()
    await w.setup()
    matches = []
    for n in range(6):
        ch = w.channel(f"soak{n}")
        size_a, size_b = rng.randint(2, 4), rng.randint(2, 4)
        a = make_players(w, [f"S{n}A{i}" for i in range(size_a)], strategy=random_strategy)
        b = make_players(w, [f"S{n}B{i}" for i in range(size_b)], strategy=random_strategy)
        reps = [p for p in a[1:] + b[1:] if rng.random() < 0.4]
        mi = await start_with(w, ch, a, b, reps=reps, overs=2, days=2, innings_overs=2,
                              rep_run_cap=rng.choice([3, 6, 10]),
                              rep_retire_counts_wicket=rng.random() < 0.5)
        if n % 2 == 0:
            # a CPU joins mid-match as a substitute for the last non-captain player of team B
            bot_player = new_cpu(mi)
            out = mi.teamB[-1]
            await wait_until(lambda: mi.awaiting_ball or mi.phase == "finished", timeout=20)
            if mi.phase != "finished" and out != mi.teamB_captain:
                async with mi.lock:
                    if mi.game.substitution_problem(out, bot_player) is None:
                        mi.game.apply_substitution(out, bot_player, as_rep=False)
        matches.append(mi)
    await asyncio.gather(*[w.finish(mi, timeout=110) for mi in matches])
    for mi in matches:
        assert mi.result and mi.result["type"] in ("win", "draw", "tie"), mi.result
        for card in all_cards(mi):
            check_card_consistency(card)
            cap = mi.match_settings["rep_run_cap"]
            for r in card["batting"]:
                if r["rep"]:
                    assert r["runs"] <= cap
            if not mi.match_settings["rep_can_bowl"]:
                assert not any(r["rep"] for r in card["bowling"])
