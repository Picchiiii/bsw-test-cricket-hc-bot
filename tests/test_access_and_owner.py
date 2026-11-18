"""Server whitelist, owner economy control and the website → bot task queue."""
import json
import time

import discord

from core.config import config
from harness import Player, World
from tutil import last, make_teams, mention, tour, tournament, world
from util import run


def whitelist(on: bool):
    config.access["whitelist_enabled"] = on


@run
async def test_whitelist_blocks_unlisted_servers():
    whitelist(True)
    try:
        w = World()
        await w.setup()
        ch = w.channel()
        owner, user = Player(w, "Owner"), Player(w, "User")
        w.bot.owner_ids.add(owner.member.id)
        # not listed: commands don't run, the server is told who to ask (once, not on every command)
        await w.cmd("create", user, ch)
        assert "not authorised" in last(ch) and f"<@{owner.member.id}>" in last(ch) and str(ch.guild.id) in last(ch)
        assert ch.id not in w.bot.active_matches
        n = len(ch.messages)
        await w.cmd("profile", user, ch)
        await w.cmd("daily", user, ch)
        assert len(ch.messages) == n                                  # anti-spam: no second notice
        assert await w.db.fetch("SELECT * FROM profiles") == []
        await w.cmd("ping", user, ch)
        assert "Pong" in last(ch)                                     # ping always answers
        # the owner is never blocked, and can allow the server from inside it
        await w.cmd("server", user, ch, "allow")
        assert "Only the bot owner" in last(ch)
        await w.cmd("server", owner, ch, "allow")
        assert "can now use the bot with no time limit" in last(ch)
        await w.cmd("create", user, ch)
        assert ch.id in w.bot.active_matches
        # revoke by ID from anywhere
        await w.cmd("server", owner, ch, "revoke", str(ch.guild.id), "unpaid")
        assert "can no longer use the bot" in last(ch)
        w.bot.access._told.clear()
        await w.cmd("join", Player(w, "Late"), ch)
        assert "turned off" in last(ch)
        # timed access, expiry and extension
        await w.cmd("server", owner, ch, "allow", str(ch.guild.id), "30", "monthly", "plan")
        row = w.bot.access.row(ch.guild.id)
        assert row["note"] == "monthly plan" and 29 * 86400 < row["expires_at"] - time.time() <= 30 * 86400
        assert w.bot.access.is_allowed(ch.guild.id)
        await w.db.execute("UPDATE guild_access SET expires_at = ? WHERE guild_id = ?", [int(time.time()) - 5, str(ch.guild.id)])
        await w.bot.access.load()
        assert not w.bot.access.is_allowed(ch.guild.id) and w.bot.access.state(ch.guild.id) == "expired"
        w.bot.access._told.clear()
        await w.cmd("profile", user, ch)
        assert "expired" in last(ch)
        await w.cmd("server", owner, ch, "extend", str(ch.guild.id), "7")
        assert w.bot.access.is_allowed(ch.guild.id)
        await w.cmd("server", owner, ch, "list")
        assert "🟢" in last(ch) and ch.guild.name in last(ch)
        await w.cmd("server", owner, ch, "info")
        assert "monthly plan" in last(ch)
        # DMs: allowed for members of an allowed server, refused otherwise
        dm = user.member.dm_channel
        await w.cmd("balance", user, dm)
        assert "wallet" in last(dm)
        stranger = discord.User("Stranger")
        await w.bot.invoke_command("balance", w.ctx(stranger, stranger.dm_channel))
        assert "not authorised" in last(stranger.dm_channel)
        # forget, and the global switch
        await w.cmd("server", owner, ch, "forget", str(ch.guild.id))
        assert not w.bot.access.is_allowed(ch.guild.id)
        await w.cmd("server", owner, ch, "whitelist", "off")
        assert "every server" in last(ch)
        await w.cmd("profile", user, ch)
        assert "Profile" in last(ch)
        await w.cmd("server", owner, ch, "whitelist", "on")
        assert config.access["whitelist_enabled"] is True
        await w.cmd("owner", owner, ch)
        assert "Owner tools" in last(ch)
    finally:
        whitelist(False)


