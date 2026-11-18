import asyncio
import random

import discord

from harness import World, make_players, Script, never_out, wait_until, random_strategy
from util import run, check_card_consistency, match_row
from core.backend.checks import GameChecks
from core.backend.game import Game


async def new_match(strategy=never_out, na=3, nb=3, overs=10, days=4, **settings):
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, [f"A{i}" for i in range(na)], strategy=strategy)
    b = make_players(w, [f"B{i}" for i in range(nb)], strategy=strategy)
    mi = await w.setup_match(ch, a, b, overs=overs, days=days, **settings)
    return w, ch, mi, a, b


def last_msg(ch, contains):
    for m in reversed(ch.messages):
        if contains in m.text():
            return m
    raise AssertionError(f"no message containing {contains!r}")


@run
async def test_declaration_rules_and_flow():
    w, ch, mi, a, b = await new_match(min_declare_overs=1, innings_overs=0)
    cap_bat = mi.captain(mi.batting_turn)
    cap_bowl = mi.captain(mi.bowling_turn)
    await wait_until(lambda: mi.scorecard_message is not None)
    # too early
    await w.cmd("declare", cap_bat, ch)
    assert "overs must be bowled" in ch.messages[-1].text()
    # wrong person
    await w.cmd("declare", cap_bowl, ch)
    assert "Only the captain of the batting team" in ch.messages[-1].text()
    await wait_until(lambda: mi.overs >= 1)
    await w.cmd("declare", cap_bat, ch)
    prompt = ch.messages[-1]
    assert prompt.view is not None
    # a non-captain can't press it
    intruder = discord.Interaction(user=cap_bowl, channel=ch, client=w.bot, message=prompt)
    await prompt.view.create_yes_button.callback(intruder)
    assert intruder.response.sent
    await w.click(prompt, cap_bat, "Yes")
    await wait_until(lambda: 1 in mi.innings_scorecards)
    card = mi.innings_scorecards[1]
    assert card["declared"] and card["wickets"] == 0
    assert mi.innings_history["innings_1"]["score"].endswith("d")
    await wait_until(lambda: mi.innings == 2 and mi.phase == "innings")
    assert not mi.innings_declared, "flag must reset for the next innings"
    check_card_consistency(card)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_cannot_declare_in_fourth_innings():
    w, ch, mi, a, b = await new_match()
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)
    from core.backend.views.declare_view import declaration_block_reason
    mi.game_started, mi.phase, mi.innings, mi.overs = True, "innings", 4, 20
    mi.match_abandoned = False
    assert "final innings" in declaration_block_reason(mi, mi.captain(mi.batting_turn))


async def _follow_on_match(enforce: bool):
    # Innings 1: team A scores freely (never out) for 2 overs; innings 2: team B collapses immediately.
    state = {"phase": 1}

    def strat(role, player, mi):
        if mi is None:
            return 1
        if mi.innings == 1:
            return 1 if role == "bowler" else 6
        if mi.innings == 2:
            return 3   # clash every ball -> quick all out
        return random_strategy(role, player, mi)
    w = World()
    w.follow_on = enforce
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1", "A2"], strategy=strat)
    b = make_players(w, ["B0", "B1", "B2"], strategy=strat)
    mi = await w.setup_match(ch, a, b, overs=10, days=4, innings_overs=2)
    await w.finish(mi)
    return w, ch, mi


@run
async def test_follow_on_enforced():
    w, ch, mi = await _follow_on_match(True)
    assert mi.innings_scorecards[1]["team"] == "A"
    assert mi.innings_scorecards[2]["team"] == "B"
    assert mi.innings_scorecards[3]["team"] == "B", "follow-on: same team bats again"
    assert mi.innings_scorecards[3]["follow_on"]
    assert "enforced the follow-on" in ch.all_text()
    if 4 in mi.innings_scorecards:
        assert mi.innings_scorecards[4]["team"] == "A"
    else:
        assert "an innings and" in mi.game.result_text()
    for c in mi.innings_scorecards.values():
        check_card_consistency(c)


@run
async def test_follow_on_declined_normal_alternation():
    w, ch, mi = await _follow_on_match(False)
    assert "declined the follow-on" in ch.all_text()
    assert mi.innings_scorecards[3]["team"] == "A"
    assert not mi.innings_scorecards[3]["follow_on"]


