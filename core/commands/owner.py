import discord
from discord.ext import commands
import logging
import time

def owner(bot: commands.Bot):

    @bot.command(name="owner", aliases=["o"])
    @commands.is_owner()
    async def owner_command(ctx: commands.Context):
        await ctx.send("You are the owner of this bot.")

        

    @bot.command(name="ping", aliases=["p"])
    async def ping(ctx: commands.Context):
        start_time = time.time()
        message = await ctx.send("Pinging...")
        end_time = time.time()
        latency = (end_time - start_time) * 1000  
        await message.edit(content=f"Pong! Latency: {latency:.2f} ms")