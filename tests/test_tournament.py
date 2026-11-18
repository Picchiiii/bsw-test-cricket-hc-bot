"""Tournament mode end to end: set-up, registration, teams, fixtures, tournament matches, tables, knockouts."""
import asyncio

import discord

import tutil
from harness import Player
from tutil import fixtures, last, make_teams, mention, play_fixture, tour, tournament, world
from util import run


@run
async def test_create_needs_permission_and_one_per_server():
    w, ch, admin = await world()
    pleb = Player(w, "Pleb")
    assert "Manage Server" in await tour(w, pleb, ch, "create", "Nope")
    assert "no tournament" in await tour(w, pleb, ch)
    out = await tour(w, admin, ch, "create", "Summer", "Cup")
    assert "Summer Cup created" in out
    assert "already running" in await tour(w, admin, ch, "create", "Second")
    t = await tournament(w, ch)
    assert t["status"] == "setup" and t["host_id"] == str(admin.member.id) and t["settings"]["format"] == "league"
    # another server can run its own tournament at the same time
    other = discord.Guild("Other")
    w.bot.guilds.append(other)
    och = discord.TextChannel(other, "x", bot_user=w.bot.user)
    boss = discord.Member("Boss", other)
    boss.guild_permissions.administrator = True
    await w.bot.invoke_command("tour", w.ctx(boss, och), "create", "Other", "Cup")
    assert "Other Cup created" in och.messages[-1].text()
    # overview, settings, help and rules render within Discord's limits
    for args in ((), ("settings",), ("help",), ("rules",), ("teams",), ("fixtures",), ("table",), ("bracket",),
                 ("stats",), ("history",), ("staff",), ("role",), ("channel",), ("players",), ("log",)):
        await tour(w, admin, ch, *args)
    assert "I don't know" in await tour(w, admin, ch, "frobnicate")


@run
async def test_settings_roles_and_organisers():
    w, ch, admin = await world()
    await tour(w, admin, ch, "create", "Cup")
    pleb = Player(w, "Pleb")
    assert "Only tournament organisers" in await tour(w, pleb, ch, "set", "overs", "20")
    assert "is now **20**" in await tour(w, admin, ch, "set", "overs", "20")
    assert "between" in await tour(w, admin, ch, "set", "overs", "999")
    assert "no setting" in await tour(w, admin, ch, "set", "bogus", "1")
    assert "must be one of" in await tour(w, admin, ch, "format", "swiss")
    assert "groups" in await tour(w, admin, ch, "format", "groups")
    # prize settings mint coins: bot owner only
    assert "bot owner" in await tour(w, admin, ch, "set", "prize_champion", "500")
    w.bot.owner_ids.add(admin.member.id)
    assert "is now **500**" in await tour(w, admin, ch, "set", "prize_champion", "500")
    w.bot.owner_ids.discard(admin.member.id)
    # organiser role and staff give access
    role = discord.Role(ch.guild, "Umpires")
    helper = Player(w, "Helper")
    assert "Organiser roles" in await tour(w, admin, ch, "role", "organizer", role.mention)
    assert "Only tournament organisers" in await tour(w, helper, ch, "set", "days", "3")
    helper.member.roles.append(role)
    assert "is now **3**" in await tour(w, helper, ch, "set", "days", "3")
    helper.member.roles.remove(role)
    assert "now a tournament organiser" in await tour(w, admin, ch, "staff", "add", mention(helper))
    assert "is now **1**" in await tour(w, helper, ch, "set", "days", "1")
    assert "no longer" in await tour(w, admin, ch, "staff", "remove", mention(helper))
    assert "Only tournament organisers" in await tour(w, helper, ch, "set", "days", "2")
    # channels
    news = w.channel("news")
    assert "Announcements channel" in await tour(w, admin, ch, "channel", "announce", news.mention)
    assert "Announcement sent" in await tour(w, admin, ch, "announce", "Hello", "everyone")
    assert "Hello everyone" in news.all_text()
    assert "not set" in await tour(w, admin, ch, "channel", "announce", "none")
    t = await tournament(w, ch)
    assert t["settings"]["announce_channel"] == "" and t["settings"]["overs"] == 20
    # host hand-over, rename, describe
    assert "now the tournament host" in await tour(w, admin, ch, "host", mention(helper))
    assert "is now called **Winter Shield**" in await tour(w, admin, ch, "name", "Winter", "Shield")
    await tour(w, admin, ch, "desc", "The", "big", "one")
    t = await tournament(w, ch)
    assert t["host_id"] == str(helper.member.id) and t["name"] == "Winter Shield" and t["description"] == "The big one"
    log = await w.db.fetch("SELECT action FROM tournament_audit WHERE tournament_id = ?", [t["tournament_id"]])
    assert {"create", "settings.set", "staff.add", "host.transfer", "rename"} <= {r["action"] for r in log}


