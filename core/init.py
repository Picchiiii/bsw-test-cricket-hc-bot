import logging
import discord
from discord.ext import commands
from core.backend.turso.db import TursoDB
logger = logging.getLogger(__name__)


def create_bot(token: str, prefix: str):
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True

    bot = commands.Bot(command_prefix=prefix, intents=intents, help_command=None)

    async def setup_hook():
        await TursoDB().init_db()
        print("Database and tables initialized")
        logger.info("Database and tables initialized")

    bot.setup_hook = setup_hook

    @bot.event
    async def on_ready():
        logger.info("bot: logged in as %s (id: %s)", bot.user, bot.user.id)

    return bot


def load_commands(bot):
    from .load import load
    load(bot)
