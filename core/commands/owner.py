import discord
from discord.ext import commands
import logging


logger = logging.getLogger(__name__)

def owner(bot: commands.Bot):

    
    @bot.command(name="instance", aliases=["gi"])
    async def get_instance(ctx: commands.Context):
        match_instance = bot.active_matches.get(ctx.channel.id)
        if match_instance:
            await ctx.send(f"Match instance found for channel {ctx.channel.name}.")
        else:
            await ctx.send(f"No match instance found for channel {ctx.channel.name}.")