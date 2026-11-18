import asyncio

import discord

from harness import World, make_players, never_out, wait_until
from util import run


def last(ch):
    return ch.messages[-1].text()


async def lobby(n=4):
    w = World()
    await w.setup()
    ch = w.channel()
    p = make_players(w, [f"P{i}" for i in range(n)])
    await w.cmd("create", p[0], ch)
    for x in p[1:]:
        await w.cmd("join", x, ch)
    return w, ch, p, w.bot.active_matches[ch.id]


@run
async def test_create_join_leave_and_limits():
    w, ch, p, mi = await lobby(4)
    assert [m.name for m in mi.teamA] == ["P0", "P2"] and [m.name for m in mi.teamB] == ["P1", "P3"]
    assert mi.teamA_captain.name == "P0" and mi.teamB_captain.name == "P1"
    await w.cmd("create", p[1], ch)
    assert "already active" in last(ch)
    await w.cmd("join", p[2], ch)
    assert "already joined" in last(ch)
    await w.cmd("join", p[2], ch, "nonsense")
    assert "Invalid representative" in last(ch)
    await w.cmd("leave", p[0], ch)
    assert "host cannot leave" in last(ch)
    await w.cmd("leave", p[1], ch)
    assert "captain cannot leave" in last(ch)
    await w.cmd("leave", p[3], ch)
    assert "has left" in last(ch) and len(mi.players) == 3
    # rep join is tagged (R) and not duplicated (old bug)
    await w.cmd("join", p[3], ch, "rep")
    assert mi.players.count(p[3].member) == 1 and p[3].member in mi.reps
    await w.cmd("players", p[0], ch)
    assert "(R)" in last(ch) and "(H)" in last(ch) and "(C)" in last(ch)
    # bots can't join; lobby lock
    robot = discord.Member("Robo", w.guild, bot=True)
    await w.bot.invoke_command("join", w.ctx(robot, ch))
    assert "Bots can't join" in last(ch)
    await w.cmd("ll", p[1], ch)
    assert "Only the host" in last(ch)
    await w.cmd("ll", p[0], ch)
    late = make_players(w, ["Late"])[0]
    await w.cmd("join", late, ch)
    assert "locked" in last(ch)
    await w.cmd("ul", p[0], ch)
    await w.cmd("join", late, ch)
    assert "has joined" in last(ch)


@run
async def test_join_button_respects_lock_and_refreshes_card():
    w, ch, p, mi = await lobby(2)
    card = ch.messages[0]
    newbie = make_players(w, ["New"])[0]
    inter = await w.click(card, newbie, "Join Match")
    assert newbie.member in mi.players
    assert "2/22" not in card.text() and "3/22" in card.text(), "lobby card refreshed"
    again = await w.click(card, newbie, "Join Match")
    assert "already joined" in again.response.sent[0]["content"]
    mi.lobby_lock = True
    other = make_players(w, ["Other"])[0]
    inter = await w.click(card, other, "Join Match")
    assert "locked" in inter.response.sent[0]["content"] and other.member not in mi.players
    leave = await w.click(card, newbie, "Leave")
    assert newbie.member not in mi.players


