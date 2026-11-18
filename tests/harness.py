"""Simulated Discord world for end-to-end tests: a guild, channels, players with strategies."""
import asyncio
import random

import discord
from discord.ext import commands

from core.backend.turso.db import SQLiteDB
from core.init import create_bot, load_commands
from core.backend.dropdown.player_select import PlayerView, PlayerSelect
from core.backend.views.follow_on_view import FollowOnView
from core.backend.views.toss_view import TossView
from core.backend.views.batball_view import BatBallView
from core.backend.views.stumps_view import StumpsView


class Player:
    """A member whose DMs are answered automatically by `strategy(role, player, game) -> int | None`."""

    def __init__(self, world, name, strategy=None, mode="type"):   # mode kept for old call sites
        self.world = world
        self.member = discord.Member(name, world.guild)
        world.bot.users[self.member.id] = self.member
        self.strategy = strategy or random_strategy
        self.mode = mode           # "type" | "button" | "mixed"
        self.picks = []
        self.member.dm_channel.listeners.append(self._on_dm)

    def _on_dm(self, msg):
        role = prompt_role(msg)
        if role:
            return self._answer(msg, role)

    async def _answer(self, msg, role):
        await asyncio.sleep(random.uniform(0.002, 0.012))
        mi = next((m for m in self.world.bot.active_matches.values() if self.member in m.players), None)
        value = self.strategy(role, self, mi)
        if value is None:
            return   # AFK
        self.picks.append((role, value))
        reply = discord.Message(channel=self.member.dm_channel, author=self.member, content=str(value))
        self.world.bot.dispatch("message", reply)


def prompt_role(msg):
    """'batsman' / 'bowler' if this DM is a ball prompt, else None."""
    title = (msg.embed.title or "") if msg.embed else ""
    if "Bowl" in title and "🥎" in title:
        return "bowler"
    if "Bat" in title and "🏏" in title:
        return "batsman"
    return None


def random_strategy(role, player, mi):
    if role == "bowler":
        return random.choice([1, 2, 3, 4, 5, 6])
    return random.choice([0, 1, 2, 3, 4, 5, 6])