@run
async def test_registration_teams_invites_and_rosters():
    w, ch, admin = await world()
    await tour(w, admin, ch, "create", "Cup")
    cap, p2, p3, p4 = (Player(w, n) for n in ("Cap", "Two", "Three", "Four"))
    assert "isn't open" in await tour(w, cap, ch, "register")
    await tour(w, admin, ch, "open")
    assert "registered" in await tour(w, cap, ch, "register")
    assert "already registered" in await tour(w, cap, ch, "register")
    assert "created" in await tour(w, cap, ch, "team", "create", "Night", "Owls")
    assert "already a team" in await tour(w, cap, ch, "team", "create", "night", "owls")
    t = await tournament(w, ch)
    from core.tournament import store
    team = (await store.list_teams(w.db, t["tournament_id"]))[0]
    assert team["tag"] == "NO" and team["captain_id"] == str(cap.member.id)
    # invites: the player must be registered, then accepts
    assert "hasn't registered" in await tour(w, cap, ch, "invite", mention(p2))
    await tour(w, p2, ch, "register")
    assert "Only a team captain" in await tour(w, p2, ch, "invite", mention(p3))
    out = await tour(w, cap, ch, "invite", mention(p2))
    assert "was invited" in out
    assert "Team invite" in p2.member.dm_channel.all_text()
    invite_msg = ch.messages[-1]
    await w.click(invite_msg, p2, "Accept")
    assert "joined **Night Owls**" in invite_msg.text()
    assert len(await store.roster(w.db, t["tournament_id"], team["team_id"])) == 2
    # accept by command, decline, and "invite only" joining
    await tour(w, p3, ch, "register")
    await tour(w, cap, ch, "invite", mention(p3))
    assert "Teams are joined by invite" in await tour(w, p3, ch, "team", "join", "NO")
    assert "declined" in await tour(w, p3, ch, "decline")
    assert "no invites" in await tour(w, p3, ch, "accept")
    await tour(w, cap, ch, "invite", mention(p3))
    assert "joined **Night Owls**" in await tour(w, p3, ch, "accept", "NO")
    # captaincy, vice, kick, leave
    assert "vice-captain" in await tour(w, cap, ch, "team", "vice", mention(p2))
    assert "captain" in await tour(w, cap, ch, "leave") and "hand over" in last(ch)
    assert "removed from **Night Owls**" in await tour(w, cap, ch, "team", "kick", mention(p3))
    assert "now captains" in await tour(w, cap, ch, "team", "captain", mention(p2))
    assert "left **Night Owls**" in await tour(w, cap, ch, "leave")
    assert "is now **Day Owls**" in await tour(w, p2, ch, "team", "rename", "Day", "Owls")
    assert "tag **DAY**" in await tour(w, p2, ch, "team", "tag", "day")
    # organiser powers: create with captain, add, move, ban, autofill, squad limit
    assert "created" in await tour(w, admin, ch, "team", "create", "Larks", mention(p4))
    assert "joined **Larks**" in await tour(w, admin, ch, "team", "add", "Larks", mention(p3))
    assert "(moved from Larks)" in await tour(w, admin, ch, "move", "DAY", mention(p3))
    await tour(w, admin, ch, "set", "max_squad", "2")
    assert "is full" in await tour(w, admin, ch, "team", "add", "DAY", mention(cap))
    assert "banned" in await tour(w, admin, ch, "ban", mention(cap))
    assert "is banned" in await tour(w, admin, ch, "team", "add", "Larks", mention(cap))
    assert "can register again" in await tour(w, admin, ch, "unban", mention(cap))
    await tour(w, cap, ch, "register")
    assert "Placed **1**" in await tour(w, admin, ch, "autofill")
    assert (await store.get_player(w.db, t["tournament_id"], cap.member.id))["team_id"]
    # roster lock stops captains but not organisers
    assert "locked" in await tour(w, admin, ch, "lock")
    assert "Rosters are locked" in await tour(w, p2, ch, "team", "kick", mention(p3))
    assert "removed" in await tour(w, admin, ch, "team", "remove", mention(p3))
    # bots and non-members can't be added; team card + me render
    robot = discord.Member("Robo", ch.guild, bot=True)
    assert "Bots can't" in await tour(w, admin, ch, "team", "add", "Larks", robot.mention)
    assert "couldn't find that member" in await tour(w, admin, ch, "team", "add", "Larks", "<@123456789012345678>")
    for args in (("team", "Larks"), ("me",), ("teams",), ("players",), ("player", mention(p2))):
        await tour(w, p2, ch, *args)
    assert "disbanded" in await tour(w, admin, ch, "team", "delete", "Larks")


