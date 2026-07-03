import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)

class GameChecks():

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


    @staticmethod
    async def game_continue_check(match_instance):
        ## At this point match_instance.game_started will always be True so leaving that condition as it is
        game_over_condns = [
            match_instance.game_started == False, ## remove later
            match_instance.innings > 4, # Match gets over after 4th innings
            match_instance.score >= match_instance.target and match_instance.innings == 2, # target is reached by the team
            match_instance.innings == 1 and match_instance.overs >= match_instance.match_settings['overs'],
            match_instance.innings == 2 and match_instance.overs >= match_instance.match_settings['overs'],
            match_instance.crr_day > match_instance.match_settings['days'],
            match_instance.wickets >= (len(match_instance.players))/2
        ]


        return not any(game_over_condns)