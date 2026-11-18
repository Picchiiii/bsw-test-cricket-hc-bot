"""Fake discord.ext.commands: enough of Bot/Context/command registration to drive the bot in tests.

Commands are invoked directly with already-converted arguments: bot.invoke_command(name, ctx, *args).
Checks (guild_only, is_owner) and on_command_error are honoured like the real framework.
"""
import asyncio
import inspect

import discord
from discord import app_commands


class CommandError(Exception):
    pass


class UserInputError(CommandError):
    pass


class CommandNotFound(CommandError):
    pass


class MissingRequiredArgument(UserInputError):
    def __init__(self, param):
        super().__init__(f"{param.name} is a required argument")
        self.param = param


class BadArgument(UserInputError):
    pass


class MemberNotFound(BadArgument):
    pass


class UserNotFound(BadArgument):
    pass


class CheckFailure(CommandError):
    pass


class NoPrivateMessage(CheckFailure):
    pass


class NotOwner(CheckFailure):
    pass


class CommandOnCooldown(CommandError):
    def __init__(self, retry_after=0):
        super().__init__("cooldown")
        self.retry_after = retry_after


class CommandInvokeError(CommandError):
    def __init__(self, original):
        super().__init__(str(original))
        self.original = original


def _add_check(func, check):
    func.__commands_checks__ = getattr(func, "__commands_checks__", []) + [check]
    return func


def guild_only():
    def deco(func):
        async def check(ctx):
            if ctx.guild is None:
                raise NoPrivateMessage()
            return True
        return _add_check(func, check)
    return deco


def is_owner():
    def deco(func):
        async def check(ctx):
            if not await ctx.bot.is_owner(ctx.author):
                raise NotOwner()
            return True
        return _add_check(func, check)
    return deco


def when_mentioned_or(*prefixes):
    return list(prefixes)


class Command:
    def __init__(self, func, name, aliases, help, hidden):
        self.callback = func
        self.name = name
        self.qualified_name = name
        self.aliases = aliases or []
        self.help = help
        self.hidden = hidden
        self.checks = getattr(func, "__commands_checks__", [])
        sig = inspect.signature(func)
        self.params = list(sig.parameters.values())[1:]
        self.signature = " ".join(f"<{p.name}>" for p in self.params)


class Context:
    def __init__(self, bot, author, channel, message=None, invoked_with=None):
        self.bot = bot
        self.author = author
        self.channel = channel
        self.guild = getattr(channel, "guild", None)
        self.message = message or discord.Message(channel=channel, author=author, content="")
        self.command = None
        self.invoked_with = invoked_with

    async def send(self, content=None, **kwargs):
        return await self.channel.send(content, **kwargs)


class _Loop:
    def create_task(self, coro):
        return asyncio.ensure_future(coro)


class Bot:
    def __init__(self, command_prefix=None, intents=None, help_command=None, case_insensitive=False, owner_ids=None):
        self.command_prefix = command_prefix
        self.intents = intents
        self.all_commands = {}
        self.commands_by_name = {}
        self._waiters = []
        self.extra_events = {}
        self.tree = app_commands.CommandTree(self)
        self.user = discord.User("BSW Bot", bot=True)
        self.owner_ids = set(owner_ids or [])
        self.latency = 0.05
        self._closed = False
        self.loop = _Loop()
        self.channels = {}
        self.users = {}
        self.setup_hook = None
        self.guilds = []
        self.checks = []
        self.listeners = {}

    def add_check(self, func):
        self.checks.append(func)

    def add_listener(self, func, name=None):
        self.listeners.setdefault(name or func.__name__, []).append(func)

    def listen(self, name=None):
        def deco(func):
            self.add_listener(func, name or func.__name__)
            return func
        return deco

    async def fire(self, event, *args):
        """Test helper: run the listeners of a gateway event (e.g. on_guild_join)."""
        for func in self.listeners.get(event, []):
            await func(*args)

    def get_guild(self, gid):
        for g in self.guilds:
            if g.id == gid:
                return g
        return None

    # registration
    def command(self, name=None, aliases=None, help=None, hidden=False, **kw):
        def deco(func):
            cmd = Command(func, name or func.__name__, aliases, help, hidden)
            if cmd.name in self.all_commands:
                raise RuntimeError(f"duplicate command {cmd.name}")
            self.commands_by_name[cmd.name] = cmd
            for key in [cmd.name, *cmd.aliases]:
                if key in self.all_commands:
                    raise RuntimeError(f"duplicate command or alias {key}")
                self.all_commands[key] = cmd
            return cmd
        return deco

    def event(self, func):
        setattr(self, func.__name__, func)
        return func

    # invocation (test helper)
    async def invoke_command(self, name, ctx, *args, **kwargs):
        cmd = self.all_commands.get(name)
        if cmd is None:
            raise CommandNotFound(name)
        ctx.command = cmd
        ctx.invoked_with = name
        try:
            for check in self.checks:          # global checks (bot.add_check) run first, like discord.py
                if not await check(ctx):
                    raise CheckFailure()
            for check in cmd.checks:
                await check(ctx)
            required = [p for p in cmd.params if p.default is inspect.Parameter.empty
                        and p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD]
            if len(args) < len(required) and not kwargs:
                raise MissingRequiredArgument(required[len(args)])
            return await cmd.callback(ctx, *args, **kwargs)
        except CommandError as e:
            handler = getattr(self, "on_command_error", None)
            if handler is None:
                raise
            await handler(ctx, e)
        except Exception as e:
            handler = getattr(self, "on_command_error", None)
            if handler is None:
                raise
            await handler(ctx, CommandInvokeError(e))

    # events
    async def wait_for(self, event, *, check=None, timeout=None):
        fut = asyncio.get_event_loop().create_future()
        self._waiters.append((event, check, fut))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._waiters = [w for w in self._waiters if w[2] is not fut]

    def dispatch(self, event, *args):
        for ev, check, fut in list(self._waiters):
            if ev != event or fut.done():
                continue
            try:
                ok = check(*args) if check else True
            except Exception as e:
                fut.set_exception(e)
                continue
            if ok:
                fut.set_result(args[0] if len(args) == 1 else args)

    # lookups
    def get_channel(self, cid):
        return self.channels.get(cid)

    async def fetch_channel(self, cid):
        ch = self.channels.get(cid)
        if ch is None:
            raise discord.NotFound(message="Unknown Channel")
        return ch

    def get_user(self, uid):
        return self.users.get(uid)

    async def fetch_user(self, uid):
        u = self.users.get(uid)
        if u is None:
            raise discord.NotFound(message="Unknown User")
        return u

    async def is_owner(self, user):
        return user.id in self.owner_ids

    def is_closed(self):
        return self._closed

    async def change_presence(self, **kwargs):
        pass

    async def close(self):
        self._closed = True

    def run(self, token, **kwargs):
        raise RuntimeError("not available in tests")