@run
async def test_owner_is_told_when_bot_joins_an_unlisted_server():
    whitelist(True)
    try:
        w = World()
        await w.setup()
        owner = Player(w, "Owner")
        w.bot.owner_ids.add(owner.member.id)
        new = discord.Guild("Newcomers")
        new.system_channel = discord.TextChannel(new, "general", bot_user=w.bot.user)
        w.bot.guilds.append(new)
        await w.bot.fire("on_guild_join", new)
        assert str(new.id) in owner.member.dm_channel.all_text() and "server allow" in owner.member.dm_channel.all_text()
        assert "not authorised" in new.system_channel.all_text() and not new.left
        config.access["leave_unlisted"] = True
        await w.bot.fire("on_guild_join", new)
        assert new.left
        # an allowed server gets no notice
        ok = discord.Guild("Paid")
        ok.system_channel = discord.TextChannel(ok, "general", bot_user=w.bot.user)
        await w.bot.access.allow(ok.id, "Paid")
        await w.bot.fire("on_guild_join", ok)
        assert ok.system_channel.messages == [] and not ok.left
    finally:
        config.access["leave_unlisted"] = False
        whitelist(False)


@run
async def test_owner_controls_the_economy():
    w = World()
    await w.setup()
    ch = w.channel()
    owner, user, other = Player(w, "Owner"), Player(w, "User"), Player(w, "Other")
    w.bot.owner_ids.add(owner.member.id)

    async def coins(p):
        return (await w.db.fetchone("SELECT coins FROM profiles WHERE userid = ?", [str(p.member.id)]))["coins"]

    await w.cmd("eco", user, ch, "add", mention(user), "1000")
    assert "Only the bot owner" in last(ch)
    await w.cmd("eco", owner, ch, "add", mention(user), "1,000", "tournament", "prize")
    assert "tournament prize" in last(ch) and await coins(user) == 1500
    await w.cmd("eco", owner, ch, "remove", mention(user), "200")
    assert await coins(user) == 1300
    await w.cmd("eco", owner, ch, "remove", mention(user), "999999")
    assert await coins(user) == 0                                        # never negative
    await w.cmd("eco", owner, ch, "set", mention(user), "42")
    assert await coins(user) == 42
    await w.cmd("eco", owner, ch, "set", mention(user), "-5")
    assert "between 0" in last(ch)
    await w.cmd("eco", owner, ch, "add", mention(user), "lots")
    assert "whole number" in last(ch)
    await w.cmd("eco", owner, ch, "reset", mention(user))
    assert await coins(user) == 500
    await w.cmd("eco", owner, ch, "view", mention(user))
    assert "owner set" in last(ch) and "owner reset" in last(ch)
    tx = await w.db.fetch("SELECT amount FROM transactions WHERE userid = ? ORDER BY id", [str(user.member.id)])
    assert sum(t["amount"] for t in tx) == 500                           # the ledger always matches the balance
    # pay everyone with a role
    role = discord.Role(ch.guild, "Winners")
    user.member.roles.append(role)
    other.member.roles.append(role)
    await w.cmd("eco", owner, ch, "role", role.mention, "250")
    assert "**2** member(s)" in last(ch) and await coins(user) == 750 and await coins(other) == 750
    # live settings and switches
    try:
        await w.cmd("eco", owner, ch, "config")
        assert "daily_enabled" in last(ch)
        await w.cmd("eco", owner, ch, "config", "daily", "999")
        assert config.economy["daily"] == 999
        await w.cmd("daily", user, ch)
        assert await coins(user) == 750 + 999
        await w.cmd("eco", owner, ch, "config", "weekly_enabled", "off")
        await w.cmd("weekly", user, ch)
        assert "switched off" in last(ch)
        await w.cmd("eco", owner, ch, "config", "give_enabled", "off")
        await w.cmd("give", user, ch, other.member, 10)
        assert "switched off" in last(ch)
        await w.cmd("eco", owner, ch, "config", "shop_enabled", "off")
        await w.cmd("buy", user, ch, item_name="rookie")
        assert "closed" in last(ch)
        await w.cmd("eco", owner, ch, "config", "daily", "-1")
        assert "between" in last(ch)
        await w.cmd("eco", owner, ch, "config", "nope", "1")
        assert "Unknown economy setting" in last(ch)
        # saved in the database: a restart keeps them
        config.economy["daily"] = 250
        from core.economy import settings as eco_settings
        await eco_settings.load(w.db)
        assert config.economy["daily"] == 999 and config.economy["weekly_enabled"] is False
        await w.cmd("eco", owner, ch, "config", "reset", "daily")
        assert config.economy["daily"] == 250
        await w.cmd("eco", owner, ch, "stats")
        assert "circulation" in last(ch)
    finally:
        for key in ("daily_enabled", "weekly_enabled", "give_enabled", "shop_enabled", "match_rewards_enabled"):
            config.economy[key] = True
        config.economy["daily"] = 250


