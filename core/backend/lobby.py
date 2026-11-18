"""Lobby rules shared by the text commands and the lobby buttons."""
import time
import discord

from core.config import config
from core.ui import theme
from core.backend.instance import join_segregate_player, leave_segregate_player, player_busy_elsewhere
from core.backend.cpu import is_cpu


def _rep_limit_reason(mi, side) -> str | None:
    cap = mi.match_settings.get("max_reps_per_team") or 0
    if cap and side and len(mi.reps_in(side)) >= cap:
        return f"**{mi.team_name(side)}** already has {cap} rep(s) — that's the limit for this match."
    return None


def _prefer_human_captain(mi, side):
    """A CPU never keeps the captaincy once a human is on the team."""
    cap = mi.captain(side)
    if cap is not None and is_cpu(cap):
        human = next((p for p in mi.team(side) if not is_cpu(p)), None)
        if human is not None:
            if side == "A":
                mi.teamA_captain = human
            else:
                mi.teamB_captain = human


def try_join(mi, user: discord.abc.User, rep: bool = False) -> tuple[bool, str]:
    if user.bot:
        return False, "Bots can't join matches."
    if user in mi.players:
        return False, "You have already joined the game."
    bench_side = mi.bench_side_of(user)
    if mi.game_started:
        return False, "The match has already started. You cannot join now."
    if mi.lobby_lock:
        return False, "The lobby is locked. You cannot join the match at this time."
    if len(mi.players) >= config.game["max_players"]:
        return False, f"The lobby is full ({config.game['max_players']} players)."
    other = player_busy_elsewhere(mi.bot, user, mi.channel.id)
    if other:
        return False, f"You are already in a match in <#{other}>. Leave it first (one match at a time)."
    info = getattr(mi, "tournament", None)
    if info:
        # tournament match: only the two rosters may join, and each player goes to their own team
        side = "A" if user.id in info["rosters"]["A"] else "B" if user.id in info["rosters"]["B"] else None
        if side is None:
            return False, (f"This is **{info['name']}** match #{info['number']} "
                           f"({mi.team_name('A')} v {mi.team_name('B')}). Only players on those two teams can join.")
        if len(mi.team(side)) >= info.get("max_side", 11):
            return False, f"**{mi.team_name(side)}** already has {info.get('max_side', 11)} players in this match."
        if rep and _rep_limit_reason(mi, side):
            return False, _rep_limit_reason(mi, side)
        if bench_side:
            mi.bench[bench_side].remove(user)
        mi.players.append(user)
        mi.team(side).append(user)
        mi.bot.tournaments.seat_captains(mi)
        if rep:
            mi.reps.append(user)
        mi.touch()
        suffix = " as a representative (R)" if rep else ""
        return True, f"**{user.name}** has joined **{mi.team_name(side)}**{suffix}. {theme.TICK}"
    if rep:
        # reps go to the side that join_segregate_player would pick; check that side's rep limit first
        side = "A" if len(mi.teamA) <= len(mi.teamB) else "B"
        if _rep_limit_reason(mi, side):
            return False, _rep_limit_reason(mi, side)
    if bench_side:
        mi.bench[bench_side].remove(user)
    mi.players.append(user)
    join_segregate_player(mi, user)
    if rep:
        mi.reps.append(user)
    side = mi.side_of(user)
    _prefer_human_captain(mi, side)
    mi.touch()
    suffix = " as a representative (R)" if rep else ""
    return True, f"**{user.name}** has joined **{mi.team_name(side)}**{suffix}. {theme.TICK}"


def try_join_bench(mi, user, side: str | None) -> tuple[bool, str]:
    """Join a team's squad as a substitute (bench). Bench players don't play unless brought in with `sub`."""
    p = config.prefix
    if user.bot:
        return False, "Bots can't join matches."
    if getattr(mi, "tournament", None):
        return False, (f"In a tournament match your team's whole roster is the squad — no need to join the bench. "
                       f"A captain can bring you in with `{p}sub @player @you`.")
    if user in mi.players:
        return False, "You are already playing in this match."
    if side not in ("A", "B"):
        return False, f"Say which team's bench to join: `{p}join sub A` or `{p}join sub B`."
    if mi.bench_side_of(user):
        return False, f"You are already on **{mi.team_name(mi.bench_side_of(user))}**'s bench."
    if len(mi.bench[side]) >= 11:
        return False, f"**{mi.team_name(side)}**'s bench is full (11)."
    if mi.phase == "finished":
        return False, "The match is over."
    mi.bench[side].append(user)
    mi.touch()
    return True, (f"🪑 **{user.name}** is on **{mi.team_name(side)}**'s bench as a substitute. "
                  f"The host or captain can bring them in with `{p}sub @player @{user.name}`.")


