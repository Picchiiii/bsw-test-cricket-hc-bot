"""Squad commands: substitutes (`sub`), representatives (`setrep`) and CPU players (`cpu`).

Substitutes
    `sub <out> <in> [rep]` — host or the captain of <out>'s team. <in> must be in that team's **squad**:
    in a tournament match the team's registered roster; in a friendly the team's bench (`join sub A|B`).
    Works in the lobby and (unless switched off) during the match: the substitute takes over the
    outgoing player's place in the XI — at the crease, in the over, and the captaincy if they had it.

Representatives
    `join rep` joins as a rep (R). The host can also mark/unmark someone in the lobby with `setrep`.
    Reps bat with a run cap (`settings rep_run_cap`) and can't bowl unless `settings rep_can_bowl 1`.

CPU players
    `cpu add [A|B] [count]`, `cpu remove <name|all>`, `cpu list` — host, friendly lobbies only.
"""
import logging

from discord.ext import commands

from core.config import config
from core.backend.cpu import is_cpu, new_cpu
from core.backend.instance import join_segregate_player, leave_segregate_player, player_busy_elsewhere
from core.backend.lobby import lobby_embed
from core.backend.resolve import find_member
from core.ui import theme

logger = logging.getLogger(__name__)
P = config.prefix
SIDE_WORDS = {"a": "A", "1": "A", "b": "B", "2": "B"}


def _norm(s) -> str:
    return str(s or "").strip().lower().lstrip("@")


async def resolve_person(mi, guild, text):
    """A player / bench player / CPU of this match by mention, ID or name, else any server member."""
    if text is None:
        return None
    if hasattr(text, "id") and hasattr(text, "name"):
        return text
    pool = list(mi.players) + [p for side in ("A", "B") for p in mi.bench.get(side, [])]
    pool += [s["member"] for s in mi.subbed_out if s.get("member") is not None]
    from core.backend.resolve import parse_id
    uid = parse_id(text)
    want = _norm(text)
    for p in pool:
        if uid is not None and p.id == uid:
            return p
        if want and want in (_norm(p.name), _norm(getattr(p, "display_name", ""))):
            return p
    if want.isdigit() and len(want) <= 2:
        for p in mi.players:
            if is_cpu(p) and p.id == int(want):
                return p
    return await find_member(guild, text)


