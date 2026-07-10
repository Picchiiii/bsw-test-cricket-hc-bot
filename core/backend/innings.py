import discord
from discord.ext import commands
from core.backend import game
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
            if self.mi.match_abandoned == True:
                Innings.abandon_match(self.ctx, self.mi)
                break
            if self.mi.innings_declared == True:
                break ## Declaration logic

            if self.mi.wickets < ((len(self.mi.players))/2):
                await game.request_ball()
                if self.mi.balls_this_over == 6:
                    await scorecard.edit(embed=game.generate_scorecard_embed())
                    await game.complete_over()

                await scorecard.edit(embed=game.generate_scorecard_embed())
            else:
                await self.ctx.channel.send("All wickets have fallen. Innings is over.")
                break

        await Two(self.ctx, self.mi, game).start_second_innings()
        

class Two():
    def __init__(self, ctx, match_instance: MatchInstance, game):
        self.ctx: commands.Context = ctx
        self.mi = match_instance
        self.game = game

    async def start_second_innings(self):
        await self.ctx.channel.send("Innings 2 has started!")
        
        await self.game.next_batsman()
        await self.game.next_bowler()
        await asyncio.sleep(20)
        if self.mi.curr_batsman is None:
            self.game.send_next_batsman()
        if self.mi.curr_bowler is None:
            self.game.send_next_bowler()
        embed = discord.Embed(
            title="Innings 2 has started!",
            description=f"First batter is {self.mi.curr_batsman.mention}\n\nFirst bowler is {self.mi.curr_bowler.mention}",
            color=discord.Color.blue()
            )
        embed.set_footer(text="Start sending your actions in my DMs")
        
        await self.ctx.channel.send(content= f"{self.mi.curr_batsman.mention} {self.mi.curr_bowler.mention}",embed=embed)

        scorecard = await self.ctx.channel.send(embed=self.game.generate_scorecard_embed())
        await self.game.next_batsman()
        await self.game.next_bowler()

        while self.mi.overs < self.mi.match_settings['overs']:
            if self.mi.match_abandoned == True:
                Innings.abandon_match(self.ctx, self.mi)
                break
            if self.mi.innings_declared == True:
                break ## Declaration logic

            if self.mi.wickets < ((len(self.mi.players))/2):
                await self.game.request_ball()
                if self.mi.balls_this_over == 6:
                    await scorecard.edit(embed=self.game.generate_scorecard_embed())

                await scorecard.edit(embed=self.game.generate_scorecard_embed())
            else:
                await self.ctx.channel.send("All wickets have fallen. Innings is over.")
                break


class Innings:
    def __init__(self, ctx: commands.Context, match_instance: MatchInstance):
        self.ctx = ctx
        self.mi = match_instance
        self.one = One(ctx, match_instance)

    @staticmethod
    def abandon_match(ctx, match_instance: MatchInstance):
        del ctx.bot.active_matches[match_instance.channel.id]



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



