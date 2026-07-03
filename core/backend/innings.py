import discord
from discord.ext import commands
from core.backend.game import Game
from core.backend.instance import MatchInstance
import asyncio


class One():
    def __init__(self, ctx, match_instance: MatchInstance):
        self.mi = match_instance
        self.ctx: commands.Context = ctx


    async def start_first_innings(self):
        game = Game(self.ctx, self.mi)
        await game.initialise()
        await self.ctx.send("The Match has started!")
        
        await game.next_batsman()
        await game.next_bowler()

        await asyncio.sleep(20)

        embed = discord.Embed(
            title="Innings 1 has started!",
            description=f"First batter is {self.mi.curr_batsman.mention}\n\nFirst bowler is {self.mi.curr_bowler.mention}",
            color=discord.Color.blue()
            )
        embed.set_footer(text="Start sending your actions in my DMs")
        
        await self.ctx.send(content= f"{self.mi.curr_batsman.mention} {self.mi.curr_bowler.mention}",embed=embed)

        
        
        

    

class Innings():
    def __init__(self, match_instance):
        self.match_instance = match_instance
        self.one = One(match_instance)
