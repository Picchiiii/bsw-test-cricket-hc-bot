"""The bot side of tournaments: permissions, Discord effects (roles, announcements), match hooks and the
background loops that run website requests and reminders.

`bot.tournaments` is one TournamentManager. Commands and the website both end up in `run()`.
"""
import asyncio
import json
import logging
import time
import types

import discord

from core.config import config
from core.economy import profiles
from core.economy import settings as eco_settings
from core.tournament import actions, logic, schema, store
from core.tournament.actions import Actor, Result, TournamentError
from core.ui import theme

logger = logging.getLogger(__name__)
P = config.prefix


def now() -> int:
    return int(time.time())


def _perms(member):
    return getattr(member, "guild_permissions", None)


def has_manage_guild(member) -> bool:
    perms = _perms(member)
    guild = getattr(member, "guild", None)
    if guild is not None and getattr(guild, "owner_id", None) == member.id:
        return True
    return bool(perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False)))


def _role_ids(member) -> set:
    return {str(r.id) for r in getattr(member, "roles", []) or []}


class TournamentManager:
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self._tasks: list[asyncio.Task] = []
        self._meta_dirty: set[int] = set()
        self._last_meta = 0

    # ───────────────────────────────────────────────────────── permissions
    async def is_organizer(self, t: dict, member) -> bool:
        if member is None:
            return False
        if await self.bot.is_owner(member):
            return True
        if str(member.id) == str(t.get("host_id")) or has_manage_guild(member):
            return True
        if _role_ids(member) & set(t["settings"].get("organizer_roles") or []):
            return True
        return await store.is_staff(self.db, t["tournament_id"], member.id)

    async def can_create(self, member) -> bool:
        return has_manage_guild(member) or await self.bot.is_owner(member)

    async def actor_for(self, t: dict, member, source: str = "bot") -> Actor:
        return Actor(id=str(member.id), name=member.name, organizer=await self.is_organizer(t, member),
                     owner=await self.bot.is_owner(member), source=source)

    # ───────────────────────────────────────────────────────── running actions
    async def create(self, guild, member, name: str, source: str = "bot") -> dict:
        if not await self.can_create(member):
            raise TournamentError("You need the **Manage Server** permission to create a tournament.")
        active = await store.active_for_guild(self.db, guild.id)
        if active is not None:
            raise TournamentError(f"**{active['name']}** is already running here — a server has one tournament at a "
                                  f"time. Finish it (`{P}tour end`) or cancel it (`{P}tour cancel`) first.")
        clean = actions._clean_name(name, "tournament name", 3, 60)
        try:
            t = await store.create(self.db, guild.id, guild.name, clean, member.id, member.name)
        except Exception as e:      # the unique index is the last line of defence against a double create
            raise TournamentError("A tournament is already running in this server.") from e
        await store.add_audit(self.db, t["tournament_id"], member.id, member.name, "create", f"Created {clean}", source)
        await self.refresh_guild_meta(guild)
        await self.refresh_cache(t)
        return t

    async def run(self, guild, t: dict, member, action: str, params: dict | None = None, source: str = "bot") -> Result:
        """Check permission, run one action, then apply what follows from it in Discord."""
        actor = await self.actor_for(t, member, source)
        clean = {k: v for k, v in (params or {}).items() if not str(k).startswith("_")}
        uid = clean.get("user_id")
        if uid is not None and str(uid).lower() not in ("", "none"):      # always re-resolved: never trust a sent name
            target = await self._member(guild, uid)
            if target is None:
                raise TournamentError("That user isn't a member of this server.")
            if target.bot:
                raise TournamentError("Bots can't take part in tournaments.")
            clean["user_id"], clean["user_name"] = str(target.id), target.name
        if action == "register":
            need = t["settings"].get("registration_role")
            if need and need not in _role_ids(member):
                clean["_missing_role"] = True
        if action == "host.transfer":
            clean["_manage_guild"] = has_manage_guild(member)
        result = await actions.perform(self.db, t, actor, action, clean)
        fresh = await store.get(self.db, t["tournament_id"])
        await self.apply_effects(guild, fresh or t, result)
        if fresh is not None:
            await self.refresh_cache(fresh)
        if actions.ACTIONS[action]["level"] != "any" or actor.organizer:
            await self._log(guild, fresh or t, f"**{actor.name}** · `{action}` — {result.message}"
                            + (" *(website)*" if source == "web" else ""))
        return result

    async def _member(self, guild, user_id):
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        m = guild.get_member(uid)
        if m is None:
            try:
                m = await guild.fetch_member(uid)
            except Exception:
                m = None
        return m

    # ───────────────────────────────────────────────────────── effects
    async def apply_effects(self, guild, t: dict, result: Result):
        notes = []
        for eff in result.effects:
            kind = eff[0]
            try:
                if kind == "announce":
                    await self.announce(guild, t, eff[1], ping=len(eff) > 2 and eff[2])
                elif kind == "result":
                    await self.announce(guild, t, eff[1], channel_key="results_channel", match_id=eff[2] if len(eff) > 2 else None)
                elif kind == "finale":
                    await self.announce(guild, t, eff[1], ping=True)
                elif kind == "note":
                    notes.append(eff[1])
                elif kind == "roles":
                    warn = await self.sync_roles(guild, t)
                    if warn:
                        notes.append(warn)
                elif kind == "unrole":
                    await self.remove_roles(guild, t, eff[1], eff[2], eff[3] if len(eff) > 3 else True,
                                            eff[4] if len(eff) > 4 else None)
                elif kind == "delete_role":
                    role = guild.get_role(int(eff[1])) if guild is not None else None
                    if role is not None:
                        await role.delete(reason="Tournament team disbanded")
                elif kind == "invite":
                    await self._dm_invite(guild, t, eff[1], eff[3])
                elif kind == "prizes":
                    note = await self.pay_prizes(guild, t)
                    if note:
                        notes.append(note)
                elif kind == "unbind":
                    await self.unbind(fixture_id=eff[1])
                elif kind == "unbind_all":
                    await self.unbind(tournament_id=t["tournament_id"])
            except TournamentError:
                raise
            except Exception as e:      # a Discord hiccup must never undo the database change
                logger.warning("tournament effect %s failed: %r", kind, e)
        if notes:
            result.message += "\n" + "\n".join(f"-# {n}" for n in notes)

    def _channel(self, guild, t: dict, key: str):
        if guild is None:
            return None
        for k in (key, "announce_channel"):
            cid = t["settings"].get(k)
            if cid:
                ch = guild.get_channel(int(cid))
                if ch is not None:
                    return ch
        return None

    async def announce(self, guild, t: dict, text: str, ping: bool = False, channel_key: str = "announce_channel",
                       match_id: str | None = None):
        channel = self._channel(guild, t, channel_key)
        if channel is None:
            return None
        e = discord.Embed(description=theme.truncate(text, 4000), color=theme.GOLD)
        e.set_footer(text=theme.footer_text(t["name"]))
        url = theme.tournament_url(t["tournament_id"])
        if match_id:
            url = theme.match_url(match_id) or url
        if url:
            e.url = url
            e.title = "🏆 " + t["name"]
        content = None
        role = t["settings"].get("player_role")
        if ping and role:
            content = f"<@&{role}>"
        try:
            return await channel.send(content=content, embed=e)
        except discord.HTTPException as err:
            logger.warning("tournament announce failed in %s: %s", getattr(channel, "id", "?"), err)
            return None

    async def _log(self, guild, t: dict, text: str):
        cid = t["settings"].get("log_channel")
        if not cid or guild is None:
            return
        ch = guild.get_channel(int(cid))
        if ch is None:
            return
        try:
            await ch.send(embed=discord.Embed(description=theme.truncate(text, 2000), color=theme.GREY))
        except discord.HTTPException:
            pass

    async def _dm_invite(self, guild, t: dict, user_id, team_name: str):
        member = await self._member(guild, user_id)
        if member is None:
            return
        try:
            await member.send(embed=theme.embed(
                f"✉️ Team invite — {t['name']}",
                f"**{team_name}** invited you to join them in **{t['name']}** ({guild.name}).\n"
                f"In the server, type `{P}tour accept` to join or `{P}tour decline` to say no.", theme.GOLD))
        except discord.HTTPException:
            pass

    # ───────────────────────────────────────────────────────── roles
    async def sync_roles(self, guild, t: dict) -> str:
        """Give every player their tournament roles. Returns a warning to show, or ''."""
        if guild is None:
            return ""
        s = t["settings"]
        tid = t["tournament_id"]
        teams = await store.list_teams(self.db, tid)
        problems = set()
        if s.get("auto_team_roles"):
            for team in teams:
                role = guild.get_role(int(team["role_id"])) if team.get("role_id") else None
                try:
                    if role is None and team["status"] == "active":
                        role = await guild.create_role(name=team["name"], mentionable=True,
                                                       reason=f"Tournament team ({t['name']})")
                        await store.update_team(self.db, team["team_id"], role_id=str(role.id), role_auto=1)
                        team["role_id"], team["role_auto"] = str(role.id), 1
                    elif role is not None and team.get("role_auto") and role.name != team["name"]:
                        await role.edit(name=team["name"])
                except discord.HTTPException:
                    problems.add("create team roles")
        by_id = {x["team_id"]: x for x in teams}
        managed = {x for x in [s.get("player_role"), s.get("captain_role")] if x}
        managed |= {x["role_id"] for x in teams if x.get("role_id")}
        if not managed:
            return ""
        for pl in await store.list_players(self.db, tid):
            member = guild.get_member(int(pl["user_id"]))
            if member is None:
                continue
            team = by_id.get(pl["team_id"]) if pl["status"] == "active" else None
            want = set()
            if team is not None:
                if s.get("player_role"):
                    want.add(s["player_role"])
                if team.get("role_id"):
                    want.add(team["role_id"])
                if s.get("captain_role") and team["captain_id"] == pl["user_id"]:
                    want.add(s["captain_role"])
            have = _role_ids(member)
            add = [guild.get_role(int(r)) for r in want - have]
            drop = [guild.get_role(int(r)) for r in (managed - want) & have]
            try:
                if any(add):
                    await member.add_roles(*[r for r in add if r], reason=f"Tournament: {t['name']}")
                if any(drop):
                    await member.remove_roles(*[r for r in drop if r], reason=f"Tournament: {t['name']}")
            except discord.HTTPException:
                problems.add("assign roles")
        if problems:
            return (f"I couldn't {' / '.join(sorted(problems))}. Give me **Manage Roles** and move my role above the "
                    f"tournament roles, then run `{P}tour role sync`.")
        return ""

    async def remove_roles(self, guild, t: dict, user_id, team_id, full: bool = True, role_id=None):
        if guild is None:
            return
        member = guild.get_member(int(user_id))
        if member is None:
            return
        s = t["settings"]
        ids = set()
        if role_id:
            ids.add(str(role_id))
        elif team_id:
            team = await store.get_team(self.db, team_id)
            if team and team.get("role_id"):
                ids.add(team["role_id"])
        for key in ("captain_role", "player_role"):      # both belong to players who are on a team
            if s.get(key):
                ids.add(s[key])
        roles = [guild.get_role(int(r)) for r in ids & _role_ids(member)]
        if any(roles):
            try:
                await member.remove_roles(*[r for r in roles if r], reason=f"Tournament: {t['name']}")
            except discord.HTTPException:
                pass

    async def clear_roles(self, guild, t: dict) -> int:
        """Take the tournament roles off every registered player and delete the roles the bot created."""
        s = t["settings"]
        teams = await store.list_teams(self.db, t["tournament_id"])
        managed = {x for x in [s.get("player_role"), s.get("captain_role")] if x} | {x["role_id"] for x in teams if x.get("role_id")}
        n = 0
        for pl in await store.list_players(self.db, t["tournament_id"]):
            member = guild.get_member(int(pl["user_id"]))
            if member is None:
                continue
            roles = [guild.get_role(int(r)) for r in managed & _role_ids(member)]
            if any(roles):
                try:
                    await member.remove_roles(*[r for r in roles if r], reason=f"Tournament over: {t['name']}")
                    n += 1
                except discord.HTTPException:
                    pass
        for team in teams:
            if team.get("role_auto") and team.get("role_id"):
                role = guild.get_role(int(team["role_id"]))
                try:
                    if role is not None:
                        await role.delete(reason="Tournament over")
                except discord.HTTPException:
                    pass
                await store.update_team(self.db, team["team_id"], role_id="", role_auto=0)
        return n

    async def sync_role_staff(self, guild, t: dict):
        """Record who holds an organiser role, so the website can offer them the Manage page."""
        wanted = set(t["settings"].get("organizer_roles") or [])
        members = []
        if wanted:
            for rid in wanted:
                role = guild.get_role(int(rid))
                for m in getattr(role, "members", []) or []:
                    if not m.bot:
                        members.append((m.id, m.name))
        await store.replace_role_staff(self.db, t["tournament_id"], members)

    # ───────────────────────────────────────────────────────── cache (standings + stats for the website)
    async def tables(self, t: dict) -> tuple[dict, list, list]:
        teams = await store.list_teams(self.db, t["tournament_id"])
        fixtures = await store.list_fixtures(self.db, t["tournament_id"])
        return logic.compute_standings(teams, fixtures, t["settings"]), teams, fixtures

    async def player_table(self, t: dict) -> list[dict]:
        rows = await store.match_stat_rows(self.db, t["tournament_id"])
        team_of = {pl["user_id"]: pl["team_id"] for pl in await store.list_players(self.db, t["tournament_id"])}
        return logic.aggregate_players(rows, team_of)

    async def refresh_cache(self, t: dict) -> dict:
        tables, teams, fixtures = await self.tables(t)
        players = await self.player_table(t)
        awards = {}
        if players:
            for key, cat in (("mvp", "mvp"), ("top_runs", "runs"), ("top_wickets", "wickets"), ("highest", "highest")):
                top = logic.leaders(players, cat, 1)
                if top and top[0][{"mvp": "mvp", "runs": "runs", "wickets": "wickets", "highest": "highest"}[cat]] > 0:
                    awards[key] = {"userid": top[0]["userid"], "name": top[0]["name"],
                                   "text": logic.LEADERBOARDS[cat][2](top[0])}
        old = (await store.get(self.db, t["tournament_id"]) or t).get("cache") or {}
        cache = {
            "standings": tables, "players": players, "awards": awards,
            "counts": {"teams": len([x for x in teams if x["status"] == "active"]),
                       "players": len({p["userid"] for p in players}),
                       "fixtures": len(fixtures),
                       "played": len([f for f in fixtures if f["status"] in logic.DONE])},
            "prizes_paid": old.get("prizes_paid", False),
            "updated_at": now(),
        }
        await store.save_cache(self.db, t["tournament_id"], cache)
        return cache

    async def pay_prizes(self, guild, t: dict) -> str:
        s = t["settings"]
        if not any(s.get(k) for k in ("prize_champion", "prize_runner_up", "prize_mvp", "prize_participation")):
            return ""
        fresh = await store.get(self.db, t["tournament_id"])
        if fresh is None or (fresh.get("cache") or {}).get("prizes_paid"):
            return ""
        tid = t["tournament_id"]
        players = await store.list_players(self.db, tid)
        table = await self.player_table(fresh)
        paid: dict[str, int] = {}

        def give(uid, amount):
            if amount:
                paid[str(uid)] = paid.get(str(uid), 0) + int(amount)

        for pl in players:
            if pl["status"] != "active" or not pl["team_id"]:
                continue
            if pl["team_id"] == fresh.get("champion_team_id"):
                give(pl["user_id"], s["prize_champion"])
            elif pl["team_id"] == fresh.get("runner_up_team_id"):
                give(pl["user_id"], s["prize_runner_up"])
        for r in table:
            give(r["userid"], s["prize_participation"])
        mvp = logic.leaders(table, "mvp", 1)
        if mvp:
            give(mvp[0]["userid"], s["prize_mvp"])
        names = {pl["user_id"]: pl["name"] for pl in players}
        for uid, amount in paid.items():
            await profiles.ensure_profile_id(self.db, uid, names.get(uid, ""))
            await profiles.add_coins(self.db, uid, amount, f"tournament {tid} prize")
        cache = dict(fresh.get("cache") or {})
        cache["prizes_paid"] = True
        await store.save_cache(self.db, tid, cache)
        total = sum(paid.values())
        if total:
            await self.announce(guild, fresh, f"{theme.COIN} **Prize money paid:** {total:,} {theme.CURRENCY} to "
                                              f"{len(paid)} player(s).")
        return f"Prizes paid: {total:,} {theme.CURRENCY} to {len(paid)} player(s)." if total else ""

    # ───────────────────────────────────────────────────────── lobbies & matches
    def lobby_for_fixture(self, fixture_id: str):
        for mi in self.bot.active_matches.values():
            if (getattr(mi, "tournament", None) or {}).get("fixture_id") == fixture_id:
                return mi
        return None

    def _match_running(self, match_id) -> bool:
        return any(mi.match_id == match_id for mi in self.bot.active_matches.values())

    async def unbind(self, fixture_id: str | None = None, tournament_id: str | None = None):
        """Turn bound lobbies / running matches back into friendlies (fixture removed, reset or overruled)."""
        for mi in list(self.bot.active_matches.values()):
            info = getattr(mi, "tournament", None)
            if not info:
                continue
            if (fixture_id and info.get("fixture_id") == fixture_id) or (tournament_id and info.get("id") == tournament_id):
                mi.tournament = None
                store_ = getattr(self.bot, "store", None)
                if store_ is not None:
                    store_.schedule(mi)
                try:
                    await mi.channel.send(embed=theme.embed(
                        "Tournament link removed",
                        "An organiser changed this fixture, so this match no longer counts for the tournament. "
                        "It carries on as a friendly.", theme.GREY))
                except discord.HTTPException:
                    pass

    async def prompt_on_create(self, mi):
        """After `create`: if a tournament is being played in this server, ask whether this is a tournament match."""
        try:
            if mi.guild is None:
                return
            t = await store.active_for_guild(self.db, mi.guild.id)
            if t is None or t["status"] != "ongoing" or not t["settings"]["prompt_on_create"]:
                return
            from core.tournament.views import TournamentPromptView, prompt_embed
            view = TournamentPromptView(self.bot, mi, t)
            view.message = await mi.channel.send(embed=prompt_embed(t), view=view)
        except Exception:
            logger.exception("tournament prompt failed")

    async def playable(self, t: dict, member, organizer: bool) -> list[dict]:
        """Fixtures this member may start now: all open ones for organisers, their own team's for captains."""
        fixtures = await store.list_fixtures(self.db, t["tournament_id"])
        teams = {x["team_id"]: x for x in await store.list_teams(self.db, t["tournament_id"])}
        uid = str(member.id)
        out = []
        for fx in fixtures:
            if not fx["team_a_id"] or not fx["team_b_id"]:
                continue
            if fx["status"] == "live" and self._match_running(fx["match_id"]):
                continue
            if fx["status"] not in ("scheduled", "live"):
                continue
            if self.lobby_for_fixture(fx["fixture_id"]) is not None:
                continue
            a, b = teams.get(fx["team_a_id"]), teams.get(fx["team_b_id"])
            if a is None or b is None:
                continue
            mine = uid in (a["captain_id"], a["vice_captain_id"], b["captain_id"], b["vice_captain_id"])
            if organizer or (t["settings"]["captain_hosting"] and mine):
                out.append(dict(fx, _a=a, _b=b, _mine=mine))
        return out

    async def mark_lobby(self, mi, t: dict, fx: dict, member) -> str:
        """Bind a lobby to a fixture: fixed teams, tournament rules, roster-only joining."""
        if mi.game_started:
            raise TournamentError("The match has already started — mark it before `start`.")
        if t["status"] != "ongoing":
            raise TournamentError(f"**{t['name']}** hasn't started yet (`{P}tour start`).")
        if not fx["team_a_id"] or not fx["team_b_id"]:
            raise TournamentError(f"Match #{fx['number']} doesn't have both teams yet.")
        if fx["status"] in logic.DONE:
            raise TournamentError(f"Match #{fx['number']} already has a result ({fx['result_text']}).")
        if fx["status"] == "live" and self._match_running(fx["match_id"]):
            raise TournamentError(f"Match #{fx['number']} is being played right now in <#{fx['channel_id']}>.")
        other = self.lobby_for_fixture(fx["fixture_id"])
        if other is not None and other is not mi:
            raise TournamentError(f"Match #{fx['number']} already has a lobby in <#{other.channel.id}>.")
        organizer = await self.is_organizer(t, member)
        a = await store.get_team(self.db, fx["team_a_id"])
        b = await store.get_team(self.db, fx["team_b_id"])
        uid = str(member.id)
        mine = uid in (a["captain_id"], a["vice_captain_id"], b["captain_id"], b["vice_captain_id"])
        if not organizer and not (t["settings"]["captain_hosting"] and mine):
            raise TournamentError("Only tournament organisers" + (" or a captain of one of the two teams"
                                  if t["settings"]["captain_hosting"] else "") + " can start this fixture.")
        s = t["settings"]
        mi.tournament = {"id": t["tournament_id"], "name": t["name"], "fixture_id": fx["fixture_id"],
                         "number": fx["number"], "stage": fx["stage"], "group": fx["group_name"],
                         "teams": {"A": a["team_id"], "B": b["team_id"]}, "rosters": {"A": [], "B": []},
                         "captains": {"A": [], "B": []}, "max_side": s["max_players"], "min_side": s["min_players"]}
        mi.team_settings["Team A name"] = a["name"]
        mi.team_settings["Team B name"] = b["name"]
        mi.match_settings["overs"] = s["overs"]
        mi.match_settings["days"] = s["days"]
        mi.match_settings["innings_overs"] = None if s["innings_overs"] < 0 else s["innings_overs"]
        mi.match_settings["follow_on_pct"] = s["follow_on_pct"]
        mi.match_settings["min_declare_overs"] = s["min_declare_overs"]
        mi.min_declare_overs = s["min_declare_overs"]
        mi.match_settings["last_man_bats"] = bool(s["last_man_bats"])
        mi.match_settings["rep_run_cap"] = int(s.get("rep_run_cap", 30))
        mi.match_settings["rep_can_bowl"] = bool(s.get("rep_can_bowl", False))
        mi.match_settings["rep_retire_counts_wicket"] = bool(s.get("rep_retire_counts_wicket", True))
        mi.match_settings["max_reps_per_team"] = int(s.get("max_reps", 0))
        mi.match_settings["max_subs_per_team"] = int(s.get("max_subs", 0))
        mi.match_settings["subs_during_match"] = bool(s.get("allow_subs", True))
        mi.tournament["outside_subs"] = bool(s.get("subs_outside_squad", False))
        mi.toss_winner = None
        mi.toss_decision = None
        mi.batting_turn = mi.bowling_turn = None
        removed = await self.refresh_rosters(mi, a, b)
        store_ = getattr(self.bot, "store", None)
        if store_ is not None:
            store_.schedule(mi)
        text = (f"🏆 This lobby is now **{t['name']}** — match `#{fx['number']}` ({logic.stage_label(fx['stage'])}"
                + (f", Pool {fx['group_name']}" if fx["group_name"] else "") + f"): **{a['name']} v {b['name']}**.\n"
                f"Rules: **{s['overs']}** overs/day, **{s['days']}** day(s). Only players on these two teams can join, "
                f"and they are placed in their own team.")
        if removed:
            text += "\nRemoved (not on either roster): " + ", ".join(f"**{m.name}**" for m in removed)
        return text

    async def refresh_rosters(self, mi, a: dict | None = None, b: dict | None = None) -> list:
        """Reload both rosters and re-seat the lobby. Returns the members who had to be removed."""
        info = mi.tournament
        if not info:
            return []
        a = a or await store.get_team(self.db, info["teams"]["A"])
        b = b or await store.get_team(self.db, info["teams"]["B"])
        if a is None or b is None:
            return []
        tid = info["id"]
        for side, team in (("A", a), ("B", b)):
            info["rosters"][side] = [int(pl["user_id"]) for pl in await store.roster(self.db, tid, team["team_id"])]
            info["captains"][side] = [int(x) for x in (team["captain_id"], team["vice_captain_id"]) if x]
        if mi.game_started:
            return []
        cap = info["max_side"]
        guests = info.get("guests") or {"A": [], "B": []}   # outside substitutes (when the tournament allows them)
        keep = {"A": [m for m in mi.players if m.id in info["rosters"]["A"] or m.id in guests.get("A", [])][:cap],
                "B": [m for m in mi.players if m.id in info["rosters"]["B"] or m.id in guests.get("B", [])][:cap]}
        removed = [m for m in mi.players if m not in keep["A"] and m not in keep["B"]]
        mi.teamA, mi.teamB = keep["A"], keep["B"]
        mi.players = keep["A"] + keep["B"]
        mi.reps = [m for m in mi.reps if m in mi.players]
        mi.bench = {"A": [], "B": []}   # the roster is the squad in a tournament match
        mi.cpu_names = {}               # CPU players never take part in tournament matches
        self.seat_captains(mi)
        return removed

    @staticmethod
    def seat_captains(mi):
        info = mi.tournament or {}
        for side in ("A", "B"):
            team = mi.team(side)
            pick = None
            for cid in info.get("captains", {}).get(side, []):
                pick = next((m for m in team if m.id == cid), None)
                if pick is not None:
                    break
            current = mi.captain(side)
            if pick is None:
                pick = current if current in team else (team[0] if team else None)
            if side == "A":
                mi.teamA_captain = pick
            else:
                mi.teamB_captain = pick

    async def outside_subs_allowed(self, mi) -> bool:
        """Read live, so an organiser can switch it on in the middle of a match (`tour subs on`)."""
        info = getattr(mi, "tournament", None)
        if not info:
            return True
        t = await store.get(self.db, info["id"])
        allowed = bool(t and schema.merged(t.get("settings")).get("subs_outside_squad"))
        info["outside_subs"] = allowed
        return allowed

    async def before_start(self, mi) -> list[str]:
        """Last checks when a tournament match starts. Returns problems; empty = go (fixture becomes live)."""
        info = mi.tournament
        if not info:
            return []
        t = await store.get(self.db, info["id"])
        fx = await store.get_fixture(self.db, info["fixture_id"])
        if t is None or fx is None or t["status"] != "ongoing":
            mi.tournament = None
            return ["the tournament fixture no longer exists — this lobby is a friendly again, start it once more"]
        if fx["status"] in logic.DONE or (fx["status"] == "live" and fx["match_id"] != mi.match_id
                                          and self._match_running(fx["match_id"])):
            mi.tournament = None
            return [f"match #{fx['number']} already has a result or is being played — this lobby is a friendly again"]
        removed = await self.refresh_rosters(mi)
        problems = []
        if removed:
            problems.append("removed players who are no longer on a roster: " + ", ".join(m.name for m in removed))
        need = t["settings"]["min_players"]
        for side in ("A", "B"):
            if len(mi.team(side)) < need:
                problems.append(f"**{mi.team_name(side)}** needs at least {need} player(s) in the lobby "
                                f"(has {len(mi.team(side))})")
        if problems:
            return problems
        await store.update_fixture(self.db, fx["fixture_id"], status="live", match_id=mi.match_id,
                                   channel_id=str(mi.channel.id))
        names = f"**{mi.team_name('A')} v {mi.team_name('B')}**"
        await self.announce(mi.guild, t, f"🏏 Match `#{fx['number']}` {names} is **under way** in <#{mi.channel.id}>!",
                            match_id=mi.match_id)
        return []

    def match_summary(self, mi) -> dict:
        info = mi.tournament
        ids = info["teams"]
        teams, first = {}, {}
        for side in ("A", "B"):
            cards = [c for _, c in sorted(mi.innings_scorecards.items()) if c.get("team") == side]
            teams[ids[side]] = {"runs": sum(c.get("runs", 0) for c in cards), "balls": sum(c.get("balls", 0) for c in cards),
                                "wickets": sum(c.get("wickets", 0) for c in cards), "fi": cards[0]["runs"] if cards else None}
            first[side] = cards[0]["runs"] if cards else None
        leader = None
        if first["A"] is not None and first["B"] is not None and first["A"] != first["B"]:
            leader = ids["A"] if first["A"] > first["B"] else ids["B"]
        potm_name = None
        if mi.potm:
            potm_name = next((r["name"] for c in mi.innings_scorecards.values() for r in c.get("batting", []) + c.get("bowling", [])
                              if r["id"] == str(mi.potm)), None)
        return {"teams": teams, "fi_leader": leader, "innings_win": (mi.result or {}).get("reason") == "innings_victory",
                "potm": str(mi.potm) if mi.potm else None, "potm_name": potm_name}

    async def on_match_finished(self, mi):
        """Called by the match engine after a result is recorded. Never raises."""
        info = getattr(mi, "tournament", None)
        if not info:
            return
        try:
            res = mi.result or {}
            if res.get("type") == "abandoned":
                await self.on_match_abandoned(mi)
                return
            t = await store.get(self.db, info["id"])
            fx = await store.get_fixture(self.db, info["fixture_id"])
            if t is None or fx is None or fx["match_id"] != mi.match_id or t["status"] != "ongoing":
                return
            rtype = {"win": "win", "draw": "draw", "tie": "tie"}.get(res.get("type"))
            if rtype is None:
                return
            winner = info["teams"].get(res.get("winner")) if rtype == "win" else None
            text = mi.game.result_text() if mi.game is not None else None
            result = await actions.apply_result(self.db, t, fx, rtype, winner, text, self.match_summary(mi), mi.match_id)
            await store.add_audit(self.db, t["tournament_id"], self.bot.user.id if self.bot.user else 0, "bot",
                                  "match.result", actions._plain(result.message), "bot")
            fresh = await store.get(self.db, t["tournament_id"])
            await self.apply_effects(mi.guild, fresh or t, result)
            if fresh is not None:
                await self.refresh_cache(fresh)
                await self._post_table_update(mi, fresh, fx)
        except Exception as e:
            logger.exception("recording tournament result failed for match %s", mi.match_id)
            reporter = getattr(self.bot, "report_error", None)
            if reporter:
                try:
                    await reporter(e, where=f"tournament result for match {mi.match_id}")
                except Exception:
                    pass

    async def _post_table_update(self, mi, t: dict, fx: dict):
        """A short 'what this means' line in the match channel."""
        try:
            if fx["stage"] == "group":
                tables = (t.get("cache") or {}).get("standings") or {}
                rows = tables.get(fx["group_name"], [])
                top = " • ".join(f"{r['rank']}. {r['name']} ({r['points']})" for r in rows[:4])
                if top:
                    await mi.channel.send(embed=theme.embed(
                        f"🏆 {t['name']} — table" + (f" (Pool {fx['group_name']})" if fx["group_name"] else ""),
                        f"{top}\n-# Full table: `{P}tour table`", theme.GOLD))
            else:
                fresh = await store.get_fixture(self.db, fx["fixture_id"])
                if fresh and fresh["winner_team_id"]:
                    team = await store.get_team(self.db, fresh["winner_team_id"])
                    msg = (f"**{team['name']}** are the champions! 🏆" if fx["stage"] == "final"
                           else f"**{team['name']}** go through to the next round.")
                    await mi.channel.send(embed=theme.embed(f"🏆 {t['name']}", msg, theme.GOLD))
        except Exception:
            pass

    async def on_match_abandoned(self, mi):
        info = getattr(mi, "tournament", None)
        if not info:
            return
        try:
            fx = await store.get_fixture(self.db, info["fixture_id"])
            if fx is not None and fx["status"] == "live" and fx["match_id"] == mi.match_id:
                await store.update_fixture(self.db, fx["fixture_id"], status="scheduled", match_id=None, channel_id=None)
                t = await store.get(self.db, info["id"])
                if t is not None:
                    await self.announce(mi.guild, t, f"🍂 Match `#{fx['number']}` was abandoned and will be replayed.")
        except Exception:
            logger.exception("could not release fixture after abandoned match %s", mi.match_id)

    # ───────────────────────────────────────────────────────── website bridge
    async def refresh_guild_meta(self, guild):
        """Publish the server's roles and channels so the website can show pickers."""
        if guild is None:
            return
        roles = []
        for r in sorted(getattr(guild, "roles", []) or [], key=lambda r: -getattr(r, "position", 0)):
            if getattr(r, "is_default", lambda: False)() or getattr(r, "managed", False):
                continue
            color = getattr(getattr(r, "color", None), "value", 0) or 0
            roles.append({"id": str(r.id), "name": r.name, "color": f"{color:06x}" if color else ""})
        channels = []
        for ch in getattr(guild, "text_channels", None) or getattr(guild, "channels", []) or []:
            channels.append({"id": str(ch.id), "name": ch.name})
        icon = getattr(getattr(guild, "icon", None), "url", None) or ""
        await self.db.execute(
            "INSERT INTO guild_meta (guild_id, name, icon, roles, channels, member_count, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET name = excluded.name, icon = excluded.icon, roles = excluded.roles, "
            "channels = excluded.channels, member_count = excluded.member_count, updated_at = excluded.updated_at",
            [str(guild.id), guild.name, str(icon), json.dumps(roles[:250]), json.dumps(channels[:250]),
             int(getattr(guild, "member_count", 0) or 0), now()])

    async def publish_schema(self):
        info = {"prefix": config.prefix, "bot_name": config.bot_name, "schema": schema.public_schema(),
                "leaderboards": {k: v[0] for k, v in logic.LEADERBOARDS.items()},
                "economy": {k: {"kind": v[0], "min": v[1], "max": v[2], "help": v[3]} for k, v in eco_settings.EDITABLE.items()}}
        await self._set("tournament.schema", json.dumps(info))

    async def _set(self, key: str, value: str):
        await self.db.execute(
            "INSERT INTO bot_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            [key, value, now()])

    async def process_web_tasks(self, limit: int = 10) -> int:
        """Run actions requested on the website. Returns how many were handled."""
        rows = await self.db.fetch("SELECT * FROM web_tasks WHERE status = 'pending' ORDER BY id LIMIT ?", [limit])
        for task in rows:
            status, message = "done", ""
            try:
                if now() - (task.get("created_at") or 0) > 900:
                    raise TournamentError("This request expired before the bot could run it. Please try again.")
                message = await self._run_task(task)
            except TournamentError as e:
                status, message = "error", str(e)
            except Exception as e:
                logger.exception("web task %s failed", task.get("id"))
                status, message = "error", "Something went wrong while running that. The bot owner has been told."
                reporter = getattr(self.bot, "report_error", None)
                if reporter:
                    try:
                        await reporter(e, where=f"web task {task.get('id')} ({task.get('kind')})")
                    except Exception:
                        pass
            await self.db.execute("UPDATE web_tasks SET status = ?, result = ?, done_at = ? WHERE id = ?",
                                  [status, actions._plain(message)[:1500], now(), task["id"]])
        return len(rows)

    async def _run_task(self, task: dict) -> str:
        kind = task.get("kind") or ""
        try:
            payload = json.loads(task.get("payload") or "{}")
        except Exception:
            payload = {}
        actor_id = int(task["actor_id"])
        user_stub = types.SimpleNamespace(id=actor_id, name=task.get("actor_name") or str(actor_id))
        is_owner = await self.bot.is_owner(user_stub)

        if kind.startswith("owner."):
            if not is_owner:
                raise TournamentError("Only the bot owner can do that.")
            return await self._owner_task(kind, payload, actor_id)

        guild_id = task.get("guild_id")
        t = None
        if kind == "tournament":
            t = await store.get(self.db, task.get("tournament_id"))
            if t is None:
                raise TournamentError("That tournament no longer exists.")
            guild_id = t["guild_id"]
        guild = self.bot.get_guild(int(guild_id)) if guild_id else None
        if guild is None:
            raise TournamentError("The bot isn't in that server.")
        access = getattr(self.bot, "access", None)
        if access is not None and not access.is_allowed(guild.id) and not is_owner:
            raise TournamentError("That server isn't authorised to use the bot.")
        member = await self._member(guild, actor_id)
        if member is None:
            raise TournamentError("You're not a member of that server.")
        if kind == "tournament.create":
            t = await self.create(guild, member, payload.get("name"), source="web")
            return f"Created {t['name']}|{t['tournament_id']}"
        if kind == "tournament":
            action = str(payload.get("action") or "")
            if action not in actions.ACTIONS:
                raise TournamentError("Unknown action.")
            result = await self.run(guild, t, member, action, payload.get("params") or {}, source="web")
            return result.message
        raise TournamentError("Unknown request.")

    async def _owner_task(self, kind: str, payload: dict, actor_id: int) -> str:
        if kind == "owner.server":
            access = self.bot.access
            await access.load()
            gid = str(payload.get("guild_id") or "")
            if not gid.isdigit():
                raise TournamentError("Give a server ID.")
            op = payload.get("op")
            g = self.bot.get_guild(int(gid))
            if op == "allow":
                days = max(0, int(payload.get("days") or 0))
                await access.allow(gid, g.name if g else "", days, str(payload.get("note") or "")[:200], by=actor_id)
                return f"Server {gid} is allowed" + (f" for {days} days." if days else " with no time limit.")
            if op == "revoke":
                await access.revoke(gid, str(payload.get("note") or "")[:200])
                return f"Server {gid} can no longer use the bot."
            if op == "extend":
                row = await access.extend(gid, int(payload.get("days") or 0))
                if row is None:
                    raise TournamentError("That server isn't on the list yet — allow it first.")
                return f"Server {gid} extended."
            if op == "forget":
                await access.forget(gid)
                return f"Server {gid} removed from the list."
            raise TournamentError("Unknown server action.")
        if kind == "owner.coins":
            uid = str(payload.get("user_id") or "")
            if not uid.isdigit():
                raise TournamentError("Give a user ID.")
            try:
                amount = int(payload.get("amount"))
            except (TypeError, ValueError):
                raise TournamentError("The amount must be a whole number.")
            if not 0 <= amount <= 1_000_000_000:
                raise TournamentError("The amount must be between 0 and 1,000,000,000.")
            op = payload.get("op")
            note = str(payload.get("note") or "")[:120]
            user = self.bot.get_user(int(uid))
            await profiles.ensure_profile_id(self.db, uid, user.name if user else "")
            reason = f"owner {op} by {actor_id} (website)" + (f": {note}" if note else "")
            if op == "set":
                old, new = await profiles.set_coins(self.db, uid, amount, reason)
            elif op in ("add", "remove"):
                old, new = await profiles.adjust_coins(self.db, uid, amount if op == "add" else -amount, reason)
            else:
                raise TournamentError("Unknown coin action.")
            return f"Balance changed from {old:,} to {new:,}."
        if kind == "owner.eco":
            try:
                value = await eco_settings.set_value(self.db, str(payload.get("key") or ""), payload.get("value"))
            except ValueError as e:
                raise TournamentError(str(e))
            return f"{payload.get('key')} is now {value}."
        raise TournamentError("Unknown request.")

    # ───────────────────────────────────────────────────────── background
    async def housekeeping(self):
        """Reminders, heartbeat, whitelist + economy refresh, roles/channels for the website."""
        await self._set("bot.heartbeat", str(now()))
        guilds = list(getattr(self.bot, "guilds", []) or [])
        await self._set("bot.guilds", json.dumps([str(g.id) for g in guilds]))
        await self._set("bot.guild_names", json.dumps(
            [{"id": str(g.id), "name": g.name, "members": int(getattr(g, "member_count", 0) or 0)} for g in guilds][:500]))
        access = getattr(self.bot, "access", None)
        if access is not None:
            await access.load()
        await eco_settings.load(self.db)
        full = now() - self._last_meta > 600
        for t in await store.list_active(self.db):
            guild = self.bot.get_guild(int(t["guild_id"]))
            if guild is None:
                continue
            if t["status"] == "ongoing":
                await self._reminders(guild, t)
            if full or guild.id in self._meta_dirty:
                await self.refresh_guild_meta(guild)
                await self.sync_role_staff(guild, t)
                if t["guild_name"] != guild.name:
                    await store.update(self.db, t["tournament_id"], guild_name=guild.name)
        if full:
            self._last_meta = now()
        self._meta_dirty.clear()
        await self.db.execute("DELETE FROM web_sessions WHERE expires_at < ?", [now()])
        await self.db.execute("DELETE FROM web_tasks WHERE created_at < ?", [now() - 7 * 86400])

    async def _reminders(self, guild, t: dict):
        minutes = t["settings"].get("reminder_minutes") or 0
        if not minutes:
            return
        ts = now()
        teams = None
        for fx in await store.list_fixtures(self.db, t["tournament_id"]):
            when = fx.get("scheduled_at") or 0
            if fx["status"] != "scheduled" or not when or fx.get("reminded"):
                continue
            if not (when - minutes * 60 <= ts <= when + 3600):
                continue
            teams = teams or {x["team_id"]: x for x in await store.list_teams(self.db, t["tournament_id"])}
            a, b = teams.get(fx["team_a_id"]), teams.get(fx["team_b_id"])
            if a is None or b is None:
                continue
            pings = []
            for team in (a, b):
                if team.get("role_id"):
                    pings.append(f"<@&{team['role_id']}>")
                elif team.get("captain_id"):
                    pings.append(f"<@{team['captain_id']}>")
            channel = self._channel(guild, t, "announce_channel")
            await store.update_fixture(self.db, fx["fixture_id"], reminded=1)
            if channel is None:
                continue
            try:
                await channel.send(
                    content=" ".join(pings) or None,
                    embed=theme.embed(f"⏰ {t['name']} — match #{fx['number']}",
                                      f"**{a['name']} v {b['name']}** starts <t:{when}:R> (<t:{when}:t>).\n"
                                      f"A captain opens the lobby with `{P}create`, then `{P}tm {fx['number']}`.", theme.GOLD))
            except discord.HTTPException:
                pass

    def mark_dirty(self, guild):
        if guild is not None:
            self._meta_dirty.add(guild.id)

    def start(self):
        """Start the background loops (called once the bot is ready)."""
        if self._tasks:
            return
        poll = float(config.tournament.get("web_poll_seconds") or 0)
        house = float(config.tournament.get("housekeeping_seconds") or 0)

        async def loop(fn, every, name):
            while not self.bot.is_closed():
                try:
                    await fn()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("%s loop error: %r", name, e)
                await asyncio.sleep(every)

        if poll > 0:
            self._tasks.append(asyncio.create_task(loop(self.process_web_tasks, poll, "web tasks")))
        if house > 0:
            self._tasks.append(asyncio.create_task(loop(self.housekeeping, house, "housekeeping")))

    def stop(self):
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()


def install(bot) -> TournamentManager:
    manager = TournamentManager(bot)
    bot.tournaments = manager

    for event in ("on_guild_role_create", "on_guild_role_delete", "on_guild_channel_create", "on_guild_channel_delete"):
        async def _dirty(obj, _m=manager):
            _m.mark_dirty(getattr(obj, "guild", None))
        bot.add_listener(_dirty, event)

    async def _updated(before, after, _m=manager):
        _m.mark_dirty(getattr(after, "guild", None))
    bot.add_listener(_updated, "on_guild_role_update")
    bot.add_listener(_updated, "on_guild_channel_update")
    return manager
