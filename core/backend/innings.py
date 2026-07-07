import discord
from discord.ext import commands
from core.backend.instance import MatchInstance
import asyncio
import logging

logger = logging.getLogger(__name__)


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
        await asyncio.sleep(20)
        if self.mi.curr_batsman is None:
            game.send_next_batsman()
        if self.mi.curr_bowler is None:
            game.send_next_bowler()
        embed = discord.Embed(
            title="Innings 1 has started!",
            description=f"First batter is {self.mi.curr_batsman.mention}\n\nFirst bowler is {self.mi.curr_bowler.mention}",
            color=discord.Color.blue()
            )
        embed.set_footer(text="Start sending your actions in my DMs")
        
        await self.ctx.channel.send(content= f"{self.mi.curr_batsman.mention} {self.mi.curr_bowler.mention}",embed=embed)

        scorecard = await self.ctx.channel.send(embed=game.generate_scorecard_embed())
        await game.next_batsman()
        await game.next_bowler()

        while self.mi.overs < self.mi.match_settings['overs']:
            if self.mi.innings_declared == True:
                break ## Declaration logic

            if self.mi.wickets < ((len(self.mi.players))/2):
                await asyncio.sleep(0.5) 
                await game.request_ball()
                if self.mi.balls_this_over == 6:
                    self.mi.overs += 1
                    self.mi.balls_this_over = 0
                    await scorecard.edit(embed=game.generate_scorecard_embed())
                    
                    game.send_next_bowler()
                    await game.next_bowler()
                await scorecard.edit(embed=game.generate_scorecard_embed())

                self.mi.zeros_by_batsman = 0
                self.mi.last_over_bowler = self.mi.curr_bowler
                self.mi.curr_bowler = None

                ### left it here for now, will add the rest of the logic later


            else:
                print("All wickets have fallen, breaking loop")
                await self.ctx.channel.send("All wickets have fallen. Innings is over.")
                break
    


    

class Innings:
    def __init__(self, ctx, match_instance):
        self.ctx = ctx
        self.mi = match_instance
        self.one = One(ctx, match_instance)



class MatchDecisions:
    def __init__(self, ctx, match_instance):
        self.ctx = ctx
        self.mi = match_instance


    async def declare_innings(self):
        from core.backend.views.declare_view import DeclarationView
        message = await self.ctx.send(
            f"**{self.mi.curr_batsman.name}**, do you want to declare the innings?",
            view=DeclarationView(self.mi, None, self.mi.curr_batsman)
        )
        view = DeclarationView(self.mi, message, self.mi.curr_batsman)
        await message.edit(view=view)