@run
async def test_roles_are_assigned_and_removed():
    w, ch, admin = await world()
    await tour(w, admin, ch, "create", "Cup")
    g = ch.guild
    prole, crole = discord.Role(g, "Player"), discord.Role(g, "Captain")
    await tour(w, admin, ch, "role", "player", prole.mention)
    await tour(w, admin, ch, "role", "captain", crole.mention)
    await tour(w, admin, ch, "role", "auto", "on")
    await tour(w, admin, ch, "set", "team_join", "open")
    await tour(w, admin, ch, "open")
    cap, mate = Player(w, "Cap"), Player(w, "Mate")
    await tour(w, cap, ch, "register")
    assert prole not in cap.member.roles                      # the player role is for players on a team
    await tour(w, cap, ch, "team", "create", "Kites")
    team_role = next(r for r in g.roles if r.name == "Kites")
    assert {prole, crole, team_role} <= set(cap.member.roles)
    await tour(w, mate, ch, "register")
    await tour(w, mate, ch, "team", "join", "Kites")
    assert {prole, team_role} <= set(mate.member.roles) and crole not in mate.member.roles
    await tour(w, cap, ch, "team", "captain", mention(mate))
    assert crole in mate.member.roles and crole not in cap.member.roles
    await tour(w, mate, ch, "team", "rename", "Falcons")
    assert team_role.name == "Falcons"
    await tour(w, cap, ch, "leave")
    assert not {prole, team_role} & set(cap.member.roles)
    # missing permissions are reported, not fatal
    g.forbid_roles = True
    await tour(w, cap, ch, "team", "join", "Falcons")
    assert "Manage Roles" in last(ch)
    g.forbid_roles = False
    assert "Syncing" in await tour(w, admin, ch, "role", "sync")
    assert team_role in cap.member.roles
    assert "Removed tournament roles" in await tour(w, admin, ch, "role", "clear")
    assert not cap.member.roles and not mate.member.roles and team_role not in g.roles


