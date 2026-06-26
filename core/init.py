import logging
import discord
from discord.ext import commands
from core.backend.turso.db import TursoDB
logger = logging.getLogger(__name__)
from discord import app_commands

# @app_commands.command(name="say", description="bot says what you want it to say")
# @app_commands.allowed_installs(users= True, guilds=False)
# async def botsay(interaction: discord.Interaction, message: str):
#     await interaction.response.send_message("Sent!", ephemeral=True)
#     await interaction.channel.send(message)

def create_bot(token: str, prefix: str):
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True

    bot = commands.Bot(command_prefix=prefix, intents=intents, help_command=None)

    async def setup_hook():
        # bot.tree.add_command(botsay)
        # await bot.tree.sync()  # Sync the command tree with Discord
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