async def queue(w, kind, actor, payload, tournament_id=None, guild_id=None):
    res = await w.db.execute(
        "INSERT INTO web_tasks (kind, guild_id, tournament_id, actor_id, actor_name, payload, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        [kind, str(guild_id) if guild_id else None, tournament_id, str(actor.member.id), actor.member.name,
         json.dumps(payload), int(time.time())])
    await w.bot.tournaments.process_web_tasks()
    row = await w.db.fetchone("SELECT status, result FROM web_tasks WHERE id = ?", [res["last_id"]])
    return row["status"], row["result"]


@run
async def test_website_requests_run_through_the_bot_with_permission_checks():
    w, ch, admin = await world()
    pleb = Player(w, "Pleb")
    # create from the website: needs Manage Server, like the command
    assert (await queue(w, "tournament.create", pleb, {"name": "Web Cup"}, guild_id=ch.guild.id))[0] == "error"
    status, result = await queue(w, "tournament.create", admin, {"name": "Web Cup"}, guild_id=ch.guild.id)
    assert status == "done" and result.startswith("Created Web Cup|")
    t = await tournament(w, ch)
    tid = t["tournament_id"]
    assert result.endswith(tid)
    # organiser action
    status, result = await queue(w, "tournament", admin, {"action": "settings.set", "params": {"key": "overs", "value": 15}}, tid)
    assert status == "done" and "15" in result and "*" not in result
    assert (await tournament(w, ch))["settings"]["overs"] == 15
    # the bot re-checks permission even if the website let the request through
    status, result = await queue(w, "tournament", pleb, {"action": "settings.set", "params": {"key": "overs", "value": 5}}, tid)
    assert status == "error" and "organisers" in result
    # trusted flags can't be smuggled in from the browser
    status, result = await queue(w, "tournament", pleb, {"action": "host.transfer",
                                                         "params": {"user_id": str(pleb.member.id), "_manage_guild": True}}, tid)
    assert status == "error"
    # players can act for themselves from the website; names always come from Discord, not the request
    await queue(w, "tournament", admin, {"action": "registration.open"}, tid)
    status, result = await queue(w, "tournament", pleb, {"action": "register"}, tid)
    assert status == "done"
    status, _ = await queue(w, "tournament", admin, {"action": "team.create", "params": {
        "name": "Webbers", "user_id": str(pleb.member.id), "user_name": "Hacked Name"}}, tid)
    assert status == "done"
    from core.tournament import store
    assert (await store.get_player(w.db, tid, pleb.member.id))["name"] == "Pleb"
    # validation errors and unknown things come back as readable errors
    assert (await queue(w, "tournament", admin, {"action": "nope"}, tid))[0] == "error"
    assert (await queue(w, "tournament", admin, {"action": "start"}, tid))[1].startswith("You need at least 2 teams")
    assert (await queue(w, "tournament", admin, {"action": "settings.set"}, "missing"))[0] == "error"
    outsider = discord.User("Outsider")
    w.bot.users[outsider.id] = outsider
    res = await w.db.execute(
        "INSERT INTO web_tasks (kind, tournament_id, actor_id, actor_name, payload, status, created_at) "
        "VALUES ('tournament', ?, ?, 'Outsider', ?, 'pending', ?)",
        [tid, str(outsider.id), json.dumps({"action": "register"}), int(time.time())])
    await w.bot.tournaments.process_web_tasks()
    row = await w.db.fetchone("SELECT status, result FROM web_tasks WHERE id = ?", [res["last_id"]])
    assert row["status"] == "error" and "not a member" in row["result"]
    # old requests are not run after the bot has been away
    await w.db.execute("INSERT INTO web_tasks (kind, tournament_id, actor_id, actor_name, payload, status, created_at) "
                       "VALUES ('tournament', ?, ?, 'Admin', ?, 'pending', ?)",
                       [tid, str(admin.member.id), json.dumps({"action": "cancel"}), int(time.time()) - 3600])
    await w.bot.tournaments.process_web_tasks()
    assert (await tournament(w, ch))["status"] == "registration"
    assert "expired" in (await w.db.fetchone("SELECT result FROM web_tasks ORDER BY id DESC LIMIT 1"))["result"]
    # owner panel: only the bot owner
    assert (await queue(w, "owner.coins", admin, {"op": "add", "user_id": str(pleb.member.id), "amount": 100}))[0] == "error"
    w.bot.owner_ids.add(admin.member.id)
    status, result = await queue(w, "owner.coins", admin, {"op": "set", "user_id": str(pleb.member.id), "amount": 777})
    assert status == "done" and "777" in result
    assert (await w.db.fetchone("SELECT coins FROM profiles WHERE userid = ?", [str(pleb.member.id)]))["coins"] == 777
    status, _ = await queue(w, "owner.server", admin, {"op": "allow", "guild_id": "123456789012345678", "days": 30})
    assert status == "done" and w.bot.access.row("123456789012345678")["status"] == "allowed"
    assert (await queue(w, "owner.server", admin, {"op": "revoke", "guild_id": "123456789012345678"}))[0] == "done"
    assert w.bot.access.state("123456789012345678") == "blocked"
    try:
        assert (await queue(w, "owner.eco", admin, {"key": "weekly", "value": 5}))[0] == "done"
        assert config.economy["weekly"] == 5
        assert (await queue(w, "owner.eco", admin, {"key": "weekly", "value": "x"}))[0] == "error"
    finally:
        config.economy["weekly"] = 1500
    # audit rows remember where a change came from
    sources = {r["source"] for r in await w.db.fetch("SELECT source FROM tournament_audit WHERE tournament_id = ?", [tid])}
    assert "web" in sources