@run
async def test_host_settings_and_validation():
    w, ch, p, mi = await lobby(4)
    await w.cmd("so", p[0], ch, 5)
    assert "between 10 and 90" in last(ch)
    await w.cmd("so", p[1], ch, 20)
    assert "Only the host" in last(ch)
    await w.cmd("so", p[0], ch, 20)
    await w.cmd("sd", p[0], ch, 9)
    assert "between 1 and 5" in last(ch)
    await w.cmd("sd", p[0], ch, 3)
    assert mi.match_settings["overs"] == 20 and mi.match_settings["days"] == 3
    await w.cmd("ctn", p[0], ch, "a", new_name="Mumbai *Mavericks*")
    assert mi.team_settings["Team A name"] == "Mumbai \\*Mavericks\\*"
    await w.cmd("ctn", p[0], ch, "z", new_name="X")
    assert "Invalid team" in last(ch)
    await w.cmd("settings", p[0], ch)
    assert "innings_overs" in last(ch)
    await w.cmd("settings", p[0], ch, "follow_on_pct", 60)
    assert mi.match_settings["follow_on_pct"] == 60
    await w.cmd("settings", p[0], ch, "ball_timeout", 500)
    assert "between" in last(ch)
    for key in ("teams", "captains", "overs", "settings", "score"):
        await w.cmd("show", p[1], ch, key)
        assert "Information" in last(ch)
    await w.cmd("show", p[1], ch, "bot")
    assert "Choose one of" in last(ch), "arbitrary attributes must not be exposed (B16)"
    await w.cmd("instance", p[1], ch)
    assert "Match Instance Details" in last(ch)   # B12: used to raise AttributeError


@run
async def test_captain_host_kick_swap():
    w, ch, p, mi = await lobby(6)       # A: P0 P2 P4   B: P1 P3 P5
    A, B = mi.teamA, mi.teamB
    # change captain: must be on that team; host or that captain
    await w.cmd("cc", p[0], ch, "a", p[1].member)
    assert "must be a player in" in last(ch)
    await w.cmd("cc", p[3], ch, "b", p[5].member)
    assert "Only the host or that team's current captain" in last(ch)
    await w.cmd("cc", p[1], ch, "b", p[5].member)
    assert mi.teamB_captain == p[5].member
    # change host (B15: used to compare id with Member)
    outsider = make_players(w, ["Out"])[0]
    await w.cmd("ch", p[0], ch, outsider.member)
    assert "must be a player" in last(ch)
    await w.cmd("ch", p[0], ch, p[2].member)
    assert mi.host == p[2].member
    # kick (B5): captain can kick from own team only, host anyone, nobody kicks the host
    await w.cmd("kick", p[5], ch, p[4].member)
    assert "Only the host or captains" in last(ch)
    await w.cmd("kick", p[5], ch, p[3].member)
    assert p[3].member not in mi.players and p[3].member not in B
    await w.cmd("kick", p[0], ch, p[2].member)
    assert "Only the host" in last(ch) or "host can't be kicked" in last(ch)
    await w.cmd("kick", p[2], ch, p[2].member)
    assert "host can't be kicked" in last(ch)
    # kicking a captain hands the armband to the next player
    await w.cmd("kick", p[2], ch, p[5].member)
    assert mi.teamB_captain == p[1].member
    # swap (B5) keeps captaincy with the team
    await w.cmd("swap", p[2], ch, p[0].member, p[1].member)
    assert p[1].member in mi.teamA and p[0].member in mi.teamB
    assert mi.teamA_captain == p[1].member and mi.teamB_captain == p[0].member
    await w.cmd("swap", p[2], ch, p[0].member, p[0].member)
    assert "different teams" in last(ch)


@run
async def test_toss_and_start_guards():
    w, ch, p, mi = await lobby(1)
    await w.cmd("toss", p[0], ch)
    assert "Both teams need" in last(ch)
    late = make_players(w, ["Q"])[0]
    await w.cmd("join", late, ch)
    await w.cmd("start", p[0], ch)
    assert "overs per day" in last(ch) and "toss" in last(ch)
    await w.cmd("toss", late, ch)
    assert "Only the host" in last(ch)
    await w.cmd("toss", p[0], ch)
    toss = ch.messages[-1]
    wrong = mi.teamA_captain if toss.view.allowed_user != mi.teamA_captain else mi.teamB_captain
    inter = await w.click(toss, wrong, "Heads")
    assert "not allowed" in inter.response.sent[0]["content"]
    await w.click(toss, toss.view.allowed_user, "Tails")
    await asyncio.sleep(0.01)
    bb = ch.messages[-1]
    bb_view, chooser = bb.view, bb.view.allowed_user
    await w.click(bb, chooser, "Bowl")
    assert bb.view is None
    again = discord.Interaction(user=chooser, channel=ch, client=w.bot, message=bb)
    await bb_view.create_bat_button.callback(again)
    assert "already been made" in again.response.sent[0]["content"]
    await w.cmd("so", p[0], ch, 10)
    await w.cmd("sd", p[0], ch, 1)
    for x in (p[0], late):
        x.strategy = never_out
    await w.cmd("start", p[0], ch)
    assert mi.game_started and mi.task is not None
    def since(n):
        return "\n".join(m.text() for m in ch.messages[n:])
    n = len(ch.messages)
    await w.cmd("start", p[0], ch)
    assert "already started" in since(n)
    n = len(ch.messages)
    await w.cmd("join", make_players(w, ["Z"])[0], ch)
    assert "already started" in since(n)
    n = len(ch.messages)
    await w.cmd("so", p[0], ch, 20)
    assert "already started" in since(n)
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)


