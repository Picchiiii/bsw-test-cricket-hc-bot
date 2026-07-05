import discord
from discord.ext import commands
from core.backend.instance import MatchInstance
import asyncio


class One():
    def __init__(self, ctx, match_instance: MatchInstance):
        self.ctx: commands.Context = ctx
        self.mi = match_instance


    async def start_first_innings(self):
        from core.backend.game import Game
        game = Game(self.ctx, self.mi)
        await game.initialise()
        await self.ctx.channel.send("The Match has started!")
        
        await game.next_batsman()
        await game.next_bowler()
        await asyncio.sleep(20)  # Small delay to ensure the message is sent before proceeding
        embed = discord.Embed(
            title="Innings 1 has started!",
            description=f"First batter is {self.mi.curr_batsman.mention}\n\nFirst bowler is {self.mi.curr_bowler.mention}",
            color=discord.Color.blue()
            )
        embed.set_footer(text="Start sending your actions in my DMs")
        
        await self.ctx.channel.send(content= f"{self.mi.curr_batsman.mention} {self.mi.curr_bowler.mention}",embed=embed)

        scorecard = await self.ctx.channel.send(embed=game.generate_scorecard_embed())
        
        while self.mi.overs < self.mi.match_settings['overs']:
            if self.mi.innings_declared == True:
                break ## Declaration logic

            if self.mi.wickets < ((len(self.mi.players))/2):
                await game.request_ball()
                ### left it here for now, will add the rest of the logic later

                await scorecard.edit(embed=game.generate_scorecard_embed())

            else:
                print("All wickets have fallen, breaking loop")
                await self.ctx.channel.send("All wickets have fallen. Innings is over.")
                break

        
        

    

class Innings:
    def __init__(self, ctx, match_instance):
        self.ctx = ctx
        self.mi = match_instance
        self.one = One(ctx, match_instance)