@run
async def test_stumps_next_day_and_draw_when_days_run_out():
    w, ch, mi, a, b = await new_match(overs=1, days=2, innings_overs=0)
    await w.finish(mi)
    text = ch.all_text()
    assert "Stumps — End of Day 1" in text
    assert "Day 2" in text
    assert mi.result["type"] == "draw" and mi.result["reason"] == "days_exhausted"
    assert mi.crr_day == 2
    assert mi.innings_scorecards[1]["balls"] == 12, "2 days x 1 over, innings never ended"
    row = await match_row(w.db, mi.match_id)
    assert row["result_text"] == "Match drawn"
    profs = await w.db.fetch("SELECT matches_drawn FROM profiles")
    assert all(p["matches_drawn"] == 1 for p in profs)


@run
async def test_manual_resume_permissions_and_day_counter():
    w = World()
    w.auto_next_day = False
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1"], strategy=never_out)
    b = make_players(w, ["B0", "B1", "B2"], strategy=never_out)
    outsider = make_players(w, ["Zed"])[0]
    mi = await w.setup_match(ch, a, b, overs=1, days=3, innings_overs=0)
    await wait_until(lambda: mi.stumps_called)
    balls_at_stumps = mi.overs * 6 + mi.balls_this_over
    await asyncio.sleep(0.2)
    assert mi.overs * 6 + mi.balls_this_over == balls_at_stumps, "no play during stumps"
    await w.cmd("resume", outsider, ch)
    assert "Only the host or a captain" in ch.messages[-1].text()
    await w.cmd("resume", b[0], ch)     # a captain may start the next day
    assert "Day 2" in ch.messages[-1].text()
    assert mi.crr_day == 2 and not mi.stumps_called and mi.overs_in_the_day == 0
    await wait_until(lambda: mi.stumps_called and mi.crr_day == 2)
    await w.cmd("nd", a[0], ch)
    await w.finish(mi)
    assert mi.result["type"] == "draw" and mi.crr_day == 3


@run
async def test_pause_and_resume():
    w, ch, mi, a, b = await new_match(innings_overs=0)
    await wait_until(lambda: mi.overs >= 1)
    await w.cmd("pause", b[0], ch)
    assert "Only the host" in ch.messages[-1].text()
    await w.cmd("pause", a[0], ch)
    await asyncio.sleep(0.4)
    frozen = (mi.overs, mi.balls_this_over)
    await asyncio.sleep(0.3)
    assert (mi.overs, mi.balls_this_over) == frozen
    await w.cmd("resume", a[0], ch)
    await wait_until(lambda: (mi.overs, mi.balls_this_over) != frozen)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_abandon_mid_match_records_nothing():
    w, ch, mi, a, b = await new_match(innings_overs=0)
    await wait_until(lambda: mi.overs >= 1)
    await w.cmd("yeet", b[0], ch)
    assert "Only the host" in ch.messages[-1].text()
    await w.cmd("yeet", a[0], ch)
    await w.click(ch.messages[-1], a[0], "Yes")
    await w.finish(mi)
    assert ch.id not in w.bot.active_matches
    assert "Match abandoned" in ch.all_text()
    assert await w.db.fetch("SELECT * FROM profiles") == []
    row = await match_row(w.db, mi.match_id)
    assert row["status"] == "abandoned"
    assert await w.db.fetch("SELECT * FROM ongoing_matches") == []


@run
async def test_abandon_during_stumps_wakes_the_match():
    w = World()
    w.auto_next_day = False
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1"], strategy=never_out)
    b = make_players(w, ["B0", "B1"], strategy=never_out)
    mi = await w.setup_match(ch, a, b, overs=1, days=3, innings_overs=0)
    await wait_until(lambda: mi.stumps_called)
    await w.cmd("yeet", a[0], ch)
    await w.click(ch.messages[-1], a[0], "Yes")
    await w.finish(mi, timeout=5)
    assert mi.result["type"] == "abandoned"


# ───────────────────────────── result maths (unit level on a real MatchInstance)
async def _bare(na=3, nb=3):
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, [f"A{i}" for i in range(na)])
    b = make_players(w, [f"B{i}" for i in range(nb)])
    await w.cmd("create", a[0], ch)
    mi = w.bot.active_matches[ch.id]
    mi.teamA = [p.member for p in a]
    mi.teamB = [p.member for p in b]
    mi.players = mi.teamA + mi.teamB
    mi.teamA_captain, mi.teamB_captain = mi.teamA[0], mi.teamB[0]
    game = Game(None, mi)
    await game.initialise()
    mi.game_started = True
    return w, mi, game


