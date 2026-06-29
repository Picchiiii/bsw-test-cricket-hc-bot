import logging
import discord
from discord.ext import commands
from core.backend.turso.db import TursoDB
logger = logging.getLogger(__name__)
from discord import app_commands
@app_commands.command(name="say", description="Bot sends a message to a user's DMs")
@app_commands.allowed_installs(users=True, guilds=False)
async def botsay(interaction: discord.Interaction, user: discord.User, message: str):
    try:
        await user.send(message)
        await interaction.response.send_message(
            f"Sent your message to {user.mention}'s DMs!",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "I couldn't DM that user. They may have DMs disabled or not share a server with me.",
            ephemeral=True
        )

def create_bot(token: str, prefix: str):
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True

    bot = commands.Bot(command_prefix=prefix, intents=intents, help_command=None)

    async def setup_hook():
        bot.tree.add_command(botsay)
        await bot.tree.sync()  # Sync the command tree with Discord
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
