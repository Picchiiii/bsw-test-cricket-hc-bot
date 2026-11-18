"""Ball-engine rules, each checked through a real (simulated) match."""
import asyncio
import random

import discord

from harness import World, make_players, Script, never_out, wait_until
from util import run, check_card_consistency


async def start(script, na=2, nb=2, overs=10, days=4, **settings):
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, [f"A{i}" for i in range(na)], strategy=script)
    b = make_players(w, [f"B{i}" for i in range(nb)], strategy=script)
    mi = await w.setup_match(ch, a, b, overs=overs, days=days, **settings)
    return w, ch, mi, a, b


@run
async def test_no_ball_gives_run_replays_ball_and_cannot_dismiss():
    # bowler 0 + batter 0 -> no-ball (not a dismissal, not a dot); then a clash ends the 2-player innings
    script = Script(batsman=[0, 3], bowler=[0, 3])
    w, ch, mi, a, b = await start(script)
    await wait_until(lambda: 1 in mi.innings_scorecards)
    card = mi.innings_scorecards[1]
    assert card["runs"] == 1 and card["extras"] == 1 and card["wickets"] == 1
    assert card["balls"] == 1, "a no-ball must not count as a legal delivery"
    assert card["bowling"][0]["no_balls"] == 1 and card["bowling"][0]["runs"] == 1
    assert card["batting"][0]["balls"] == 1 and card["batting"][0]["dots"] == 0
    assert "No Ball!" in ch.all_text()
    check_card_consistency(card)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_fifth_dot_in_an_over_is_out_without_bowler_wicket():
    script = Script(batsman=[0, 0, 0, 0, 0], bowler=[1, 1, 1, 1, 1])
    w, ch, mi, a, b = await start(script)
    await wait_until(lambda: 1 in mi.innings_scorecards)
    card = mi.innings_scorecards[1]
    out = card["batting"][0]
    assert out["dismissal"] == "four_zeros" and out["balls"] == 5 and out["dots"] == 4
    assert card["bowling"][0]["wickets"] == 0, "five-dot dismissals are not credited to the bowler (B6)"
    assert card["wickets"] == 1
    assert "Out by Four 0s" in ch.all_text()
    check_card_consistency(card)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_new_batter_gets_fresh_dot_count_mid_over():
    # batter 1: three dots then out by clash; batter 2 then plays two dots in the same over -> NOT out (B7)
    script = Script(batsman=[0, 0, 0, 2, 0, 0], bowler=[1, 1, 1, 2, 1, 1], fallback=never_out)
    w, ch, mi, a, b = await start(script, na=3, nb=3, innings_overs=2)
    await wait_until(lambda: mi.overs >= 1 or 1 in mi.innings_scorecards)
    assert mi.wickets == 1
    second = mi.game.row(mi.curr_batsman)
    assert not second["is_out"] and second["dots"] == 2
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_hattrick_and_bowler_rotation():
    # 4 batters -> all out at 3 wickets; three straight clashes = hat-trick for one bowler
    script = Script(batsman=[1, 2, 3], bowler=[1, 2, 3])
    w, ch, mi, a, b = await start(script, na=4, nb=4)
    await wait_until(lambda: 1 in mi.innings_scorecards)
    card = mi.innings_scorecards[1]
    assert card["wickets"] == 3 and card["balls"] == 3
    bowler = card["bowling"][0]
    assert bowler["wickets"] == 3 and bowler["hattricks"] == 1
    assert "HAT-TRICK" in ch.all_text()
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_no_bowler_bowls_consecutive_overs_and_fifty_milestone():
    w, ch, mi, a, b = await start(never_out, na=3, nb=3, innings_overs=5)
    await wait_until(lambda: 1 in mi.innings_scorecards, timeout=30)
    card = mi.innings_scorecards[1]
    assert card["balls"] == 30 and card["wickets"] == 0   # stopped by the innings over cap
    # reconstruct who bowled each over from the over-complete embeds
    overs = [m for m in ch.messages if m.embed and (m.embed.title or "").startswith("Over ")]
    names = []
    for m in overs:
        fig = [f.name for f in m.embed.fields if f.name.endswith("Figures")][0]
        names.append(fig.replace("'s Figures", ""))
    assert all(x != y for x, y in zip(names, names[1:])), names
    assert "FIFTY!" in ch.all_text()
    check_card_consistency(card)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_afk_batter_strikes_then_out_and_strikes_reset_on_response():
    # batter misses twice, answers (strikes reset), then misses 3 in a row -> out (afk_timeout)
    script = Script(batsman=[None, None, 1, None, None, None], bowler=[2, 2, 2, 2, 2, 2, 2, 2], fallback=never_out)
    w, ch, mi, a, b = await start(script)
    await wait_until(lambda: 1 in mi.innings_scorecards, timeout=30)
    card = mi.innings_scorecards[1]
    out = card["batting"][0]
    assert out["dismissal"] == "afk_timeout"
    assert out["runs"] == 1
    assert card["bowling"][0]["wickets"] == 0
    text = ch.all_text()
    assert "strike 1/3" in text and "strike 2/3" in text
    assert text.count("strike 2/3") == 2, "strikes must reset after the player answered"
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_afk_bowler_is_replaced_mid_over_and_not_used_again():
    script = Script(batsman=[2, 2, 2, 2, 2, 2], bowler=[3, None, None, None], fallback=never_out)
    w, ch, mi, a, b = await start(script, na=3, nb=3, innings_overs=3)
    await wait_until(lambda: 1 in mi.innings_scorecards, timeout=30)
    card = mi.innings_scorecards[1]
    assert len(card["bowling"]) >= 2
    first = card["bowling"][0]
    assert first["balls"] == 1, "AFK bowler only bowled one legal ball"
    assert "a new bowler must be chosen to finish the over" in ch.all_text()
    assert card["balls"] == 18
    check_card_consistency(card)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_closed_dms_warn_in_channel_and_count_as_afk():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1"], strategy=never_out)
    b = make_players(w, ["B0", "B1"], strategy=never_out)
    for p in a:
        p.member.forbidden_dm = True
    mi = await w.setup_match(ch, a, b)
    await wait_until(lambda: 1 in mi.innings_scorecards, timeout=30)
    assert "I can't DM you" in ch.all_text()
    assert mi.innings_scorecards[1]["batting"][0]["dismissal"] == "afk_timeout"
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_invalid_numbers_channel_messages_and_wrong_users_are_ignored():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1"], strategy=lambda *_: None)
    b = make_players(w, ["B0", "B1"], strategy=lambda *_: None)
    mi = await w.setup_match(ch, a, b)
    await wait_until(lambda: mi.curr_batsman is not None and mi.curr_bowler is not None and mi.scorecard_message)
    bat = mi.curr_batsman
    bowl = mi.curr_bowler
    from harness import prompt_role
    await wait_until(lambda: any(prompt_role(m) and not m.deleted for m in bat.dm_channel.messages))
    # 9 in DMs -> rejected; 3 typed in the server channel -> ignored; someone else's 3 -> ignored
    w.bot.dispatch("message", discord.Message(channel=bat.dm_channel, author=bat, content="9"))
    w.bot.dispatch("message", discord.Message(channel=ch, author=bat, content="3"))
    w.bot.dispatch("message", discord.Message(channel=bowl.dm_channel, author=bowl, content="5"))
    prompt = [m for m in bat.dm_channel.messages if prompt_role(m)][-1]
    assert prompt.view is None, "DM prompts are type-only (no buttons)"
    assert "Type your number" in prompt.text()
    await asyncio.sleep(0.05)
    assert any("Only numbers from **0 to 6**" in (m.content or "") for m in bat.dm_channel.messages)
    # valid answers from both
    w.bot.dispatch("message", discord.Message(channel=bat.dm_channel, author=bat, content="4"))
    await asyncio.sleep(0.05)
    assert mi.score == 4 and mi.balls_this_over == 1
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_stale_message_from_before_the_prompt_is_ignored():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1"], strategy=lambda *_: None)
    b = make_players(w, ["B0", "B1"], strategy=lambda *_: None)
    mi = await w.setup_match(ch, a, b)
    await wait_until(lambda: mi.curr_batsman is not None and mi.scorecard_message)
    bat = mi.curr_batsman
    stale = discord.Message(channel=bat.dm_channel, author=bat, content="6")
    from harness import prompt_role
    await wait_until(lambda: any(prompt_role(m) for m in bat.dm_channel.messages))
    stale.created_at = stale.created_at.replace(year=2000)
    w.bot.dispatch("message", stale)
    await asyncio.sleep(0.05)
    assert mi.score == 0
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)
