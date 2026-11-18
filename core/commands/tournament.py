"""Tournament commands: `tour` (short for `tournament`; `t` is already the toss) and `tm` (mark a lobby
as a tournament match).

`tour <subcommand> …` — see `tour help` or docs/TOURNAMENTS.md. Every change goes through
TournamentManager.run(), the same path the website uses.
"""
import discord
from discord.ext import commands

from core.backend.resolve import find_member
from core.config import config
from core.tournament import logic, render, schema, store
from core.tournament.actions import TournamentError
from core.tournament.views import ConfirmView, FixturePickView, InviteView
from core.ui import theme
from core.ui.paginator import send_pages

P = config.prefix
NO_PING = discord.AllowedMentions.none()


def _is_mention(text) -> bool:
    return str(text).startswith("<@") or (str(text).isdigit() and len(str(text)) >= 15)


def _split_users(args) -> tuple[list, list]:
    """(mention/ID tokens, everything else)."""
    users = [a for a in args if _is_mention(a)]
    rest = [a for a in args if not _is_mention(a)]
    return users, rest


def tournament(bot: commands.Bot):
    mgr = bot.tournaments
    db = bot.db

    async def say(ctx, text: str, **kw):
        return await ctx.send(theme.truncate(text, 1900), allowed_mentions=NO_PING, **kw)

    async def current(ctx, active: bool = True):
        """The server's tournament. active=True: the running one only; False: fall back to the last finished one."""
        t = await (store.active_for_guild(db, ctx.guild.id) if active else store.latest_for_guild(db, ctx.guild.id))
        if t is None:
            await say(ctx, f"There is no tournament {'running ' if active else ''}in this server. "
                           f"Someone with **Manage Server** can start one with `{P}tour create <name>`.")
        return t

    async def do(ctx, t, action: str, params: dict | None = None):
        try:
            result = await mgr.run(ctx.guild, t, ctx.author, action, params or {})
        except TournamentError as e:
            await say(ctx, f"{theme.CROSS} {e}")
            return None
        await say(ctx, result.message)
        return result

    async def member_arg(ctx, text):
        m = await find_member(ctx.guild, text)
        if m is None:
            await say(ctx, "I couldn't find that member. Mention them or use their ID.")
        return m

    async def confirm(ctx, args, question: str) -> bool:
        if any(str(a).lower() in ("confirm", "yes", "-y") for a in args):
            return True
        view = ConfirmView(ctx.author.id)
        view.message = await ctx.send(f"⚠️ {question}\n-# Add `confirm` to the command to skip this question.", view=view)
        await view.wait()
        if view.value:
            try:
                await view.message.edit(content="Confirmed.", view=None)
            except Exception:
                pass
            return True
        if view.value is False:
            try:
                await view.message.edit(content="Cancelled — nothing was changed.", view=None)
            except Exception:
                pass
        return False

    async def names_of(t) -> tuple[list, dict]:
        teams = await store.list_teams(db, t["tournament_id"])
        return teams, {x["team_id"]: x["name"] for x in teams}

    # ───────────────────────────────────────────────────────── read-only
    async def c_overview(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        tid = t["tournament_id"]
        e = render.overview(t, await store.list_teams(db, tid), await store.list_players(db, tid),
                            await store.list_fixtures(db, tid))
        await ctx.send(embed=e)

    async def c_help(ctx, args):
        await send_pages(ctx, render.help_pages())

    async def c_rules(ctx, args):
        t = await current(ctx, active=False)
        if t is not None:
            await ctx.send(embed=render.rules_embed(t))

    async def c_teams(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        teams = await store.list_teams(db, t["tournament_id"])
        if not teams:
            await say(ctx, f"No teams yet. Create one with `{P}tour team create <name>`.")
            return
        await send_pages(ctx, render.teams_pages(t, teams, await store.list_players(db, t["tournament_id"])))

    async def show_team(ctx, t, ref):
        teams, names = await names_of(t)
        team = store.match_team(teams, ref)
        if team is None:
            await say(ctx, f"I couldn't find a team called **{ref}**. See `{P}tour teams`.")
            return
        tid = t["tournament_id"]
        stats = {r["userid"]: r for r in (t.get("cache") or {}).get("players") or []}
        await ctx.send(embed=render.team_embed(t, team, await store.roster(db, tid, team["team_id"]),
                                               await store.list_fixtures(db, tid), names, stats),
                       allowed_mentions=NO_PING)

    async def c_players(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        players = await store.list_players(db, t["tournament_id"])
        free = [pl for pl in players if not pl["team_id"] and pl["status"] == "active"]
        banned = [pl for pl in players if pl["status"] == "banned"]
        in_team = len([pl for pl in players if pl["team_id"] and pl["status"] == "active"])
        e = theme.embed(f"👥 {t['name']} — players", f"**{in_team}** in teams • **{len(free)}** free agents", theme.BLUE)
        e.add_field(name="Free agents", value=theme.truncate(", ".join(pl["name"] for pl in free) or "none"), inline=False)
        if banned:
            e.add_field(name="Banned", value=theme.truncate(", ".join(pl["name"] for pl in banned)), inline=False)
        await ctx.send(embed=e)

    async def c_fixtures(ctx, args, only_results: bool = False):
        t = await current(ctx, active=False)
        if t is None:
            return
        fixtures = await store.list_fixtures(db, t["tournament_id"])
        teams, names = await names_of(t)
        title = "Fixtures"
        flt = " ".join(args).strip()
        if only_results:
            fixtures = [f for f in fixtures if f["status"] in logic.DONE]
            title = "Results"
        if flt:
            low = flt.lower()
            team = store.match_team(teams, flt)
            if low in ("live", "now"):
                fixtures, title = [f for f in fixtures if f["status"] == "live"], "Live"
            elif low in ("todo", "upcoming", "next", "open"):
                fixtures, title = [f for f in fixtures if f["status"] == "scheduled"], "To be played"
            elif low in ("done", "played", "results"):
                fixtures, title = [f for f in fixtures if f["status"] in logic.DONE], "Results"
            elif low in ("ko", "knockout", "bracket", "playoffs"):
                fixtures, title = [f for f in fixtures if f["stage"] not in ("group", "extra")], "Knockout"
            elif team is not None:
                fixtures = [f for f in fixtures if team["team_id"] in (f["team_a_id"], f["team_b_id"])]
                title = f"{team['name']}"
            elif len(flt) == 1 and flt.upper() in schema.GROUP_LETTERS:
                fixtures, title = [f for f in fixtures if f["group_name"] == flt.upper()], f"Pool {flt.upper()}"
            else:
                await say(ctx, "Filter by a team, a pool letter, or `live`, `todo`, `done`, `knockout`.")
                return
        if not fixtures:
            await say(ctx, "Nothing to show." if flt or only_results else
                      f"The fixture list hasn't been drawn yet. It is built on `{P}tour start` (preview with `{P}tour generate`).")
            return
        await send_pages(ctx, render.fixtures_pages(t, fixtures, names, title))

    async def c_results(ctx, args):
        await c_fixtures(ctx, args, only_results=True)

    async def c_table(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        if t["settings"]["format"] == "knockout":
            await say(ctx, f"A knockout has no points table — see `{P}tour bracket`.")
            return
        tables, _, _ = await mgr.tables(t)
        only = args[0] if args else None
        await ctx.send(embed=render.table_embed(t, tables, only))

    async def c_bracket(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        _, names = await names_of(t)
        await ctx.send(embed=render.bracket_embed(t, await store.list_fixtures(db, t["tournament_id"]), names))

    async def c_stats(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        cat = (args[0].lower() if args else "runs")
        cat = logic.LEADER_ALIASES.get(cat, cat)
        if cat not in logic.LEADERBOARDS:
            await say(ctx, f"Pick one of: {', '.join(f'`{k}`' for k in logic.LEADERBOARDS)}")
            return
        _, names = await names_of(t)
        await send_pages(ctx, render.leaders_pages(t, await mgr.player_table(t), cat, names))

    async def c_player(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        user = ctx.author
        if args:
            user = await member_arg(ctx, args[0])
            if user is None:
                return
        pl = await store.get_player(db, t["tournament_id"], user.id)
        if pl is None:
            await say(ctx, f"**{user.name}** isn't registered for **{t['name']}**.")
            return
        _, names = await names_of(t)
        row = next((r for r in await mgr.player_table(t) if r["userid"] == str(user.id)), None)
        await ctx.send(embed=render.player_embed(t, row, user.name, names.get(pl["team_id"]), pl["status"]))

    async def c_me(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        tid = t["tournament_id"]
        pl = await store.get_player(db, tid, ctx.author.id)
        if pl is None:
            await say(ctx, f"You're not registered for **{t['name']}**."
                      + (f" Sign up with `{P}tour register`." if t["status"] == "registration" else ""))
            return
        teams, names = await names_of(t)
        team = next((x for x in teams if x["team_id"] == pl["team_id"]), None)
        e = theme.embed(f"👤 {ctx.author.name} — {t['name']}", color=theme.BLUE)
        if team is None:
            invites = await store.list_invites(db, tid, user_id=ctx.author.id)
            e.description = "You're a **free agent**."
            if invites:
                e.add_field(name="Invites", value="\n".join(f"**{names.get(i['team_id'], '?')}** — `{P}tour accept "
                                                           f"{next((x['tag'] for x in teams if x['team_id'] == i['team_id']), '')}`"
                                                           for i in invites), inline=False)
        else:
            role = "captain" if team["captain_id"] == str(ctx.author.id) else \
                "vice-captain" if team["vice_captain_id"] == str(ctx.author.id) else "player"
            e.description = f"Team **{team['name']}** [{team['tag']}] — {role}"
            fixtures = await store.list_fixtures(db, tid)
            mine = [f for f in fixtures if team["team_id"] in (f["team_a_id"], f["team_b_id"])]
            todo = [f for f in mine if f["status"] in ("scheduled", "live")][:4]
            if todo:
                e.add_field(name="Your next matches", value=theme.truncate("\n".join(render.fixture_line(f, names) for f in todo)),
                            inline=False)
        row = next((r for r in (t.get("cache") or {}).get("players") or [] if r["userid"] == str(ctx.author.id)), None)
        if row:
            e.add_field(name="Your tournament", value=f"{row['matches']} matches • {row['runs']} runs (HS {row['highest']}) • "
                                                      f"{row['wickets']} wickets • MVP {row['mvp']}", inline=False)
        await ctx.send(embed=e)

    async def c_settings(ctx, args):
        t = await current(ctx)
        if t is not None:
            await send_pages(ctx, render.settings_pages(t))

    async def c_log(ctx, args):
        t = await current(ctx, active=False)
        if t is None:
            return
        if not await mgr.is_organizer(t, ctx.author):
            await say(ctx, "Only organisers can read the log.")
            return
        rows = await store.list_audit(db, t["tournament_id"], 40)
        pages = []
        for i in range(0, max(len(rows), 1), 10):
            lines = [f"<t:{r['created_at']}:R> **{r['actor_name']}** `{r['action']}`{' 🌐' if r['source'] == 'web' else ''}\n"
                     f"-# {theme.truncate(r['detail'], 150)}" for r in rows[i:i + 10]]
            pages.append(theme.embed(f"🧾 {t['name']} — log", "\n".join(lines) or "Nothing yet.", theme.GREY))
        await send_pages(ctx, pages)

    async def c_history(ctx, args):
        rows = await store.list_for_guild(db, ctx.guild.id)
        if not rows:
            await say(ctx, "This server hasn't run a tournament yet.")
            return
        lines = []
        for t in rows:
            teams = {x["team_id"]: x["name"] for x in await store.list_teams(db, t["tournament_id"])}
            champ = f" — 🥇 **{teams.get(t['champion_team_id'], '?')}**" if t.get("champion_team_id") else ""
            url = theme.tournament_url(t["tournament_id"])
            name = f"[{t['name']}]({url})" if url else f"**{t['name']}**"
            lines.append(f"{render.STATUS_BADGE.get(t['status'], t['status'])} · {name}{champ} · <t:{t['created_at']}:D>")
        await ctx.send(embed=theme.embed(f"📚 Tournaments in {ctx.guild.name}", theme.truncate("\n".join(lines), 4000), theme.BLUE))

    async def c_staff(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if args and args[0].lower() in ("add", "remove", "rm", "del") and len(args) >= 2:
            m = await member_arg(ctx, args[1])
            if m is not None:
                await do(ctx, t, "staff.add" if args[0].lower() == "add" else "staff.remove",
                         {"user_id": m.id, "user_name": m.name})
            return
        staff = await store.list_staff(db, t["tournament_id"])
        lines = [f"👑 <@{t['host_id']}> — host"] + [f"🛡️ <@{s['user_id']}>" + (" (role)" if s["source"] == "role" else "")
                                                    for s in staff if s["user_id"] != t["host_id"]]
        roles = t["settings"]["organizer_roles"]
        e = theme.embed(f"🛡️ {t['name']} — organisers", "\n".join(lines), theme.BLUE)
        e.add_field(name="Organiser roles", value=" ".join(f"<@&{r}>" for r in roles) or "none", inline=False)
        e.set_footer(text=theme.footer_text(f"Members with Manage Server can always organise • {P}tour staff add @user"))
        await ctx.send(embed=e, allowed_mentions=NO_PING)

    # ───────────────────────────────────────────────────────── lifecycle
    async def c_create(ctx, args):
        name = " ".join(args).strip()
        if not name:
            await say(ctx, f"Usage: `{P}tour create <tournament name>`")
            return
        try:
            t = await mgr.create(ctx.guild, ctx.author, name)
        except TournamentError as e:
            await say(ctx, f"{theme.CROSS} {e}")
            return
        e = theme.embed(f"🏆 {t['name']} created", (
            f"You are the host. The tournament is in **set-up**.\n\n"
            f"**1.** Choose the format: `{P}tour set format league|groups|knockout`\n"
            f"**2.** Match rules: `{P}tour set overs 10` • `{P}tour set days 2` (`{P}tour settings` shows everything)\n"
            f"**3.** Channels & roles: `{P}tour channel announce #channel` • `{P}tour role player @role`\n"
            f"**4.** `{P}tour open` — players register and build teams\n"
            f"**5.** `{P}tour start` — fixtures are drawn and rosters lock"), theme.GOLD)
        url = theme.tournament_url(t["tournament_id"])
        if url:
            e.add_field(name="Website", value=f"Manage it in the browser: {url}", inline=False)
        e.set_footer(text=theme.footer_text(f"{P}tour help for every command"))
        await ctx.send(embed=e)

    async def c_set(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if len(args) < 2:
            await say(ctx, f"Usage: `{P}tour set <name> <value>` — see `{P}tour settings` for the names.")
            return
        await do(ctx, t, "settings.set", {"key": args[0], "value": " ".join(args[1:])})

    def simple(action: str, build=None, usage: str = ""):
        async def handler(ctx, args):
            t = await current(ctx)
            if t is None:
                return
            params = build(args) if build else {}
            if params is None:
                await say(ctx, f"Usage: `{P}tour {usage}`")
                return
            await do(ctx, t, action, params)
        return handler

    async def c_destructive(ctx, args, action: str, question: str, any_status: bool = False):
        t = await (store.latest_for_guild(db, ctx.guild.id) if any_status else store.active_for_guild(db, ctx.guild.id))
        if t is None:
            await say(ctx, "There is no tournament to do that to.")
            return
        if not await mgr.is_organizer(t, ctx.author):
            await say(ctx, f"{theme.CROSS} Only tournament organisers can do that.")
            return
        rest = [a for a in args if str(a).lower() not in ("confirm", "yes", "-y")]
        if not await confirm(ctx, args, question.format(name=t["name"])):
            return
        params = {}
        if action == "end" and rest:
            params["champion"] = " ".join(rest)
        await do(ctx, t, action, params)

    async def c_end(ctx, args):
        await c_destructive(ctx, args, "end", "Finish **{name}** now? Remaining matches will not be played.")

    async def c_cancel(ctx, args):
        await c_destructive(ctx, args, "cancel", "Cancel **{name}**? It stays on record but can't be played on.")

    async def c_delete(ctx, args):
        await c_destructive(ctx, args, "delete", "Delete **{name}** with all its teams, fixtures and tables? "
                                                 "This can't be undone.", any_status=True)

    async def c_reopen(ctx, args):
        t = await store.latest_for_guild(db, ctx.guild.id)
        if t is None:
            await say(ctx, "There is no tournament to reopen.")
            return
        await do(ctx, t, "reopen")

    # ───────────────────────────────────────────────────────── players
    async def c_register(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if args:
            for token in args:
                m = await member_arg(ctx, token)
                if m is not None:
                    await do(ctx, t, "register", {"user_id": m.id, "user_name": m.name})
            return
        await do(ctx, t, "register")

    async def c_unregister(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if args:
            m = await member_arg(ctx, args[0])
            if m is not None:
                await do(ctx, t, "unregister", {"user_id": m.id, "user_name": m.name})
            return
        await do(ctx, t, "unregister")

    async def c_leave(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        pl = await store.get_player(db, t["tournament_id"], ctx.author.id)
        await do(ctx, t, "team.leave" if pl and pl["team_id"] else "unregister")

    async def c_invite(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        users, rest = _split_users(args)
        if not users:
            await say(ctx, f"Usage: `{P}tour invite @user` (organisers: `{P}tour invite <team> @user`)")
            return
        for token in users:
            m = await member_arg(ctx, token)
            if m is None:
                continue
            params = {"user_id": m.id, "user_name": m.name}
            if rest:
                params["team"] = " ".join(rest)
            try:
                result = await mgr.run(ctx.guild, t, ctx.author, "team.invite", params)
            except TournamentError as e:
                await say(ctx, f"{theme.CROSS} {e}")
                continue
            team_id = next((eff[2] for eff in result.effects if eff[0] == "invite"), None)
            team = await store.get_team(db, team_id) if team_id else None
            view = InviteView(bot, t["tournament_id"], team, m.id) if team else None
            msg = await ctx.send(f"{m.mention} — {result.message}", view=view)
            if view is not None:
                view.message = msg

    async def c_accept(ctx, args):
        t = await current(ctx)
        if t is not None:
            await do(ctx, t, "invite.accept", {"team": " ".join(args)} if args else {})

    async def c_decline(ctx, args):
        t = await current(ctx)
        if t is not None:
            await do(ctx, t, "invite.decline", {"team": " ".join(args)} if args else {})

    async def c_ban(ctx, args, action="player.ban"):
        t = await current(ctx)
        if t is None:
            return
        if not args:
            await say(ctx, f"Usage: `{P}tour {'ban' if action == 'player.ban' else 'unban'} @user`")
            return
        m = await member_arg(ctx, args[0])
        if m is not None:
            await do(ctx, t, action, {"user_id": m.id, "user_name": m.name})

    async def c_unban(ctx, args):
        await c_ban(ctx, args, "player.unban")

    async def c_host(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if not args:
            await say(ctx, f"Usage: `{P}tour host @user`")
            return
        m = await member_arg(ctx, args[0])
        if m is not None:
            await do(ctx, t, "host.transfer", {"user_id": m.id, "user_name": m.name})

    # ───────────────────────────────────────────────────────── teams
    async def c_team(ctx, args):
        if not args:
            return await c_teams(ctx, args)
        sub = args[0].lower()
        rest = list(args[1:])
        read_only = sub not in TEAM_SUBS
        t = await current(ctx, active=not read_only)
        if t is None:
            return
        if read_only:
            return await show_team(ctx, t, " ".join(args))
        organizer = await mgr.is_organizer(t, ctx.author)
        users, words = _split_users(rest)

        async def user_param(required=True):
            if not users:
                if required:
                    await say(ctx, "Mention the member (or use their ID).")
                return None
            m = await member_arg(ctx, users[0])
            return {"user_id": m.id, "user_name": m.name} if m is not None else None

        if sub in ("create", "new"):
            name = " ".join(words).strip()
            if not name:
                await say(ctx, f"Usage: `{P}tour team create <team name>`" + (" `[@captain]`" if organizer else ""))
                return
            params = {"name": name}
            if users and organizer:
                up = await user_param()
                if up is None:
                    return
                params.update(up)
            await do(ctx, t, "team.create", params)
        elif sub in ("info", "show", "view"):
            await show_team(ctx, t, " ".join(rest))
        elif sub in ("invite", "inv"):
            await c_invite(ctx, rest)
        elif sub == "join":
            await do(ctx, t, "team.join", {"team": " ".join(rest)})
        elif sub == "leave":
            await do(ctx, t, "team.leave")
        elif sub in ("kick", "remove", "rm"):
            up = await user_param()
            if up is not None:
                await do(ctx, t, "team.remove", up)
        elif sub in ("add", "move", "assign"):
            if not users or not words:
                await say(ctx, f"Usage: `{P}tour team add <team> @user [@user…]`")
                return
            for token in users:
                m = await member_arg(ctx, token)
                if m is not None:
                    await do(ctx, t, "team.add", {"team": " ".join(words), "user_id": m.id, "user_name": m.name})
        elif sub in ("captain", "cap", "vice", "vc"):
            action = "team.captain" if sub in ("captain", "cap") else "team.vice"
            if sub in ("vice", "vc") and not users and words and words[-1].lower() == "none":
                params = {"user_id": "none"}
                words = words[:-1]
            else:
                params = await user_param()
                if params is None:
                    return
            if words and organizer:
                params["team"] = " ".join(words)
            await do(ctx, t, action, params)
        elif sub in ("rename", "name", "tag"):
            if not words:
                await say(ctx, f"Usage: `{P}tour team {sub} <new {'tag' if sub == 'tag' else 'name'}>`"
                          + (f" — organisers: `{P}tour team {sub} <team> <new>`" if organizer else ""))
                return
            params = {}
            teams = await store.list_teams(db, t["tournament_id"])
            if organizer and len(words) >= 2 and store.match_team(teams, words[0]) is not None:
                params["team"] = words[0]
                words = words[1:]
            if sub == "tag":
                params["tag"] = words[0]
                await do(ctx, t, "team.tag", params)
            else:
                params["name"] = " ".join(words)
                await do(ctx, t, "team.rename", params)
        elif sub in ("disband", "delete", "del"):
            params = {"team": " ".join(a for a in words if a.lower() != "confirm")} if organizer and words else {}
            await do(ctx, t, "team.delete", params)
        elif sub == "withdraw":
            if not words:
                await say(ctx, f"Usage: `{P}tour team withdraw <team>`")
                return
            await do(ctx, t, "team.withdraw", {"team": " ".join(words)})
        elif sub in ("pool", "group"):
            if len(words) < 2:
                await say(ctx, f"Usage: `{P}tour team pool <team> <A-H>`")
                return
            await do(ctx, t, "team.group", {"team": " ".join(words[:-1]), "group": words[-1]})
        elif sub == "seed":
            if len(words) < 2:
                await say(ctx, f"Usage: `{P}tour team seed <team> <number>`")
                return
            await do(ctx, t, "team.seed", {"team": " ".join(words[:-1]), "seed": words[-1]})
        elif sub == "role":
            role_tokens = [a for a in rest if str(a).startswith("<@&") or str(a).lower() == "none" or str(a).isdigit()]
            name = " ".join(a for a in rest if a not in role_tokens)
            if not role_tokens or not name:
                await say(ctx, f"Usage: `{P}tour team role <team> @role` (or `none`)")
                return
            await do(ctx, t, "team.role", {"team": name, "role": role_tokens[0]})

    TEAM_SUBS = {"create", "new", "info", "show", "view", "invite", "inv", "join", "leave", "kick", "remove", "rm", "add",
                 "move", "assign", "captain", "cap", "vice", "vc", "rename", "name", "tag", "disband", "delete", "del",
                 "withdraw", "pool", "group", "seed", "role"}

    async def c_move(ctx, args):
        await c_team(ctx, ["add", *args])

    # ───────────────────────────────────────────────────────── fixtures
    def _pair(words) -> tuple[str, str] | None:
        low = [w.lower() for w in words]
        for sep in ("v", "vs", "vs.", "-"):
            if sep in low:
                i = low.index(sep)
                a, b = " ".join(words[:i]), " ".join(words[i + 1:])
                return (a, b) if a and b else None
        if len(words) == 2:
            return words[0], words[1]
        return None

    async def c_fixture(ctx, args):
        if not args or args[0].lower() in ("list", "all"):
            return await c_fixtures(ctx, args[1:] if args else [])
        sub, rest = args[0].lower(), list(args[1:])
        if sub not in ("add", "new", "remove", "rm", "delete", "time", "schedule", "teams", "reset", "replay"):
            return await c_fixtures(ctx, args)
        t = await current(ctx)
        if t is None:
            return
        if sub in ("add", "new"):
            stage = "group"
            words = []
            when = []
            for w in rest:
                if w.lower() in ("extra", "friendly", "exhibition"):
                    stage = "extra"
                elif when or w.startswith("+") or w[:1].isdigit() and ("-" in w or ":" in w) or w.startswith("<t:"):
                    when.append(w)
                else:
                    words.append(w)
            pair = _pair(words)
            if pair is None:
                await say(ctx, f"Usage: `{P}tour fixture add <team> v <team> [extra] [time]` (team tags work best)")
                return
            params = {"team_a": pair[0], "team_b": pair[1], "stage": stage}
            if when:
                params["time"] = " ".join(when)
            await do(ctx, t, "fixture.add", params)
        elif sub in ("remove", "rm", "delete"):
            await do(ctx, t, "fixture.remove", {"number": rest[0] if rest else None})
        elif sub in ("time", "schedule"):
            await c_schedule(ctx, rest)
        elif sub == "teams":
            pair = _pair(rest[1:]) if rest else None
            if pair is None:
                await say(ctx, f"Usage: `{P}tour fixture teams <number> <team> v <team>`")
                return
            await do(ctx, t, "fixture.teams", {"number": rest[0], "team_a": pair[0], "team_b": pair[1]})
        elif sub in ("reset", "replay"):
            await do(ctx, t, "fixture.reset", {"number": rest[0] if rest else None})

    async def c_schedule(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if len(args) < 2:
            await say(ctx, f"Usage: `{P}tour schedule <match number> <time>` — e.g. `2025-07-01 18:30` (UTC), `+2h`, `none`")
            return
        await do(ctx, t, "fixture.schedule", {"number": args[0], "time": " ".join(args[1:])})

    async def c_result(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        force = any(a.lower() == "force" for a in args)
        args = [a for a in args if a.lower() != "force"]
        if len(args) < 2:
            await say(ctx, f"Usage: `{P}tour result <match number> <team|draw|tie|nr>`")
            return
        await do(ctx, t, "fixture.result", {"number": args[0], "outcome": " ".join(args[1:]), "force": force})

    async def c_walkover(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if len(args) < 2:
            await say(ctx, f"Usage: `{P}tour walkover <match number> <winning team>`")
            return
        await do(ctx, t, "fixture.walkover", {"number": args[0], "winner": " ".join(args[1:])})

    # ───────────────────────────────────────────────────────── roles & channels
    async def c_role(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        if not args:
            s = t["settings"]
            e = theme.embed(f"🎭 {t['name']} — roles", color=theme.BLUE)
            for key in ("organizer_roles", "player_role", "captain_role", "registration_role", "auto_team_roles"):
                e.add_field(name=schema.SETTINGS[key]["label"], value=schema.describe(key, s[key]), inline=True)
            e.set_footer(text=theme.footer_text(f"{P}tour role organizer|player|captain|register @role • auto on|off • sync • clear"))
            await ctx.send(embed=e, allowed_mentions=NO_PING)
            return
        sub, rest = args[0].lower(), list(args[1:])
        keys = {"organizer": "organizer_roles", "organiser": "organizer_roles", "staff": "organizer_roles",
                "player": "player_role", "players": "player_role", "captain": "captain_role", "captains": "captain_role",
                "register": "registration_role", "registration": "registration_role"}
        if sub in keys:
            if not rest:
                await say(ctx, f"Usage: `{P}tour role {sub} @role` (or `none`)")
                return
            await do(ctx, t, "settings.set", {"key": keys[sub], "value": " ".join(rest)})
        elif sub == "auto":
            await do(ctx, t, "settings.set", {"key": "auto_team_roles", "value": rest[0] if rest else "on"})
        elif sub == "team":
            await c_team(ctx, ["role", *rest])
        elif sub == "sync":
            await do(ctx, t, "roles.sync")
        elif sub in ("clear", "cleanup"):
            if not await mgr.is_organizer(t, ctx.author):
                await say(ctx, f"{theme.CROSS} Only tournament organisers can do that.")
                return
            n = await mgr.clear_roles(ctx.guild, t)
            await say(ctx, f"🎭 Removed tournament roles from **{n}** member(s) and deleted the team roles I created.")
        else:
            await say(ctx, f"See `{P}tour help` → Roles & channels.")

    async def c_channel(ctx, args):
        t = await current(ctx)
        if t is None:
            return
        keys = {"announce": "announce_channel", "announcements": "announce_channel", "news": "announce_channel",
                "results": "results_channel", "result": "results_channel", "log": "log_channel", "logs": "log_channel"}
        if len(args) < 2 or args[0].lower() not in keys:
            s = t["settings"]
            await say(ctx, "\n".join(f"**{schema.SETTINGS[k]['label']}:** {schema.describe(k, s[k])}"
                                     for k in ("announce_channel", "results_channel", "log_channel"))
                      + f"\nChange with `{P}tour channel announce|results|log #channel` (or `none`).")
            return
        await do(ctx, t, "settings.set", {"key": keys[args[0].lower()], "value": args[1]})

    COMMANDS = {
        "info": c_overview, "overview": c_overview, "status": c_overview,
        "help": c_help, "commands": c_help, "rules": c_rules,
        "teams": c_teams, "team": c_team, "players": c_players, "freeagents": c_players, "fa": c_players,
        "fixtures": c_fixtures, "matches": c_fixtures, "schedule": c_schedule, "fixture": c_fixture, "match": c_fixture,
        "results": c_results, "table": c_table, "standings": c_table, "points": c_table, "pt": c_table,
        "bracket": c_bracket, "knockout": c_bracket, "stats": c_stats, "leaders": c_stats, "lb": c_stats, "top": c_stats,
        "player": c_player, "me": c_me, "mine": c_me, "next": c_me,
        "settings": c_settings, "config": c_settings, "log": c_log, "audit": c_log, "history": c_history,
        "staff": c_staff, "host": c_host,
        "create": c_create, "new": c_create, "set": c_set,
        # organisers: allow substitutes from outside a team's registered squad (tour subs on|off)
        "subs": simple("settings.set", lambda a: {"key": "subs_outside_squad", "value": a[-1]} if a else None,
                       "subs on|off — on: substitutes may come from outside the team's squad"),
        "outsidesubs": simple("settings.set", lambda a: {"key": "subs_outside_squad", "value": a[-1]} if a else None,
                              "outsidesubs on|off"),
        "name": simple("rename", lambda a: {"name": " ".join(a)} if a else None, "name <new name>"),
        "rename": simple("rename", lambda a: {"name": " ".join(a)} if a else None, "name <new name>"),
        "desc": simple("describe", lambda a: {"text": " ".join(a)}),
        "description": simple("describe", lambda a: {"text": " ".join(a)}),
        "format": simple("settings.set", lambda a: {"key": "format", "value": a[0]} if a else None,
                         "format league|groups|knockout"),
        "open": simple("registration.open"), "close": simple("registration.close"),
        "lock": simple("rosters.lock"), "unlock": simple("rosters.unlock"),
        "draw": simple("groups.draw", lambda a: {"mode": a[0] if a else "random"}),
        "generate": simple("fixtures.generate"), "gen": simple("fixtures.generate"),
        "start": simple("start"), "begin": simple("start"),
        "advance": simple("advance", lambda a: {"force": any(x.lower() == "force" for x in a)}),
        "end": c_end, "finish": c_end, "cancel": c_cancel, "delete": c_delete, "reopen": c_reopen,
        "register": c_register, "signup": c_register, "join": c_register, "add": c_register,
        "unregister": c_unregister, "leave": c_leave,
        "invite": c_invite, "accept": c_accept, "decline": c_decline,
        "ban": c_ban, "unban": c_unban, "autofill": simple("players.autofill"), "move": c_move,
        "result": c_result, "walkover": c_walkover, "wo": c_walkover,
        "role": c_role, "roles": c_role, "channel": c_channel, "channels": c_channel,
        "announce": simple("announce", lambda a: {"text": " ".join(a)} if a else None, "announce <text>"),
        "say": simple("announce", lambda a: {"text": " ".join(a)} if a else None, "announce <text>"),
    }

    @bot.command(name="tournament", aliases=["tour", "tn", "tourney"],
                 help="Tournament mode: teams, pools, fixtures, tables and brackets. See `tour help`.")
    @commands.guild_only()
    async def tournament_cmd(ctx: commands.Context, sub: str = None, *args):
        handler = COMMANDS.get((sub or "info").lower())
        if handler is None:
            await say(ctx, f"I don't know `{P}tour {sub}`. See `{P}tour help`.")
            return
        await handler(ctx, list(args))

    # ───────────────────────────────────────────────────────── tm
    @bot.command(name="tm", aliases=["tmatch", "tournamentmatch"],
                 help="Mark the lobby in this channel as a tournament match: tm [match number] • tm off")
    @commands.guild_only()
    async def tournament_match(ctx: commands.Context, which: str = None):
        mi = bot.active_matches.get(ctx.channel.id)
        if mi is None:
            await say(ctx, f"Create a lobby first with `{P}create`, then use `{P}tm`.")
            return
        if which and which.lower() in ("off", "no", "none", "friendly", "unmark"):
            info = getattr(mi, "tournament", None)
            if not info:
                await say(ctx, "This lobby isn't a tournament match.")
                return
            if mi.game_started:
                await say(ctx, f"The match has started. An organiser can release the fixture with `{P}tour fixture reset {info['number']}`.")
                return
            t = await store.get(db, info["id"])
            if ctx.author != mi.host and not (t and await mgr.is_organizer(t, ctx.author)):
                await say(ctx, "Only the match host or an organiser can do that.")
                return
            mi.tournament = None
            mi.team_settings["Team A name"], mi.team_settings["Team B name"] = "Team A", "Team B"
            bot.store.schedule(mi)
            await say(ctx, "This lobby is a **friendly** again — anyone can join.")
            return
        t = await store.active_for_guild(db, ctx.guild.id)
        if t is None:
            await say(ctx, "There is no tournament running in this server.")
            return
        organizer = await mgr.is_organizer(t, ctx.author)
        if ctx.author != mi.host and not organizer:
            await say(ctx, "Only the match host or a tournament organiser can mark this lobby.")
            return
        try:
            if which:
                num = str(which).lstrip("#")
                fx = await store.fixture_by_number(db, t["tournament_id"], int(num)) if num.isdigit() and len(num) < 6 else None
                if fx is None:
                    await say(ctx, f"There is no match `{which}`. See `{P}tour fixtures`.")
                    return
                await say(ctx, await mgr.mark_lobby(mi, t, fx, ctx.author))
                return
            if t["status"] != "ongoing":
                raise TournamentError(f"**{t['name']}** hasn't started yet (`{P}tour start`).")
            options = await mgr.playable(t, ctx.author, organizer)
            if not options:
                raise TournamentError("There is no tournament match you can start right now"
                                      + ("." if organizer else " — captains can only start their own team's fixtures."))
            mine = [o for o in options if o["_mine"]]
            if len(options) == 1 or len(mine) == 1:
                await say(ctx, await mgr.mark_lobby(mi, t, (mine or options)[0], ctx.author))
                return
            view = FixturePickView(bot, mi, t, options, ctx.author.id)
            view.message = await ctx.send("Which tournament match is this?", view=view)
        except TournamentError as e:
            await say(ctx, f"{theme.CROSS} {e}")
