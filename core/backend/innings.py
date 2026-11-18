import discord
from discord.ext import commands
from core.backend.instance import MatchInstance
import asyncio
import logging

logger = logging.getLogger(__name__)

# Every innings now runs through one shared loop, Game.play_innings() (spec §5.1). These classes are
# kept as thin, readable phase markers so existing call sites keep working.


class _InningsPhase:
    number = 0

    def __init__(self, ctx, match_instance: MatchInstance, game=None):
        self.ctx: commands.Context = ctx
        self.mi = match_instance
        self.game = game or match_instance.game

    async def start(self):
        if self.game is None:
            from core.backend.game import Game
            self.game = Game(self.ctx, self.mi)
            await self.game.initialise()
        if self.mi.innings != self.number or self.mi.phase != "innings":
            self.game.begin_innings_state(self.number)
        await self.game.play_innings(self.number)


class One(_InningsPhase):
    number = 1

    async def start_first_innings(self):
        await self.start()


class Two(_InningsPhase):
    number = 2

    async def start_second_innings(self):
        await self.start()


class Three(_InningsPhase):
    number = 3

    async def start_third_innings(self):
        await self.start()


class Four(_InningsPhase):
    number = 4

    async def start_fourth_innings(self):
        await self.start()


class Innings:
    def __init__(self, ctx: commands.Context, match_instance: MatchInstance):
        self.ctx = ctx
        self.mi = match_instance
        self.one = One(ctx, match_instance)

    @staticmethod
    def abandon_match(ctx, match_instance: MatchInstance):
        bot = ctx.bot if ctx is not None else match_instance.bot
        if bot.active_matches.get(match_instance.channel.id) is match_instance:
            del bot.active_matches[match_instance.channel.id]


class MatchDecisions:
    def __init__(self, ctx, match_instance):
        self.ctx = ctx
        self.mi = match_instance

    async def declare_innings(self):
        from core.backend.views.declare_view import DeclarationView, declaration_block_reason
        captain = self.mi.captain(self.mi.batting_turn)
        reason = declaration_block_reason(self.mi, self.ctx.author)
        if reason:
            await self.ctx.send(reason)
            return None
        view = DeclarationView(self.mi, None, captain)
        message = await self.ctx.send(
            f"**{captain.name}**, do you want to declare the innings at **{self.mi.score}/{self.mi.wickets}**?",
            view=view
        )
        view.message = message
        return view