class World:
    def __init__(self, db=None, owner=None):
        self.guild = discord.Guild()
        self.db = db or SQLiteDB(":memory:")
        self.bot = create_bot("token", "+", db=self.db)
        load_commands(self.bot)
        self.bot.guilds.append(self.guild)
        self.channels = []
        self.captain_mode = "pick"     # "pick" | "ignore"
        self.follow_on = True          # enforce follow-on when offered
        self.auto_next_day = True      # press "Start next day" automatically
        self.events = []

    async def setup(self):
        await self.bot.setup_hook()
        self.bot._restored = True

    def channel(self, name="match"):
        ch = discord.TextChannel(self.guild, name=f"{name}-{len(self.channels)}", bot_user=self.bot.user)
        self.bot.channels[ch.id] = ch
        ch.listeners.append(lambda m, ch=ch: self._on_channel(ch, m))
        self.channels.append(ch)
        return ch

    def ctx(self, author, channel):
        return commands.Context(self.bot, author, channel)

    async def cmd(self, name, author, channel, *args, **kwargs):
        m = author.member if isinstance(author, Player) else author
        return await self.bot.invoke_command(name, self.ctx(m, channel), *args, **kwargs)

    # automatic captain / decision behaviour
    def _on_channel(self, channel, msg):
        view = msg.view
        if isinstance(view, PlayerView) and self.captain_mode == "pick":
            return self._pick(view, msg)
        if isinstance(view, FollowOnView):
            return self._click(view, msg, view.allowed_user, "follow_on_yes_button" if self.follow_on else "follow_on_no_button")
        if isinstance(view, StumpsView) and self.auto_next_day:
            mi = view.match_instance
            return self._click(view, msg, mi.host, "next_day", delay=0.01)

    async def _pick(self, view, msg):
        await asyncio.sleep(0.003)
        if view.is_finished():
            return
        select = next(c for c in view.children if isinstance(c, PlayerSelect))
        select.values = [select.options[-1].value]   # pick the last listed (not the default auto-pick)
        captain = view.match_instance.captain(view.side)
        inter = discord.Interaction(user=captain, channel=msg.channel, client=self.bot, message=msg)
        await select.callback(inter)

    async def _click(self, view, msg, user, attr, delay=0.003):
        await asyncio.sleep(delay)
        if view.is_finished():
            return
        btn = getattr(view, attr)
        inter = discord.Interaction(user=user, channel=msg.channel, client=self.bot, message=msg)
        await btn.callback(inter)

    async def click(self, msg, user, label):
        view = msg.view
        btn = next(c for c in view.children if getattr(c, "label", None) and c.label.startswith(label))
        inter = discord.Interaction(user=user.member if isinstance(user, Player) else user, channel=msg.channel,
                                    client=self.bot, message=msg)
        await btn.callback(inter)
        return inter

    # full lobby → start
    async def setup_match(self, channel, players_a, players_b, overs=10, days=3, bat_first="A", **settings):
        """Create a lobby with the given teams, toss, choose, and start. Returns the MatchInstance."""
        host = players_a[0]
        await self.cmd("create", host, channel)
        mi = self.bot.active_matches[channel.id]
        # join alternately so join_segregate_player builds the intended teams
        order = []
        for i in range(max(len(players_a), len(players_b))):
            if i < len(players_b):
                order.append(players_b[i])
            if i + 1 < len(players_a):
                order.append(players_a[i + 1])
        for p in order:
            await self.cmd("join", p, channel)
        # make the teams exactly what the test asked for (join order balances automatically)
        mi.teamA = [p.member for p in players_a]
        mi.teamB = [p.member for p in players_b]
        mi.teamA_captain = mi.teamA[0]
        mi.teamB_captain = mi.teamB[0]
        await self.cmd("so", host, channel, overs if overs >= 10 else 10)
        await self.cmd("sd", host, channel, days)
        if overs < 10:
            mi.match_settings["overs"] = overs
        for k, v in settings.items():
            mi.match_settings[k] = v
        await self.cmd("toss", host, channel)
        toss_msg = channel.messages[-1]
        caller = toss_msg.view.allowed_user
        await self.click(toss_msg, caller, "Heads")
        await asyncio.sleep(0.01)
        bb_msg = channel.messages[-1]
        winner = bb_msg.view.allowed_user
        winner_side = "A" if winner == mi.teamA_captain else "B"
        choice = "Bat" if winner_side == bat_first else "Bowl"
        await self.click(bb_msg, winner, choice)
        assert mi.batting_turn == bat_first
        await self.cmd("start", host, channel)
        return mi

    async def finish(self, mi, timeout=60):
        await asyncio.wait_for(mi.task, timeout)
        return mi


def make_players(world, names, strategy=None, mode="mixed"):
    return [Player(world, n, strategy=strategy, mode=mode) for n in names]


class Script:
    """Deterministic picks by role: Script(batsman=[...], bowler=[...], fallback=fn).

    Every player in the match uses the same Script object, so whoever is currently batting/bowling
    consumes the next value for that role. Use None in a queue to simulate a missed ball (AFK).
    """

    def __init__(self, batsman=None, bowler=None, fallback=None):
        self.queues = {"batsman": list(batsman or []), "bowler": list(bowler or [])}
        self.fallback = fallback or random_strategy

    def __call__(self, role, player, mi):
        q = self.queues[role]
        if q:
            return q.pop(0)
        return self.fallback(role, player, mi)


def never_out(role, player, mi):
    """Batter always 2, bowler always 1: runs flow and nobody is ever out."""
    return 1 if role == "bowler" else 2


async def wait_until(pred, timeout=20, interval=0.005):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while not pred():
        if loop.time() > end:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(interval)
