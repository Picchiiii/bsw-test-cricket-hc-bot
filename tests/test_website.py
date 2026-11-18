import os
import random
import shutil
import subprocess

import pytest

from fake_hrana import HranaServer
from harness import World, make_players, random_strategy
from util import run
from core.backend.turso.db import TursoDB

WEBSITE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "website")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@run
async def test_website_api_against_turso():
    random.seed(4)
    srv = HranaServer().start()
    try:
        w = World(db=TursoDB(url=srv.url, token="secret-token"))
        await w.setup()
        ch = w.channel()
        a = make_players(w, ["Ravi", "Sam", "Tom"], strategy=random_strategy)
        b = make_players(w, ["Uday", "Vik", "Wil"], strategy=random_strategy)
        mi = await w.setup_match(ch, a, b, overs=10, days=4)
        await w.finish(mi, timeout=90)
        env = dict(os.environ, TURSO_DATABASE_URL=srv.url, TURSO_AUTH_TOKEN="secret-token")
        out = subprocess.run(["node", "test/api_check.js"], cwd=WEBSITE, env=env, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stdout + out.stderr
        assert "website api ok" in out.stdout
    finally:
        srv.stop()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@run
async def test_website_tournaments_login_and_manage_with_the_bot_running():
    """Bot + website on one Turso database: public pages, Discord login, organiser changes via the bot."""
    import asyncio

    import discord

    import tutil
    from harness import Player

    random.seed(5)
    tutil.STRONG.clear()
    tutil.STRONG.update({"L1", "L2"})
    srv = HranaServer().start()
    try:
        w = World(db=TursoDB(url=srv.url, token="secret-token"))
        await w.setup()
        ch = w.channel("lobby")
        admin = Player(w, "Admin", strategy=tutil.strength_strategy)
        admin.member.guild_permissions.manage_guild = True
        outsider = discord.User("Outsider")
        w.bot.users[outsider.id] = outsider
        discord.Role(ch.guild, "Umpires")
        teams = await tutil.make_teams(w, ch, admin, {"Lions": ["L1", "L2"], "Tigers": ["T1", "T2"], "Bears": ["B1", "B2"]})
        fx = (await tutil.fixtures(w, ch))
        names = {r["team_id"]: r["name"] for r in await w.db.fetch("SELECT team_id, name FROM tournament_teams")}
        lions = next(f["number"] for f in fx if "Lions" in (names[f["team_a_id"]], names[f["team_b_id"]]))
        await tutil.play_fixture(w, lions, teams)
        await w.bot.tournaments.housekeeping()          # heartbeat, server list, roles/channels for the site

        env = dict(os.environ, TURSO_DATABASE_URL=srv.url, TURSO_AUTH_TOKEN="secret-token", DISCORD_CLIENT_ID="cid",
                   DISCORD_CLIENT_SECRET="secret", TEST_USER=str(admin.member.id), TEST_GUILD=str(ch.guild.id),
                   TEST_OUTSIDER=str(outsider.id))
        env.pop("OWNER_IDS", None)
        env.pop("SITE_URL", None)
        w.bot.owner_ids.add(admin.member.id)
        proc = await asyncio.create_subprocess_exec("node", "test/tournament_check.js", cwd=WEBSITE, env=env,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        reader = asyncio.ensure_future(proc.communicate())
        while not reader.done():                        # the bot's website loop
            await w.bot.tournaments.process_web_tasks()
            await asyncio.sleep(0.03)
        out = (await reader)[0].decode()
        assert proc.returncode == 0, out
        assert "website tournaments ok" in out
        t = await tutil.tournament(w, ch)
        assert t["description"] == "Set from the website" and t["status"] == "ongoing"
        assert w.bot.access.row(ch.guild.id)["note"] == "paid"
    finally:
        srv.stop()
