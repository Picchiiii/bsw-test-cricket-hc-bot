import json
import discord
from discord.ext import commands
import logging
import random
from core.backend.views.toss_view import TossView
from core.backend.game import Game
from core.backend.permissions import can_control
from core.config import config
from core.ui import theme
from core.ui.cards import innings_card_embed, InningsView
from core.backend.cpu import is_cpu

logger = logging.getLogger(__name__)


def start_problems(mi) -> list[str]:
    """Rep / CPU rules checked when the host starts the match."""
    problems = []
    s = mi.match_settings
    for side in ("A", "B"):
        team = mi.team(side)
        if not team:
            continue
        if not s.get("rep_can_bowl") and all(p in mi.reps for p in team):
            problems.append(f"**{mi.team_name(side)}** has only reps, and reps can't bowl — "
                            f"it needs at least one regular player (or `{config.prefix}settings rep_can_bowl 1`)")
        cap = s.get("max_reps_per_team") or 0
        if cap and len(mi.reps_in(side)) > cap:
            problems.append(f"**{mi.team_name(side)}** has {len(mi.reps_in(side))} reps (the limit is {cap})")
        if all(is_cpu(p) for p in team) and all(is_cpu(p) for p in mi.team(mi.other(side))):
            problems.append("at least one human player is needed")
    return problems