@run
async def test_housekeeping_reminders_schema_and_server_info_for_the_website():
    w, ch, admin = await world()
    news = w.channel("news")
    role = discord.Role(ch.guild, "Umpires")
    helper = Player(w, "Helper")
    helper.member.roles.append(role)
    teams = await make_teams(w, ch, admin, {"Ants": ["A1"], "Bees": ["B1"]}, start=False)
    await tour(w, admin, ch, "channel", "announce", news.mention)
    await tour(w, admin, ch, "role", "organizer", role.mention)
    await tour(w, admin, ch, "start")
    assert "is set for" in await tour(w, admin, ch, "schedule", "1", "+10m")
    await w.bot.tournaments.housekeeping()
    assert "starts" in news.all_text() and f"<@{teams['Ants'][0].member.id}>" in (news.messages[-1].content or "")
    n = len(news.messages)
    await w.bot.tournaments.housekeeping()
    assert len(news.messages) == n                                         # reminded once
    meta = await w.db.fetchone("SELECT * FROM guild_meta WHERE guild_id = ?", [str(ch.guild.id)])
    assert "Umpires" in meta["roles"] and "news" in meta["channels"]
    t = await tournament(w, ch)
    staff = await w.db.fetch("SELECT user_id, source FROM tournament_staff WHERE tournament_id = ?", [t["tournament_id"]])
    assert (str(helper.member.id), "role") in {(s["user_id"], s["source"]) for s in staff}
    info = json.loads((await w.db.fetchone("SELECT value FROM bot_settings WHERE key = 'tournament.schema'"))["value"])
    assert info["prefix"] == "+" and any(s["key"] == "overs" for s in info["schema"]["settings"])
    assert int((await w.db.fetchone("SELECT value FROM bot_settings WHERE key = 'bot.heartbeat'"))["value"]) > 0
