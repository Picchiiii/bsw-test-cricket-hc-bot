import discord
from discord.ext import commands
import logging
import random
from core.backend.views.toss_view import TossView

logger = logging.getLogger(__name__)

def match(bot: commands.Bot):


    @bot.command(name="toss", help="Conduct a toss to decide which team will bat or bowl first.", aliases=["t"])
    async def toss(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author.id == match_instance.host.id:
                user: discord.Member = random.choice([ctx.bot.teamA_captain, ctx.bot.teamB_captain])
                toss_view = TossView(match_instance, None, user)
                toss_message = await ctx.send(f"Starting the toss! **{ctx.bot.teamA_name if user == ctx.bot.teamA_captain else ctx.bot.teamB_name}** captain {user.mention} choose Heads or Tails.", view=toss_view)
                toss_view.message = toss_message
            else:
                await ctx.send("Only the host can conduct the toss.")

    @bot.command(name="start", help="Start the ongoing match in the channel.", aliases=["s"])
    async def start_match(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author.id == match_instance.host.id:
                if len(match_instance.players):
                    match_instance.lobby_lock = True
                    await ctx.send("The match has started!")
                else:
                    await ctx.send("Not enough players to start the match. At least 2 players are required.")
            else:
                await ctx.send("Only the host can start the match.")
        else:
            await ctx.send("No active match in this channel.")