def try_leave(mi, user: discord.abc.User) -> tuple[bool, str]:
    bench_side = mi.bench_side_of(user)
    if bench_side and user not in mi.players:
        mi.bench[bench_side].remove(user)
        mi.touch()
        return True, f"**{user.name}** has left **{mi.team_name(bench_side)}**'s bench."
    if user not in mi.players:
        return False, "You are not part of the game."
    if user == mi.host:
        return False, "The host cannot leave the match. Change the host before you leave."
    if mi.game_started:
        return False, "You cannot leave the match after it has started."
    if user == mi.teamA_captain or user == mi.teamB_captain:
        return False, "The captain cannot leave the match. Change the captain before you leave."
    mi.players.remove(user)
    leave_segregate_player(mi, user)
    mi.touch()
    return True, f"**{user.name}** has left the game."


def get_player_suffix(player, match_instance):
    suffixes = []
    if player == match_instance.host:
        suffixes.append("(H)")
    if player == match_instance.teamA_captain or player == match_instance.teamB_captain:
        suffixes.append("(C)")
    if player in match_instance.reps:
        suffixes.append("(R)")
    if is_cpu(player):
        suffixes.append("(CPU)")
    if any(s.get("in_id") == player.id for s in getattr(match_instance, "substitutions", [])):
        suffixes.append("(sub)")
    return " " + " ".join(suffixes) if suffixes else ""


def lobby_embed(mi) -> discord.Embed:
    overs = mi.match_settings['overs']
    days = mi.match_settings['days']
    toss = "—"
    if mi.toss_winner:
        side = mi.side_of(mi.toss_winner)
        toss = f"{mi.team_name(side)} won" + (f", chose to **{mi.toss_decision}**" if mi.toss_decision else "")
    status = "🔒 Locked" if mi.lobby_lock else "🟢 Open"
    if mi.game_started:
        status = "🏏 In play"
    info = getattr(mi, "tournament", None)
    badge = (f"🏆 **{info['name']}** — match #{info['number']}\n" if info else "")
    e = discord.Embed(
        title=f"{theme.STADIUM} {getattr(mi.channel, 'name', 'Match')} — Test Match Lobby",
        description=(
            f"{badge}Host: **{mi.host.name}**\n"
            f"Players: **{len(mi.players)}/{config.game['max_players']}** • Lobby: {status}\n"
            f"Overs/day: **{overs if overs else theme.CROSS}** • Days: **{days if days else theme.CROSS}**\n"
            f"Toss: {toss}\n{theme.SEP}"
        ),
        color=theme.CREAM,
    )

    def team_block(team):
        if not team:
            return "```No players yet.```"
        lines = [f"{i}. {p.name}{get_player_suffix(p, mi)}" for i, p in enumerate(team, start=1)]
        return theme.truncate("```\n" + "\n".join(lines) + "\n```")

    e.add_field(name=f"🟡 {mi.team_settings['Team A name']}", value=team_block(mi.teamA), inline=True)
    e.add_field(name=f"🟢 {mi.team_settings['Team B name']}", value=team_block(mi.teamB), inline=True)
    bench = [f"**{mi.team_name(s)}**: {', '.join(p.name for p in mi.bench[s])}" for s in ("A", "B") if mi.bench.get(s)]
    if bench:
        e.add_field(name="🪑 Bench (substitutes)", value=theme.truncate("\n".join(bench)), inline=False)
    cap = mi.match_settings.get("rep_run_cap") or 0
    if mi.reps:
        e.add_field(name="🎗️ Rep rules", value=(f"Reps retire at **{cap}** runs" if cap else "No run cap for reps")
                    + (" • reps **can** bowl" if mi.match_settings.get("rep_can_bowl") else " • reps **can't** bowl"),
                    inline=False)
    p = config.prefix
    steps = []
    if not overs:
        steps.append(f"`{p}so <overs>`")
    if not days:
        steps.append(f"`{p}sd <days>`")
    if not mi.toss_winner:
        steps.append(f"`{p}toss`")
    steps.append(f"`{p}start`")
    e.add_field(name="Next steps (host)", value=" → ".join(steps), inline=False)
    elapsed = int(time.time() - mi.created_at)
    minutes, seconds = divmod(elapsed, 60)
    e.set_footer(text=theme.footer_text(f"Created {minutes} min {seconds} sec ago • (H) host (C) captain (R) rep (sub) substitute"))
    return e