@run
async def test_toss_timeout_allows_retoss():
    w, ch, p, mi = await lobby(2)
    await w.cmd("toss", p[0], ch)
    await asyncio.sleep(0.5)
    assert "Toss timed out" in last(ch)
    await w.cmd("toss", p[0], ch)
    assert ch.messages[-1].view is not None


@run
async def test_dm_commands_are_refused_and_yeet_lobby():
    w, ch, p, mi = await lobby(2)
    dm_ctx = w.ctx(p[0].member, p[0].member.dm_channel)
    await w.bot.invoke_command("create", dm_ctx)
    assert "only works in a server" in p[0].member.dm_channel.messages[-1].text()
    await w.cmd("yeet", p[0], ch)
    await w.click(ch.messages[-1], p[0], "Yes")
    assert ch.id not in w.bot.active_matches
    assert await w.db.fetch("SELECT * FROM ongoing_matches") == []
    await w.cmd("players", p[0], ch)
    assert "No active match" in last(ch)


@run
async def test_scorecard_score_help_and_error_handler():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["A0", "A1", "A2"], strategy=never_out)
    b = make_players(w, ["B0", "B1", "B2"], strategy=never_out)
    mi = await w.setup_match(ch, a, b, innings_overs=2)
    await wait_until(lambda: 1 in mi.innings_scorecards and mi.innings == 2 and mi.overs >= 1)
    await w.cmd("scorecard", a[1], ch)
    msg = ch.messages[-1]
    assert "2nd innings" in msg.text() and msg.view is not None   # live card + innings switcher
    await w.cmd("sc", a[1], ch, "1")
    assert "1st innings" in last(ch) and "Bowling" in last(ch)
    await w.cmd("sc", a[1], ch, "4")
    assert "hasn't been played" in last(ch)
    await w.cmd("score", a[1], ch)
    assert "MATCH SUMMARY" in last(ch)
    # select menu switches innings
    sel = msg.view.children[0]
    sel.values = ["1"]
    inter = discord.Interaction(user=a[1].member, channel=ch, client=w.bot, message=msg)
    await sel.callback(inter)
    assert "1st innings" in msg.text()
    mi.match_abandoned = True
    mi.interrupt.set()
    await w.finish(mi)
    for topic in (None, "rules", "economy", "stats", "lobby", "play"):
        await w.cmd("help", a[0], ch, topic)
        help_msg = ch.messages[-1]
        assert help_msg.embed is not None
    # help select works
    hs = help_msg.view.children[0]
    hs.values = ["rules"]
    await hs.callback(discord.Interaction(user=a[0].member, channel=ch, client=w.bot, message=help_msg))
    assert "Follow-on" in help_msg.text()
    await w.cmd("so", a[0], ch)   # missing argument -> friendly usage
    assert "No active match" in last(ch) or "Missing required argument" in last(ch)
    await w.cmd("dump", a[0], ch)
    assert "Only the bot owner" in last(ch)
