import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)

class GameChecks:

    @staticmethod
    async def is_host(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author.id == match_instance.host.id:
                return True
            else:
                await ctx.send("Only the host can perform this action.")
                return False
            
    @staticmethod
    async def is_player(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author.id in match_instance.players:
                return True
            else:
                await ctx.send("You are not a player in this match.")
                return False
    
    @staticmethod
    async def is_captain(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author.id == match_instance.teamA_captain or ctx.author.id == match_instance.teamB_captain:
                return True
            else:
                await ctx.send("Only the team captains can perform this action.")
                return False
            
    @staticmethod
    async def is_toss_winner(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author.id == match_instance.toss_winner:
                return True
            else:
                await ctx.send("Only the toss winner can perform this action.")
                return False