@run
async def test_league_played_through_to_a_champion():
    tutil.STRONG.clear()
    tutil.STRONG.update({"L1", "L2"})                        # Lions always win; Tigers and Bears draw
    w, ch, admin = await world()
    news = w.channel("news")
    await tour(w, admin, ch, "create", "placeholder")
    await tour(w, admin, ch, "channel", "announce", news.mention)
    await tour(w, admin, ch, "delete", "confirm")
    teams = await make_teams(w, ch, admin, {"Lions": ["L1", "L2"], "Tigers": ["T1", "T2"], "Bears": ["B1", "B2"]},
                             start=False, settings={"qualifiers": 2})
    await tour(w, admin, ch, "channel", "announce", news.mention)
    assert "has started" in await tour(w, admin, ch, "start")
    t = await tournament(w, ch)
    assert t["status"] == "ongoing" and t["rosters_locked"]
    fx = await fixtures(w, ch)
    assert len(fx) == 3 and all(f["stage"] == "group" and f["status"] == "scheduled" for f in fx)
    assert "under way" in news.all_text()
    # rosters are locked for captains once it starts; the format is frozen
    assert "Rosters are locked" in await tour(w, teams["Lions"][0], ch, "team", "kick", mention(teams["Lions"][1]))
    assert "can't change once" in await tour(w, admin, ch, "format", "knockout")

    outsider = Player(w, "Outsider", strategy=tutil.strength_strategy)
    for n in (1, 2, 3):
        mch = w.channel("m")
        f = next(x for x in await fixtures(w, ch) if x["number"] == n)
        if n == 1:
            # create shows the "tournament match?" prompt; an outsider can't join a tournament lobby
            names = {x["team_id"]: x["name"] for x in await __import__("core.tournament.store", fromlist=["x"]).list_teams(w.db, t["tournament_id"])}
            host = teams[names[f["team_a_id"]]][0]
            await w.cmd("create", host, mch)
            assert "tournament match" in last(mch).lower()
            prompt = mch.messages[-1]
            await w.click(prompt, outsider, "Yes")            # not the host: ignored
            await w.cmd("tm", outsider, mch, "1")
            assert "Only the match host" in last(mch)
            await w.cmd("tm", host, mch, "1")
            assert "is now" in last(mch)
            await w.cmd("join", outsider, mch)
            assert "Only players on those two teams" in last(mch)
            await w.cmd("so", host, mch, 20)
            assert "tournament match" in last(mch)
            mi = w.bot.active_matches[mch.id]
            assert mi.match_settings["overs"] == 2 and mi.match_settings["days"] == 4
            # a second lobby can't claim the same fixture
            other_ch = w.channel("dup")
            other_host = teams[names[f["team_b_id"]]][0]
            await w.cmd("create", other_host, other_ch)
            await w.cmd("tm", other_host, other_ch, "1")
            assert "already has a lobby" in last(other_ch)
            del w.bot.active_matches[other_ch.id]
            del w.bot.active_matches[mch.id]
            mch = w.channel("m")
        mi, mch = await play_fixture(w, n, teams, channel=mch)
        assert mi.tournament and mi.tournament["number"] == n
        row = await w.db.fetchone("SELECT tournament_id, fixture_id FROM matches WHERE match_id = ?", [mi.match_id])
        assert row["tournament_id"] == t["tournament_id"] and row["fixture_id"]

    fx = await fixtures(w, ch)
    group = [f for f in fx if f["stage"] == "group"]
    assert all(f["status"] == "completed" and f["match_id"] for f in group)
    from core.tournament import store
    names = {x["team_id"]: x["name"] for x in await store.list_teams(w.db, t["tournament_id"])}
    for f in group:
        pair = {names[f["team_a_id"]], names[f["team_b_id"]]}
        if "Lions" in pair:
            assert names[f["winner_team_id"]] == "Lions" and f["result_type"] == "win" and f["summary"]["innings_win"]
        else:
            assert f["result_type"] == "draw" and f["winner_team_id"] is None
    t = await tournament(w, ch)
    table = t["cache"]["standings"][""]
    assert [r["name"] for r in table][0] == "Lions" and table[0]["points"] == 8 and table[0]["nrr"] > 0
    assert {r["points"] for r in table[1:]} == {2}
    assert "📋" in news.all_text() and "knockout stage is set" in news.all_text()
    # top two reach a final that was created automatically
    final = next(f for f in fx if f["stage"] == "final")
    assert names[final["team_a_id"]] == "Lions" and final["status"] == "scheduled"
    assert "Lions" in await tour(w, admin, ch, "table")
    await tour(w, admin, ch, "bracket")
    await tour(w, admin, ch, "fixtures", "done")
    await tour(w, admin, ch, "results")
    await tour(w, admin, ch, "stats", "wickets")
    await tour(w, admin, ch, "stats", "mvp")
    await tour(w, teams["Lions"][0], ch, "me")

    await play_fixture(w, final["number"], teams)
    t = await tournament(w, ch)
    assert t["status"] == "completed" and names[t["champion_team_id"]] == "Lions" and t["runner_up_team_id"]
    assert "is over" in news.all_text() and "Champions: **Lions**" in news.all_text()
    players = {r["name"]: r for r in t["cache"]["players"]}
    assert players["L1"]["matches"] == 3
    assert players["L1"]["runs"] + players["L2"]["runs"] > players["T1"]["runs"] + players["T2"]["runs"]
    assert t["cache"]["awards"]["top_runs"]["name"] in ("L1", "L2")
    assert t["cache"]["counts"] == {"teams": 3, "players": 6, "fixtures": 4, "played": 4}
    # the server is free for the next tournament; the old one is still readable
    assert "🥇" in await tour(w, admin, ch, "history")
    assert "created" in await tour(w, admin, ch, "create", "Next", "One")


