import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


class GameChecks():
    """Membership checks compare Member objects to Member objects (spec §3.4, fixes B4)."""

    @staticmethod
    async def is_host(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author == match_instance.host:
                return True
            await ctx.send("Only the host can perform this action.")
            return False
        return False

    @staticmethod
    async def is_player(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author in match_instance.players:
                return True
            await ctx.send("You are not a player in this match.")
            return False
        return False

    @staticmethod
    async def is_captain(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author == match_instance.teamA_captain or ctx.author == match_instance.teamB_captain:
                return True
            await ctx.send("Only the team captains can perform this action.")
            return False
        return False

    @staticmethod
    async def is_toss_winner(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author == match_instance.toss_winner:
                return True
            await ctx.send("Only the toss winner can perform this action.")
            return False
        return False

    # ----------------------------------------------------------------- engine
    @staticmethod
    def all_out_limit(mi) -> int:
        """Wickets that end an innings for the batting side (spec §5.5, fixes B11)."""
        size = len(mi.team(mi.batting_turn))
        if mi.match_settings.get('last_man_bats'):
            return max(1, size)
        return max(1, size - 1)

    @staticmethod
    def is_all_out(mi) -> bool:
        # reps retired "not out" at their run cap can't bat again, so they use up a batting place too
        return mi.wickets + getattr(mi, "retired_not_out", 0) >= GameChecks.all_out_limit(mi)

    @staticmethod
    async def game_continue_check(match_instance) -> bool:
        """Single source of truth for 'is the current innings still live' (spec §5.4)."""
        mi = match_instance
        if not mi.game_started:
            return False
        if mi.match_abandoned:
            return False
        if mi.innings > 4:
            return False
        days = mi.match_settings.get('days') or 0
        if days and mi.crr_day > days:
            mi.result = mi.result or {'type': 'draw', 'reason': 'days_exhausted'}
            return False
        if mi.innings == 4 and mi.target is not None and mi.score >= mi.target:
            mi.result = {'type': 'win', 'winner': mi.batting_turn, 'reason': 'target_chased'}
            return False
        cap = mi.innings_overs_cap
        if cap and mi.overs >= cap:
            return False   # innings-level stoppage only; caller routes to the next innings
        if GameChecks.is_all_out(mi):
            return False
        return True
