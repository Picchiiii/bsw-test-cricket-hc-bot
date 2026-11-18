"""Shared look & feel: colours, emojis and small formatting helpers.

Everything visual lives here so embeds stay consistent across the bot.
"""
import discord
from core.config import config

# ── Brand palette (taken from the bot logo: cream, ball gold, pitch green) ──
CREAM = 0xF6DC9A      # original scorecard colour, kept as the primary brand colour
GOLD = 0xE8B84A
GREEN = 0x1F6B3A
RED = 0xD64545
BLUE = 0x3B82C4
GREY = 0x2B2D31
PURPLE = 0x8E6CD8

# The bot's own application emojis (uploaded from core/assets/images/emojis).
_CUSTOM = {
    "0": "<:zero:1523349130934489201>",
    "1": "<:one:1523349128724218007>",
    "2": "<:two:1523349126425612513>",
    "3": "<:three:1523349122378235904>",
    "4": "<:four:1523349119643685056>",
    "5": "<:five:1523349117252665384>",
    "6": "<:six:1523349115289997362>",
    "W": "<:w_:1523349110290120856>",
    "NB": "<:nb:1523349112471158965>",
}
_UNICODE = {
    "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
    "5": "5️⃣", "6": "6️⃣", "W": "🟥", "NB": "🟨",
}

EMOJI_MAP = _CUSTOM if config.game.get("use_custom_emojis", True) else _UNICODE

# Other emojis used around the bot (kept from the original code where they existed)
TICK = "<:correct:1519046913666715749>"
CROSS = "<:redcross:1519046806338670633>"
if not config.game.get("use_custom_emojis", True):
    TICK, CROSS = "✅", "❌"

BAT = "🏏"
BALL = "🥎"
STADIUM = "🏟️"
TROPHY = "🏆"
COIN = config.economy.get("currency_emoji", "🪙")
CURRENCY = config.economy.get("currency_name", "Coins")
SEP = "━━━━━━━━━━━━━━━━━━━━━━"


def ball_emoji(entry: str) -> str:
    return EMOJI_MAP.get(str(entry), str(entry))


def overs_str(balls: int) -> str:
    """Balls → cricket overs notation (e.g. 14 → '2.2')."""
    return f"{balls // 6}.{balls % 6}"


def strike_rate(runs: int, balls: int) -> float:
    return (runs / balls * 100) if balls else 0.0


def economy_rate(runs: int, balls: int) -> float:
    return (runs / balls * 6) if balls else 0.0


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def money(amount: int) -> str:
    return f"{COIN} **{amount:,}**"


def footer_text(extra: str = "") -> str:
    base = config.bot_name
    return f"{base} • {extra}" if extra else base


def embed(title: str = None, description: str = None, color: int = CREAM, footer: str = None) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color)
    e.set_footer(text=footer_text(footer or ""))
    return e


def match_url(match_id: str) -> str:
    if not config.website_url or not match_id:
        return ""
    return f"{config.website_url}/#/match/{match_id}"


def tournament_url(tournament_id) -> str:
    if not config.website_url or not tournament_id:
        return ""
    return f"{config.website_url}/#/tournament/{tournament_id}"


def player_url(user_id) -> str:
    if not config.website_url:
        return ""
    return f"{config.website_url}/#/player/{user_id}"


def truncate(text: str, limit: int = 1024) -> str:
    text = str(text) if text is not None else ""
    if len(text) <= limit:
        return text or "​"
    return text[: limit - 1] + "…"