@run
async def test_pools_then_knockout_with_draw_rule_and_manual_results():
    tutil.STRONG.clear()
    w, ch, admin = await world()
    spec = {n: [f"{n[0]}{i}" for i in (1, 2)] for n in ("Ants", "Bees", "Cats", "Dogs")}
    teams = await make_teams(w, ch, admin, spec, start=False,
                             settings={"format": "groups", "groups": 2, "qualifiers": 2, "knockout_draw_rule": "organiser"})
    assert "Pools drawn" in await tour(w, admin, ch, "draw", "seeded")
    assert "Pool A" in await tour(w, admin, ch, "team", "pool", "Ants", "A")
    await tour(w, admin, ch, "team", "pool", "Bees", "A")
    await tour(w, admin, ch, "team", "pool", "Cats", "B")
    await tour(w, admin, ch, "team", "pool", "Dogs", "B")
    assert "Choose a pool" in await tour(w, admin, ch, "team", "pool", "Dogs", "Z")
    assert "**2** pool matches" in await tour(w, admin, ch, "generate")
    assert "has started" in await tour(w, admin, ch, "start")
    fx = await fixtures(w, ch)
    assert [(f["group_name"], f["stage"]) for f in fx] == [("A", "group"), ("B", "group")]
    pleb = teams["Ants"][1]
    # manual results: only organisers, validated, and the knockout appears when the pools finish
    assert "Only tournament organisers" in await tour(w, pleb, ch, "result", "1", "Ants")
    assert "isn't playing" in await tour(w, admin, ch, "result", "1", "Cats")
    assert "no match #9" in await tour(w, admin, ch, "result", "9", "Ants")
    assert "Ants won" in await tour(w, admin, ch, "result", "1", "Ants")
    assert "walkover" in await tour(w, admin, ch, "walkover", "2", "Dogs")
    fx = await fixtures(w, ch)
    semis = [f for f in fx if f["stage"] == "sf"]
    final = next(f for f in fx if f["stage"] == "final")
    from core.tournament import store
    t = await tournament(w, ch)
    names = {x["team_id"]: x["name"] for x in await store.list_teams(w.db, t["tournament_id"])}
    assert {frozenset((names[f["team_a_id"]], names[f["team_b_id"]])) for f in semis} == {
        frozenset(("Ants", "Cats")), frozenset(("Dogs", "Bees"))}
    assert final["team_a_id"] is None and final["source_a"].startswith("W:")
    assert "doesn't have both teams" in await tour(w, admin, ch, "result", str(final["number"]), "Ants")
    # scheduling
    s1 = semis[0]["number"]
    assert "is set for" in await tour(w, admin, ch, "schedule", str(s1), "+2h")
    assert "couldn't read that time" in await tour(w, admin, ch, "schedule", str(s1), "soonish")
    assert "no set time" in await tour(w, admin, ch, "schedule", str(s1), "none")
    # a drawn semi-final (equal sides): organiser must decide
    mi, mch = await play_fixture(w, s1, teams)
    assert mi.result["type"] == "draw"
    f1 = next(f for f in await fixtures(w, ch) if f["number"] == s1)
    assert f1["status"] == "completed" and f1["winner_team_id"] is None and "organiser to decide" in f1["result_text"]
    winner = names[f1["team_a_id"]]
    assert "go through" in await tour(w, admin, ch, "result", str(s1), winner)
    f1 = next(f for f in await fixtures(w, ch) if f["number"] == s1)
    assert names[f1["winner_team_id"]] == winner and f1["match_id"] == mi.match_id       # scorecard kept
    final = next(f for f in await fixtures(w, ch) if f["stage"] == "final")
    assert winner in (names.get(final["team_a_id"]), names.get(final["team_b_id"]))
    # reset + replay the other semi, correct a result, then the final
    s2 = semis[1]["number"]
    assert "won" in await tour(w, admin, ch, "result", str(s2), "Dogs")
    assert "was reset" in await tour(w, admin, ch, "fixture", "reset", str(s2))
    final = next(f for f in await fixtures(w, ch) if f["stage"] == "final")
    assert "Dogs" not in (names.get(final["team_a_id"]), names.get(final["team_b_id"]))
    assert "Bees won" in await tour(w, admin, ch, "result", str(s2), "Bees")
    assert "Dogs won" in await tour(w, admin, ch, "result", str(s2), "Dogs")       # correction moves the bracket
    final = next(f for f in await fixtures(w, ch) if f["stage"] == "final")
    assert {names[final["team_a_id"]], names[final["team_b_id"]]} == {winner, "Dogs"}
    assert "Dogs won" in await tour(w, admin, ch, "result", str(final["number"]), "Dogs")
    t = await tournament(w, ch)
    assert t["status"] == "completed" and names[t["champion_team_id"]] == "Dogs" and names[t["runner_up_team_id"]] == winner
    # reopen → fix → finish by hand
    assert "open again" in await tour(w, admin, ch, "reopen")
    assert "has already been played" in await tour(w, admin, ch, "result", str(s2), "Bees")
    assert "is finished" in await tour(w, admin, ch, "end", "confirm")
    assert (await tournament(w, ch))["status"] == "completed"