def _set_totals(mi, a1, b1, a2=None, b2=None):
    mi.teamA_scores["inning_one"].update(runs=a1, batted=True)
    mi.teamB_scores["inning_one"].update(runs=b1, batted=True)
    if a2 is not None:
        mi.teamA_scores["inning_two"].update(runs=a2, batted=True)
    if b2 is not None:
        mi.teamB_scores["inning_two"].update(runs=b2, batted=True)


@run
async def test_target_and_results():
    w, mi, game = await _bare()
    # A 100 & 80, B 120 -> B need 61
    _set_totals(mi, 100, 120, a2=80)
    mi.batting_turn, mi.bowling_turn, mi.innings, mi.phase = "B", "A", 4, "innings"
    mi.target = game.compute_target()
    assert mi.target == 61
    # chased with 1 wicket down out of a 3-player side (limit 2) -> won by 1 wicket
    mi.score, mi.wickets = 61, 1
    assert not await GameChecks.game_continue_check(mi)
    game.compute_result()
    assert mi.result["winner"] == "B" and mi.result["margin"] == "1 wicket"
    # bowled out 10 short -> A win by 10 runs
    mi.result = None
    mi.score, mi.wickets = 50, 2
    game.compute_result()
    assert mi.result == {"type": "win", "winner": "A", "margin": "10 runs", "reason": "all_out"}
    # bowled out with scores level -> tie
    mi.result = None
    mi.score = 60
    game.compute_result()
    assert mi.result["type"] == "tie"
    # innings ended by the over cap without result -> draw
    mi.result = None
    mi.score, mi.wickets = 30, 0
    game.compute_result()
    assert mi.result["type"] == "draw"


@run
async def test_innings_victory_without_fourth_innings():
    w, mi, game = await _bare()
    # A 200 (inns 1); B 50 & 60 (f/o) -> A win by an innings and 90 runs
    mi.innings_scorecards = {1: {"runs": 200, "balls": 30}, 2: {"runs": 50, "balls": 10}, 3: {"runs": 60, "balls": 12}}
    _set_totals(mi, 200, 50, b2=60)
    mi.batting_turn, mi.bowling_turn = "B", "A"   # B batted in innings 3
    mi.phase = "break"
    mi.innings = 3
    await game.end_innings(3)
    assert mi.phase == "finished"
    assert mi.result["winner"] == "A" and mi.result["margin"] == "an innings and 90 runs"


@run
async def test_no_ball_can_complete_a_chase():
    w, mi, game = await _bare()
    _set_totals(mi, 10, 10, a2=5)
    mi.batting_turn, mi.bowling_turn, mi.innings, mi.phase = "B", "A", 4, "innings"
    mi.target = game.compute_target()
    assert mi.target == 6
    mi.score = 5
    mi.curr_batsman, mi.curr_bowler = mi.teamB[0], mi.teamA[0]
    game.row(mi.curr_batsman)
    await game.handle_noball()
    assert mi.score == 6
    assert not await GameChecks.game_continue_check(mi)
    game.compute_result()
    assert mi.result["winner"] == "B" and "wicket" in mi.result["margin"]


@run
async def test_all_out_limits():
    w, mi, game = await _bare(na=1, nb=4)
    mi.batting_turn = "A"
    assert GameChecks.all_out_limit(mi) == 1      # 1-player side: one wicket ends it
    mi.batting_turn = "B"
    assert GameChecks.all_out_limit(mi) == 3      # last man can't bat alone (spec §5.5)
    mi.match_settings["last_man_bats"] = True
    assert GameChecks.all_out_limit(mi) == 4


@run
async def test_one_v_one_and_uneven_teams_complete():
    random.seed(11)
    for na, nb in ((1, 1), (4, 2)):
        w, ch, mi, a, b = await new_match(strategy=random_strategy, na=na, nb=nb, overs=2, days=5)
        await w.finish(mi)
        assert mi.phase == "finished" and mi.result["type"] in ("win", "draw", "tie")
        for c in mi.innings_scorecards.values():
            check_card_consistency(c)
