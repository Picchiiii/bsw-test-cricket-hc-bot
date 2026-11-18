import asyncio
import logging
import time
import discord
from discord.ext import commands
from discord import app_commands

from core.backend import access as access_control
from core.backend.turso.db import get_database
from core.backend.persistence import Store, restore_matches
from core.config import config
from core.economy import settings as eco_settings
from core.tournament import manager as tournament_manager

logger = logging.getLogger(__name__)


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


async def _lobby_janitor(bot):
    """Close lobbies that were never started (config: lobby_ttl_minutes)."""
    ttl = config.game.get("lobby_ttl_minutes", 0) * 60
    if not ttl:
        return
    while not bot.is_closed():
        await asyncio.sleep(300)
        now = time.time()
        for cid, mi in list(bot.active_matches.items()):
            if not mi.game_started and now - mi.last_activity > ttl:
                del bot.active_matches[cid]
                try:
                    await bot.store.delete_state(mi)
                    await mi.channel.send("🧹 This lobby was closed because the match never started.")
                except Exception:
                    pass


def create_bot(token: str, prefix: str, db=None):
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.guilds = True
    intents.dm_messages = True

    # owner_ids from config.toml / OWNER_IDS; an empty set means "the owner of the Discord application"
    bot = commands.Bot(command_prefix=commands.when_mentioned_or(prefix), intents=intents,
                       help_command=None, case_insensitive=True, owner_ids=set(config.owner_ids))
    bot.active_matches = {}      # {channel_id: MatchInstance} — shape unchanged
    bot.recent_matches = {}
    bot.db = db or get_database()
    bot.store = Store(bot.db)
    bot._restored = False
    access_control.install(bot)          # server whitelist (bot.access) + global command check
    tournament_manager.install(bot)      # bot.tournaments

    async def record(mi):
        from core.economy.profiles import record_match
        return await record_match(bot.db, mi)
    bot.record_match = record

    async def setup_hook():
        bot.tree.add_command(botsay)
        await bot.db.init_db()
        logger.info("Database and tables initialized")
        await bot.access.load()
        await eco_settings.load(bot.db)
        await bot.tournaments.publish_schema()
        try:
            await bot.tree.sync()  # Sync the command tree with Discord
        except Exception as e:
            logger.warning("app command sync failed: %s", e)
        asyncio.create_task(_lobby_janitor(bot))

    bot.setup_hook = setup_hook

    @bot.event
    async def on_ready():
        logger.info("bot: logged in as %s (id: %s)", bot.user, bot.user.id)
        if not bot._restored:
            bot._restored = True
            n = await restore_matches(bot)
            if n:
                logger.info("restored %d saved match(es)", n)
            bot.tournaments.start()      # website requests, fixture reminders, housekeeping
            if bot.access.enabled:
                unlisted = [g for g in bot.guilds if not bot.access.is_allowed(g.id)]
                if unlisted:
                    logger.info("%d server(s) are not on the whitelist: %s", len(unlisted),
                                ", ".join(f"{g.name} ({g.id})" for g in unlisted[:20]))
        try:
            await bot.change_presence(activity=discord.Game(name=f"Test cricket • {config.prefix}help"))
        except Exception:
            pass

    async def close_hook():
        # flush every running match before shutting down
        for mi in list(bot.active_matches.values()):
            try:
                await bot.store.flush(mi)
            except Exception:
                pass
        bot.tournaments.stop()
        reporter = getattr(bot, "error_reporter", None)
        if reporter is not None:
            await reporter.close()
        try:
            await bot.db.close()
        except Exception:
            pass

    bot._bsw_close_hook = close_hook
    original_close = bot.close

    async def close():
        await close_hook()
        await original_close()
    bot.close = close

    return bot


def load_commands(bot):
    from .load import load
    load(bot)