@run
async def test_knockout_first_innings_rule_byes_extra_fixtures_and_withdrawals():
    tutil.STRONG.clear()
    w, ch, admin = await world()
    spec = {n: [f"{n[0]}{i}" for i in (1, 2)] for n in ("Ants", "Bees", "Cats")}
    teams = await make_teams(w, ch, admin, spec, start=False, settings={"format": "knockout"})
    assert "seed 1" in await tour(w, admin, ch, "team", "seed", "Cats", "1")
    assert "has started" in await tour(w, admin, ch, "start")
    fx = await fixtures(w, ch)
    from core.tournament import store
    t = await tournament(w, ch)
    names = {x["team_id"]: x["name"] for x in await store.list_teams(w.db, t["tournament_id"])}
    assert [f["stage"] for f in fx] == ["sf", "final"]
    assert {names[fx[0]["team_a_id"]], names[fx[0]["team_b_id"]]} == {"Ants", "Bees"}
    assert names[fx[1]["team_a_id"]] == "Cats"                      # the top seed has a bye to the final
    assert "no points table" in await tour(w, admin, ch, "table")
    # extra fixtures don't touch the bracket
    assert "Added match `#3`" in await tour(w, admin, ch, "fixture", "add", "Ants", "v", "Cats", "extra")
    assert "can't play itself" in await tour(w, admin, ch, "fixture", "add", "Ants", "v", "Ants")
    assert "was removed" in await tour(w, admin, ch, "fixture", "remove", "3")
    assert "Bracket matches can't be removed" in await tour(w, admin, ch, "fixture", "remove", "1")
    # semi-final: the first-innings leader goes through when the match is drawn
    a_name = names[fx[0]["team_a_id"]]
    tutil.FIRST_INNINGS_BOOST.update({f"{a_name[0]}1", f"{a_name[0]}2"})    # first-innings lead, then a drawn match
    try:
        mi, _ = await play_fixture(w, 1, teams)
    finally:
        tutil.FIRST_INNINGS_BOOST.clear()
    f1 = (await fixtures(w, ch))[0]
    assert mi.result["type"] == "draw"
    assert f1["summary"]["decided_by"] == "first_innings" and "first-innings lead" in f1["result_text"]
    assert f1["result_type"] == "draw" and names[f1["winner_team_id"]] == a_name
    final = (await fixtures(w, ch))[1]
    assert {names[final["team_a_id"]], names[final["team_b_id"]]} == {"Cats", a_name}
    # the other finalist withdraws: walkover, champion crowned
    assert "withdrew" in await tour(w, admin, ch, "team", "withdraw", "Cats")
    t = await tournament(w, ch)
    assert t["status"] == "completed" and names[t["champion_team_id"]] == a_name