def squad(bot: commands.Bot):

    def get_match(ctx):
        return ctx.bot.active_matches.get(ctx.channel.id)

    def persist(mi):
        store = getattr(bot, "store", None)
        if store is not None:
            store.schedule(mi, force=True)

    # ─────────────────────────────────────────────────────────── substitutes
    @bot.command(name="sub", aliases=["substitute", "subs"],
                 help="Host/captain: bring a squad player in for someone. sub <out> <in> [rep]")
    @commands.guild_only()
    async def substitute(ctx: commands.Context, out_text=None, in_text=None, *flags):
        mi = get_match(ctx)
        if not mi:
            await ctx.send(f"No active match in this channel. Create one with `{P}create`.")
            return
        if out_text is None or in_text is None:
            await ctx.send(embed=sub_help(mi))
            return
        out = await resolve_person(mi, ctx.guild, out_text)
        sub = await resolve_person(mi, ctx.guild, in_text)
        as_rep = any(_norm(f) in ("r", "rep", "representative") for f in flags)
        problem = await sub_problem(ctx, mi, out, sub)
        if problem:
            await ctx.send(problem)
            return
        side = mi.side_of(out)
        if not mi.game_started:
            # lobby: a straight swap in the team list
            team = mi.team(side)
            team[team.index(out)] = sub
            mi.players[mi.players.index(out)] = sub
            if mi.captain(side) == out:
                if side == "A":
                    mi.teamA_captain = sub
                else:
                    mi.teamB_captain = sub
            if out in mi.reps:
                mi.reps.remove(out)
            if as_rep and sub not in mi.reps:
                mi.reps.append(sub)
            for members in mi.bench.values():
                if sub in members:
                    members.remove(sub)
            if is_cpu(out):
                mi.cpu_names.pop(str(out.id), None)
            mi.substitutions.append({"side": side, "out_id": out.id, "out_name": out.name, "in_id": sub.id,
                                     "in_name": sub.name, "rep": as_rep, "innings": 0, "over": "0.0", "day": 0,
                                     "phase": "lobby", "by": ctx.author.name})
            mi.touch()
            persist(mi)
            await ctx.send(f"🔁 **{sub.name}**{' (R)' if as_rep else ''} comes in for **{out.name}** "
                           f"in **{mi.team_name(side)}**.")
            return
        game = mi.game
        async with mi.lock:
            reason = game.substitution_problem(out, sub)
            if reason:
                await ctx.send(reason)
                return
            entry = game.apply_substitution(out, sub, as_rep, by=ctx.author)
        e = theme.embed("🔁 Substitution", (
            f"**{sub.name}**{' (R)' if as_rep else ''} replaces **{out.name}** for **{mi.team_name(side)}** "
            f"(innings {entry['innings']}, over {entry['over']})."), theme.BLUE)
        notes = []
        if mi.curr_batsman == sub:
            notes.append(f"{sub.mention} takes over at the crease — {out.name} is *retired (substituted)*.")
        if entry.get("bowler_now"):
            if mi.curr_bowler == sub:
                notes.append(f"{sub.mention} finishes the over.")
            else:
                notes.append(f"Reps can't bowl, so **{entry['bowler_now']}** finishes the over.")
        if mi.captain(side) == sub:
            notes.append(f"{sub.name} is now captain of {mi.team_name(side)}.")
        if notes:
            e.add_field(name="What changes", value="\n".join(notes), inline=False)
        used = mi.subs_used(side)
        cap = mi.match_settings.get("max_subs_per_team") or 0
        e.set_footer(text=theme.footer_text(f"Substitutions used by {mi.team_name(side)}: {used}" + (f"/{cap}" if cap else "")))
        await ctx.send(embed=e)
        if mi.game and mi.phase == "innings" and not (mi.paused or mi.stumps_called):
            await mi.game.refresh_scorecard()

    async def sub_problem(ctx, mi, out, sub) -> str | None:
        if out is None:
            return "I couldn't find the player going out. Mention them or type their name."
        if sub is None:
            return "I couldn't find the substitute. Mention them or type their name."
        side = mi.side_of(out)
        if side is None:
            return f"**{out.name}** isn't playing in this match."
        info = getattr(mi, "tournament", None)
        allowed = ctx.author == mi.host or ctx.author == mi.captain(side)
        if info and not allowed:
            allowed = ctx.author.id in (info.get("captains") or {}).get(side, [])
        if not allowed:
            return f"Only the host or **{mi.team_name(side)}**'s captain can make substitutions."
        if sub == out:
            return "That's the same player."
        if sub in mi.players:
            return f"**{sub.name}** is already playing in this match."
        if any(s.get("member") == sub for s in mi.subbed_out):
            return f"**{sub.name}** was substituted out of this match and can't come back."
        if getattr(sub, "bot", False):
            return "Bots can't play."
        if mi.phase == "finished":
            return "The match is over."
        if mi.game_started:
            if not mi.match_settings.get("subs_during_match", config.game.get("subs_during_match", True)):
                return "Substitutions are switched off once the match has started."
            cap = mi.match_settings.get("max_subs_per_team") or 0
            if cap and mi.subs_used(side) >= cap:
                return f"**{mi.team_name(side)}** has used all {cap} substitution(s)."
        # the squad rule: friendlies — anyone who isn't in the match; tournaments — the team's registered squad,
        # or (if the tournament allows it) anyone except players registered with the opponent
        if info:
            await ctx.bot.tournaments.refresh_rosters(mi)
            other = mi.other(side)
            if sub.id in info["rosters"][other]:
                return (f"**{sub.name}** is registered with **{mi.team_name(other)}** and can't play for "
                        f"**{mi.team_name(side)}**.")
            if sub.id not in info["rosters"][side]:
                if not await ctx.bot.tournaments.outside_subs_allowed(mi):
                    return (f"**{sub.name}** isn't in **{mi.team_name(side)}**'s squad (tournament roster), so they "
                            f"can't come on as a substitute. A tournament organiser can allow substitutes from "
                            f"outside the squad with `{P}tour subs on`.")
                guests = info.setdefault("guests", {"A": [], "B": []})
                if sub.id not in guests[side]:
                    guests[side].append(sub.id)
        other = player_busy_elsewhere(ctx.bot, sub, ctx.channel.id)
        if other:
            return f"**{sub.name}** is playing in another match in <#{other}>."
        return None

    def sub_help(mi):
        p = P
        info = getattr(mi, "tournament", None)
        if info:
            squad_txt = ("on the team's registered tournament squad"
                         + (" — or, because this tournament allows it, anyone outside the squad (not the opponent's players)"
                            if info.get("outside_subs") else f" (organisers: `{p}tour subs on` allows outsiders)"))
        else:
            squad_txt = (f"anyone who isn't already in this match (players can also wait on the bench with "
                         f"`{p}join sub A|B` so captains can see who's available)")
        e = theme.embed("🔁 Substitutes", (
            f"`{p}sub <player out> <player in>` — add `rep` to bring them in as a rep (R).\n"
            f"Who: the host or that team's captain.\n"
            f"Who can come in: {squad_txt}.\n"
            "When play resumes (next day or after a pause) the bot shows both squads first, so you can replace "
            "anyone who isn't there today.\n"
            "During a match the substitute takes the outgoing player's place at once — at the crease, in the over "
            "and as captain if needed. The outgoing player's figures stay on the scorecard."), theme.BLUE)
        bench = [f"**{mi.team_name(s)}**: {', '.join(x.name for x in mi.bench[s])}" for s in ("A", "B") if mi.bench.get(s)]
        if bench:
            e.add_field(name="Bench", value=theme.truncate("\n".join(bench)), inline=False)
        done = [f"{s['in_name']} for {s['out_name']} ({mi.team_name(s['side'])}"
                + (f", inns {s['innings']} ov {s['over']})" if s["phase"] == "match" else ", lobby)")
                for s in mi.substitutions]
        if done:
            e.add_field(name="Substitutions made", value=theme.truncate("\n".join(done)), inline=False)
        return e

    # ─────────────────────────────────────────────────────────── representatives
    @bot.command(name="setrep", aliases=["rep", "markrep"], help="Host: mark a player as a rep (R) or not. setrep <player> [on|off]")
    @commands.guild_only()
    async def set_rep(ctx: commands.Context, who=None, state: str = None):
        mi = get_match(ctx)
        if not mi:
            await ctx.send("No active match in this channel.")
            return
        if who is None:
            cap = mi.match_settings.get("rep_run_cap") or 0
            reps = ", ".join(p.name for p in mi.reps) or "none"
            await ctx.send(embed=theme.embed("🎗️ Representatives (R)", (
                f"Reps in this match: **{reps}**\n"
                f"Run cap: **{cap or 'none'}** • Reps bowl: **{'yes' if mi.match_settings.get('rep_can_bowl') else 'no'}** • "
                f"Reaching the cap: **{'retired out (wicket)' if mi.match_settings.get('rep_retire_counts_wicket', True) else 'retired not out'}**\n"
                f"Join as a rep with `{P}join rep`. Host: `{P}setrep <player> on|off`, `{P}settings rep_run_cap <n>`."),
                theme.BLUE))
            return
        if ctx.author != mi.host:
            await ctx.send("Only the host can change who is a rep.")
            return
        if mi.game_started:
            await ctx.send("Reps can only be changed in the lobby, before the match starts.")
            return
        member = await resolve_person(mi, ctx.guild, who)
        if member is None or member not in mi.players:
            await ctx.send("That player isn't in this match.")
            return
        turn_on = member not in mi.reps if state is None else _norm(state) in ("1", "on", "yes", "true", "rep")
        if turn_on and member not in mi.reps:
            cap = mi.match_settings.get("max_reps_per_team") or 0
            side = mi.side_of(member)
            if cap and len(mi.reps_in(side)) >= cap:
                await ctx.send(f"**{mi.team_name(side)}** already has {cap} rep(s).")
                return
            mi.reps.append(member)
        elif not turn_on and member in mi.reps:
            mi.reps.remove(member)
        persist(mi)
        await ctx.send(f"🎗️ **{member.name}** is {'now a rep (R)' if member in mi.reps else 'no longer a rep'}.")

    # ─────────────────────────────────────────────────────────── CPU players
    @bot.command(name="cpu", aliases=["cpus", "ai"],
                 help="Host: add or remove CPU players in a friendly lobby. cpu add [A|B] [count] • cpu remove <name|all>")
    @commands.guild_only()
    async def cpu(ctx: commands.Context, *args):
        mi = get_match(ctx)
        if args:
            action = _norm(args[0])
            if action in ("add", "+", "new"):
                return await cpu_add(ctx, *args[1:])
            if action in ("remove", "rm", "kick", "-", "del", "delete"):
                return await cpu_remove(ctx, *args[1:])
        names = ", ".join(p.name for p in mi.players if is_cpu(p)) if mi else ""
        await ctx.send(embed=theme.embed("🤖 CPU players", (
            f"`{P}cpu add [A|B] [count]` — add computer players to a friendly lobby (host)\n"
            f"`{P}cpu remove <name|all>` — take them out again\n"
            "CPUs pick their own numbers, never bowl no-balls and make captain decisions instantly. "
            + ("Matches with a CPU don't count for stats or coins." if not config.game.get("cpu_matches_count")
               else "Only the human players get stats and coins.")
            + (f"\nIn this lobby: **{names}**" if names else "")), theme.BLUE))

    async def cpu_guard(ctx, mi) -> bool:
        if not mi:
            await ctx.send(f"No active match in this channel. Create one with `{P}create`.")
            return False
        if not config.game.get("cpu_enabled", True):
            await ctx.send("CPU players are switched off on this bot.")
            return False
        if ctx.author != mi.host:
            await ctx.send("Only the host can add or remove CPU players.")
            return False
        if mi.game_started:
            await ctx.send("CPU players can only be changed in the lobby.")
            return False
        if getattr(mi, "tournament", None):
            await ctx.send("CPU players can't take part in tournament matches.")
            return False
        return True

    async def cpu_add(ctx, *args):
        mi = get_match(ctx)
        if not await cpu_guard(ctx, mi):
            return
        side, count = None, 1
        for a in args:
            t = _norm(a)
            if t in ("a", "b") and side is None:
                side = t.upper()
            elif t.isdigit():
                count = int(t)
        count = max(1, min(count, 11))
        added = []
        for _ in range(count):
            if len(mi.players) >= config.game["max_players"]:
                break
            bot_player = new_cpu(mi)
            if bot_player is None:
                break
            mi.players.append(bot_player)
            if side is None:
                join_segregate_player(mi, bot_player)
            else:
                mi.team(side).append(bot_player)
                if mi.captain(side) is None:
                    if side == "A":
                        mi.teamA_captain = bot_player
                    else:
                        mi.teamB_captain = bot_player
            added.append(bot_player)
        if not added:
            await ctx.send(f"The lobby is full ({config.game['max_players']} players).")
            return
        mi.touch()
        persist(mi)
        where = f" to **{mi.team_name(side)}**" if side else ""
        await ctx.send(f"🤖 Added {', '.join(f'**{b.name}**' for b in added)}{where}.", embed=lobby_embed(mi))

    async def cpu_remove(ctx, *args):
        mi = get_match(ctx)
        if not await cpu_guard(ctx, mi):
            return
        cpus = [p for p in mi.players if is_cpu(p)]
        if not cpus:
            await ctx.send("There are no CPU players in this lobby.")
            return
        want = " ".join(args).strip()
        if not want or _norm(want) == "all":
            gone = cpus
        else:
            target = await resolve_person(mi, ctx.guild, want)
            gone = [target] if target is not None and is_cpu(target) else []
        if not gone:
            await ctx.send("No CPU player by that name. Use `cpu remove all` to remove every CPU.")
            return
        for b in gone:
            mi.players.remove(b)
            leave_segregate_player(mi, b)
        mi.touch()
        persist(mi)
        await ctx.send(f"🤖 Removed {', '.join(f'**{b.name}**' for b in gone)}.")
