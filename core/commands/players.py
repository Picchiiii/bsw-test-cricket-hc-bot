import discord
import asyncio
from discord.ext import commands
from core.backend.instance import MatchInstance
import logging
from core.config import config
from core.backend.views.declare_view import DeclarationView, declaration_block_reason
from core.backend.lobby import try_join, try_join_bench, try_leave, lobby_embed
logger = logging.getLogger(__name__)

REP_WORDS = ("r", "rep", "representative")
SUB_WORDS = ("sub", "s", "substitute", "bench")


def players(bot: commands.Bot):

    def persist(mi):
        store = getattr(bot, "store", None)
        if store is not None:
            store.schedule(mi)

    @bot.command(name="join", aliases=["j"],
                 help="Join the lobby. 'join rep' joins as a representative (R); 'join sub A|B' joins a team's bench.")
    @commands.guild_only()
    async def join_match(ctx: commands.Context, *args):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        words = [a.lower() for a in args]
        kind = words[0] if words else None
        sub = kind in SUB_WORDS
        if kind and not sub and (kind not in REP_WORDS or len(words) > 1):
            await ctx.send("Invalid representative type. Please use 'r', 'rep', or 'representative' "
                           f"(or `{config.prefix}join sub A|B` to join a team's bench as a substitute).")
            return
        rep = kind if kind in REP_WORDS else None

        if not match_instance:
            await ctx.send(f"No active match in this channel. Create one with `{config.prefix}create`.")
            return
        if sub:
            side = {"a": "A", "1": "A", "b": "B", "2": "B"}.get(words[1]) if len(words) > 1 else None
            ok, msg = try_join_bench(match_instance, ctx.author, side)
            await ctx.send(msg)
            if ok:
                persist(match_instance)
            return
        if getattr(match_instance, "tournament", None):
            await ctx.bot.tournaments.refresh_rosters(match_instance)
        ok, msg = try_join(match_instance, ctx.author, rep=bool(rep))
        await ctx.send(msg)
        if ok:
            persist(match_instance)

    @bot.command(name="leave", aliases=["l"], help="Leave the lobby (before the match starts).")
    @commands.guild_only()
    async def leave_match(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if not match_instance:
            await ctx.send("No active match in this channel.")
            return
        ok, msg = try_leave(match_instance, ctx.author)
        await ctx.send(msg)
        if ok:
            persist(match_instance)

    @bot.command(name="players", aliases=["pl", "lobby"], help="Show the lobby / team lists.")
    @commands.guild_only()
    async def list_players(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if not match_instance:
            await ctx.send("No active match in this channel.")
            return
        if not match_instance.players:
            await ctx.send("No players have joined the match yet.")
            return
        await ctx.send(embed=lobby_embed(match_instance))

    @bot.command(name="declare", aliases=["dec"], help="Batting captain: declare your innings closed.")
    @commands.guild_only()
    async def declare_innings(ctx: commands.Context):
        match_instance: MatchInstance = ctx.bot.active_matches.get(ctx.channel.id)
        if not match_instance:
            await ctx.send("No active match in this channel.")
            return
        reason = declaration_block_reason(match_instance, ctx.author)   # FIX (B4): object comparisons
        if reason:
            await ctx.send(reason)
            return
        declaration_view = DeclarationView(match_instance, None, ctx.author)
        message = await ctx.send(
            f"Do you want to declare the innings at **{match_instance.score}/{match_instance.wickets}**?",
            view=declaration_view)
        declaration_view.message = message
