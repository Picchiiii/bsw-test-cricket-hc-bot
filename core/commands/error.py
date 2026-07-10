import discord 
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


class WebhookErrorHandler():
    def __init__(self, error):
        self.error = error

    async def on_webhook_error(self, error: Exception):
        logger.error(f"Webhook error occurred: {error}")
        # You can add more sophisticated error handling here, such as notifying admins or retrying the webhook.

def error_handler(bot: commands.Bot):


    @bot.event
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing required argument: {error.param.name}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Bad argument: {error}")
        elif isinstance(error, commands.CommandNotFound):
            await ctx.send("Command not found.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("You do not have permission to use this command.")
        else:
            embed = discord.Embed(
                title="Error",
                description=f"An unexpected error occurred: {error}",
                color=discord.Color.red()
            )
            logger.error(f"Unhandled command error: {error}")
            await ctx.send(embed=embed)


    