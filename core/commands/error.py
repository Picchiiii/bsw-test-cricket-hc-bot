import os
import traceback
import discord
from discord.ext import commands
import logging

from core.backend.access import GuildNotAllowed
from core.config import config
from core.ui import theme

logger = logging.getLogger(__name__)


class WebhookErrorHandler():
    """Posts unexpected errors to ERROR_WEBHOOK_URL (if set) so the developer sees them."""

    def __init__(self, bot):
        self.bot = bot
        self.url = os.getenv("ERROR_WEBHOOK_URL", "").strip()
        self._session = None

    async def on_webhook_error(self, error: Exception, where: str = ""):
        logger.error("error%s: %r", f" in {where}" if where else "", error)
        if not self.url:
            return
        try:
            import aiohttp  # ships with discord.py
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            webhook = discord.Webhook.from_url(self.url, session=self._session)
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-3500:]
            e = discord.Embed(title=f"⚠️ {type(error).__name__}", description=f"**Where:** {where}\n```py\n{tb}\n```",
                              color=theme.RED)
            await webhook.send(embed=e, username=f"{config.bot_name} errors")
        except Exception as e:  # never let error reporting crash anything
            logger.warning("could not post to error webhook: %s", e)

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()


def error_handler(bot: commands.Bot):
    reporter = WebhookErrorHandler(bot)
    bot.report_error = reporter.on_webhook_error
    bot.error_reporter = reporter

    @bot.event
    async def on_command_error(ctx: commands.Context, error: commands.CommandError):  # FIX: no stray `self`
        error = getattr(error, "original", error) if isinstance(error, commands.CommandInvokeError) else error
        p = config.prefix
        if isinstance(error, commands.CommandNotFound):
            return   # stay quiet: people type the prefix in normal chat
        if isinstance(error, commands.MissingRequiredArgument):
            usage = f"{p}{ctx.command.qualified_name} {ctx.command.signature}" if ctx.command else ""
            await ctx.send(f"Missing required argument: **{error.param.name}**\nUsage: `{usage}`")
        elif isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
            await ctx.send("I couldn't find that member. Mention them or use their ID.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Bad argument: {error}")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("That command only works in a server channel.")
        elif isinstance(error, GuildNotAllowed):
            access = getattr(ctx.bot, "access", None)
            if access is not None and access.should_tell(ctx.channel.id):
                try:
                    await ctx.send(access.denied_text(ctx.guild))
                except discord.HTTPException:
                    pass
        elif isinstance(error, commands.NotOwner):
            await ctx.send("Only the bot owner can use that command.")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Slow down! Try again in {error.retry_after:.0f}s.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("You do not have permission to use this command.")
        else:
            embed = discord.Embed(
                title="Error",
                description="An unexpected error occurred. The developers have been notified.",
                color=discord.Color.red()
            )
            await reporter.on_webhook_error(error, where=f"command {ctx.command} in #{getattr(ctx.channel, 'name', 'DM')}")
            try:
                await ctx.send(embed=embed)
            except discord.HTTPException:
                pass