def match(bot: commands.Bot):

    def get_match(ctx):
        return ctx.bot.active_matches.get(ctx.channel.id)

    @bot.command(name="toss", help="Conduct a toss to decide which team will bat or bowl first.", aliases=["t"])
    @commands.guild_only()
    async def toss(ctx: commands.Context):
        match_instance = get_match(ctx)
        if not match_instance:
            await ctx.send("No active match in this channel.")
            return
        mi = match_instance
        if ctx.author.id != mi.host.id:
            await ctx.send("Only the host can conduct the toss.")
            return
        if mi.game_started:
            await ctx.send("The match has already started.")
            return
        if not mi.teamA or not mi.teamB or not mi.teamA_captain or not mi.teamB_captain:
            await ctx.send("Both teams need at least one player (and a captain) before the toss.")
            return
        mi.toss_winner = None
        mi.batting_turn = mi.bowling_turn = None
        user: discord.Member = random.choice([mi.teamA_captain, mi.teamB_captain])
        toss_view = TossView(mi, None, user)
        team = mi.team_settings['Team A name'] if user == mi.teamA_captain else mi.team_settings['Team B name']
        e = discord.Embed(title="🪙 Toss time!",
                          description=f"**{team}** captain {user.mention}, call it — **Heads** or **Tails**?",
                          color=theme.GOLD)
        toss_message = await ctx.send(content=user.mention, embed=e, view=toss_view)
        toss_view.message = toss_message
        if is_cpu(user):
            await toss_view.auto_call()

    @bot.command(name="start", help="Start the ongoing match in the channel.", aliases=["s"])
    @commands.guild_only()
    async def start_match(ctx: commands.Context):
        match_instance = get_match(ctx)
        if not match_instance:
            await ctx.send("No active match in this channel.")
            return
        mi = match_instance
        if ctx.author.id != mi.host.id:
            await ctx.send("Only the host can start the match.")
            return
        if mi.game_started:
            await ctx.send("The match has already started.")
            return
        problems = []
        if not mi.teamA or not mi.teamB:
            problems.append("both teams need at least one player")
        if not mi.match_settings['overs']:
            problems.append(f"set the overs per day with `{config.prefix}so <overs>`")
        if not mi.match_settings['days']:
            problems.append(f"set the number of days with `{config.prefix}sd <days>`")
        if not mi.toss_winner or not mi.batting_turn:
            problems.append(f"do the toss with `{config.prefix}toss` and choose bat/bowl")
        problems += start_problems(mi)
        if problems:
            await ctx.send("Can't start yet: " + "; ".join(problems) + ".")
            return
        if getattr(mi, "tournament", None):
            problems = await ctx.bot.tournaments.before_start(mi)
            if problems:
                await ctx.send("Can't start the tournament match yet: " + "; ".join(problems) + ".")
                return
        mi.lobby_lock = True
        await ctx.send(f"Starting match! {theme.STADIUM}")
        game = Game(ctx, mi)
        await game.start_game()

    @bot.command(name="pause", help="Host: pause the match after the current ball.")
    @commands.guild_only()
    async def pause_match(ctx: commands.Context):
        mi = get_match(ctx)
        if not mi or not mi.game_started:
            await ctx.send("There is no match in play here.")
            return
        if ctx.author != mi.host:
            await ctx.send("Only the host can pause the match.")
            return
        if mi.paused or mi.stumps_called:
            await ctx.send("The match is already paused.")
            return
        mi.paused = True
        mi.pause_reason = "host"
        mi.interrupt.set()
        if mi.game:
            mi.game.persist(force=True)
        await ctx.send(f"⏸️ Match paused. Use `{config.prefix}resume` to continue — it's saved, so this can wait for days.")

    @bot.command(name="resume", aliases=["r", "nextday", "nd", "continue"],
                 help="Host/captain: start the next day after stumps, or resume a paused match.")
    @commands.guild_only()
    async def resume_match(ctx: commands.Context):
        mi = get_match(ctx)
        if not mi or not mi.game_started or mi.game is None:
            await ctx.send("There is no match in play here.")
            return
        if not can_control(mi, ctx.author):
            await ctx.send("Only the host or a captain can resume the match.")
            return
        if mi.squad_check_view is not None and not (mi.paused or mi.stumps_called):
            await mi.squad_check_view.finish(ctx.author)
            await ctx.send("▶️ Play starts now.")
            return
        if not (mi.paused or mi.stumps_called):
            if mi.task is None or mi.task.done():
                mi.game.start_task(resume=True)
                await ctx.send("▶️ Restarting the match loop.")
                return
            await ctx.send("Play is already in progress.")
            return
        what = mi.game.resume_play()
        await ctx.send(what or "▶️ Resuming.")

    @bot.command(name="score", aliases=["sb", "live"], help="Re-post the live scoreboard.")
    @commands.guild_only()
    async def score(ctx: commands.Context):
        mi = get_match(ctx)
        if not mi or not mi.game_started or mi.game is None or mi.phase != "innings":
            await ctx.send("There is no innings in progress here.")
            return
        await mi.game.refresh_scorecard(resend=True)

    @bot.command(name="scorecard", aliases=["sc", "card"], help="Full batting & bowling card. Optional: innings number or match ID.")
    @commands.guild_only()
    async def scorecard(ctx: commands.Context, which: str = None):
        mi = get_match(ctx) or getattr(ctx.bot, "recent_matches", {}).get(ctx.channel.id)
        cards = []
        title = ""
        match_id = None
        if which and not which.isdigit() or (which and len(which) > 2):
            # a match id from the database
            store = getattr(ctx.bot, "store", None)
            row = None
            if store is not None:
                row = await store.db.fetchone("SELECT data FROM matches WHERE match_id = ?", [which])
            if not row:
                await ctx.send("I couldn't find a match with that ID.")
                return
            data = json.loads(row["data"])
            cards = data.get("innings", [])
            title = f"**{data['teams']['A']['name']} v/s {data['teams']['B']['name']}**"
            match_id = which
            which = None
        elif mi is not None and mi.game is not None:
            cards = [mi.innings_scorecards[n] for n in sorted(mi.innings_scorecards)]
            if mi.phase == "innings":
                live = mi.game.build_innings_card()
                live["live"] = True
                cards = [c for c in cards if c["innings"] != mi.innings] + [live]
            title = f"**{mi.team_settings['Team A name']} v/s {mi.team_settings['Team B name']}**"
            match_id = mi.match_id
        if not cards:
            await ctx.send("No innings have been played yet.")
            return
        card = cards[-1]
        if which and which.isdigit():
            pick = [c for c in cards if c["innings"] == int(which)]
            if not pick:
                await ctx.send(f"Innings {which} hasn't been played.")
                return
            card = pick[0]
        footer = f"Match ID {match_id}" if match_id else ""
        e = innings_card_embed(card, title, footer)
        url = theme.match_url(match_id)
        if url:
            e.url = url
        view = InningsView(cards, title, footer)
        await ctx.send(embed=e, view=view if view.children else None)

    @bot.command(name="matchsheet", aliases=["sheet", "msheet", "matchjson"],
                 help="Download the public JSON match sheet. Optional: a match ID.")
    @commands.guild_only()
    async def matchsheet(ctx: commands.Context, match_id: str = None):
        from core.backend.match_sheet import build_match_sheet, sheet_from_public, sheet_file
        sheet = None
        mi = None
        if match_id is None:
            mi = get_match(ctx) or getattr(ctx.bot, "recent_matches", {}).get(ctx.channel.id)
            if mi is None or not mi.game_started:
                await ctx.send(f"There's no match here yet. Use `{config.prefix}matchsheet <match id>` for an older match.")
                return
            sheet = getattr(mi, "match_sheet", None) or build_match_sheet(mi)
        else:
            if mi is None:
                for m in list(ctx.bot.active_matches.values()) + list(getattr(ctx.bot, "recent_matches", {}).values()):
                    if m.match_id == match_id and m.game_started:
                        mi = m
                        break
            if mi is not None:
                sheet = getattr(mi, "match_sheet", None) or build_match_sheet(mi)
            else:
                store = getattr(ctx.bot, "store", None)
                row = None
                if store is not None:
                    row = await store.db.fetchone("SELECT data FROM matches WHERE match_id = ?", [match_id])
                if not row or not row.get("data"):
                    await ctx.send("I couldn't find a match with that ID.")
                    return
                sheet = sheet_from_public(json.loads(row["data"]))
        live = sheet.get("status") == "live"
        await ctx.send(content=f"📄 Match sheet for **{sheet['title']}** (`{sheet['match_id']}`)"
                               + (" — the match is still in progress, so this is a snapshot." if live else "."),
                       file=sheet_file(sheet))