@run
async def test_abandoned_and_unmarked_matches_release_the_fixture():
    tutil.STRONG.clear()
    w, ch, admin = await world()
    teams = await make_teams(w, ch, admin, {"Ants": ["A1", "A2"], "Bees": ["B1", "B2"]}, settings={"qualifiers": 0})
    host = teams["Ants"][0]
    mch = w.channel("m")
    await w.cmd("create", host, mch)
    prompt = mch.messages[-1]
    await w.click(prompt, host, "Yes")                               # one playable fixture → marked straight away
    mi = w.bot.active_matches[mch.id]
    assert mi.tournament and "is now" in prompt.text()
    await w.cmd("tm", host, mch, "off")
    assert mi.tournament is None and "friendly" in last(mch)
    await w.cmd("tm", host, mch)                                     # no number: the captain's only fixture
    assert mi.tournament["number"] == 1
    # can't start with too few players when the tournament demands more
    await tour(w, admin, ch, "set", "min_players", "2")
    for p in (teams["Bees"][0],):
        await w.cmd("join", p, mch)
    mi.toss_winner, mi.batting_turn, mi.bowling_turn, mi.toss_decision = mi.teamA_captain, "A", "B", "bat"
    await w.cmd("start", host, mch)
    assert "needs at least 2" in last(mch) and not mi.game_started
    for p in (teams["Ants"][1], teams["Bees"][1]):
        await w.cmd("join", p, mch)
    await w.cmd("start", host, mch)
    assert mi.game_started
    fx = (await fixtures(w, ch))[0]
    assert fx["status"] == "live" and fx["match_id"] == mi.match_id
    assert "being played right now" in await tour(w, admin, ch, "result", "1", "Ants")
    # abandon → the fixture can be played again
    await w.cmd("yeet", host, mch)
    await w.click(mch.messages[-1], host, "Yes")
    await asyncio.wait_for(mi.task, 20)
    fx = (await fixtures(w, ch))[0]
    assert fx["status"] == "scheduled" and fx["match_id"] is None
    # replay it; qualifiers = 0 so the table decides and the tournament closes itself
    tutil.STRONG.update({"B1", "B2"})
    mi2, _ = await play_fixture(w, 1, teams)
    t = await tournament(w, ch)
    from core.tournament import store
    names = {x["team_id"]: x["name"] for x in await store.list_teams(w.db, t["tournament_id"])}
    assert t["status"] == "completed" and names[t["champion_team_id"]] == "Bees"


@run
async def test_prizes_cancel_delete_and_restart_persistence():
    tutil.STRONG.clear()
    tutil.STRONG.update({"A1", "A2"})
    w, ch, admin = await world()
    w.bot.owner_ids.add(admin.member.id)
    teams = await make_teams(w, ch, admin, {"Ants": ["A1", "A2"], "Bees": ["B1", "B2"]}, start=False,
                             settings={"qualifiers": 0, "prize_champion": 1000, "prize_runner_up": 300,
                                       "prize_mvp": 50, "prize_participation": 10})
    await tour(w, admin, ch, "start")
    # a tournament lobby survives a restart with its link
    host = teams["Ants"][0]
    mch = w.channel("m")
    await w.cmd("create", host, mch)
    await w.cmd("tm", host, mch, "1")
    mi = w.bot.active_matches[mch.id]
    await w.bot.store.flush(mi)
    from core.backend.instance import MatchInstance
    state = (await w.bot.store.load_all())[0]
    again = await MatchInstance.from_state(w.bot, mch, state)
    assert again.tournament["number"] == 1 and again.tournament["rosters"]["A"]
    del w.bot.active_matches[mch.id]
    await w.bot.store.delete_state(mi)
    mi, _ = await play_fixture(w, 1, teams)
    t = await tournament(w, ch)
    assert t["status"] == "completed" and t["cache"]["prizes_paid"]
    start = 500
    coins = {r["name"]: r["coins"] for r in await w.db.fetch("SELECT name, coins FROM profiles")}
    paid = {r["userid"]: r["amount"] for r in await w.db.fetch(
        "SELECT userid, SUM(amount) AS amount FROM transactions WHERE reason LIKE 'tournament % prize' GROUP BY userid")}
    by_name = {p.member.name: paid.get(str(p.member.id), 0) for ps in teams.values() for p in ps}
    assert by_name["B1"] == 310 and by_name["B2"] == 310
    assert sorted((by_name["A1"], by_name["A2"])) == [1010, 1060]            # one of the champions is the MVP
    assert coins["A1"] > start
    # cancel / delete need confirmation
    await tour(w, admin, ch, "create", "Second")
    task = asyncio.ensure_future(w.cmd("tour", admin, ch, "cancel"))
    await asyncio.sleep(0.02)
    await w.click(ch.messages[-1], admin, "Cancel")
    await task
    assert (await tournament(w, ch))["status"] == "setup"
    task = asyncio.ensure_future(w.cmd("tour", admin, ch, "cancel"))
    await asyncio.sleep(0.02)
    await w.click(ch.messages[-1], admin, "Yes")
    await task
    assert (await tournament(w, ch))["status"] == "cancelled"
    assert "was deleted" in await tour(w, admin, ch, "delete", "confirm")
    left = await w.db.fetch("SELECT name FROM tournaments")
    assert [r["name"] for r in left] == ["BSW Cup"]
