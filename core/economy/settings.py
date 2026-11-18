"""Economy values the bot owner can change while the bot is running.

Values live in the `bot_settings` table (keys `eco.<name>`) and are copied over `config.economy`
at start-up and whenever they change, so every part of the bot sees the new value immediately and
it survives restarts. `config.toml` supplies the defaults.
"""
import time

from core.config import config

# name: (kind, min, max, description)
EDITABLE = {
    "start_balance": ("int", 0, 10_000_000, "Coins a new player starts with"),
    "daily": ("int", 0, 1_000_000, "Daily claim"),
    "daily_streak_bonus": ("int", 0, 100_000, "Extra coins per streak day"),
    "daily_streak_cap": ("int", 0, 365, "Streak days that count for the bonus"),
    "weekly": ("int", 0, 10_000_000, "Weekly claim"),
    "participation": ("int", 0, 1_000_000, "Coins for finishing a match"),
    "win": ("int", 0, 1_000_000, "Extra coins for a win"),
    "draw": ("int", 0, 1_000_000, "Extra coins for a draw"),
    "tie": ("int", 0, 1_000_000, "Extra coins for a tie"),
    "per_run": ("int", 0, 10_000, "Coins per run"),
    "per_wicket": ("int", 0, 100_000, "Coins per wicket"),
    "fifty": ("int", 0, 1_000_000, "Bonus for a fifty"),
    "hundred": ("int", 0, 1_000_000, "Bonus for a hundred"),
    "five_wickets": ("int", 0, 1_000_000, "Bonus for five wickets in an innings"),
    "hattrick": ("int", 0, 1_000_000, "Bonus for a hat-trick"),
    "potm": ("int", 0, 1_000_000, "Bonus for Player of the Match"),
    "min_balls_for_rewards": ("int", 0, 10_000, "Shorter matches pay nothing and record no stats"),
    "daily_enabled": ("bool", 0, 1, "Players can claim the daily reward"),
    "weekly_enabled": ("bool", 0, 1, "Players can claim the weekly reward"),
    "give_enabled": ("bool", 0, 1, "Players can send coins to each other"),
    "shop_enabled": ("bool", 0, 1, "Players can buy from the shop"),
    "match_rewards_enabled": ("bool", 0, 1, "Matches pay coins"),
}

_DEFAULTS: dict = {}


def _remember_defaults():
    if not _DEFAULTS:
        _DEFAULTS.update({k: config.economy.get(k) for k in EDITABLE})


def coerce(key: str, value):
    """Validate one value. Returns the clean value or raises ValueError with a user-facing message."""
    if key not in EDITABLE:
        raise ValueError(f"Unknown economy setting `{key}`.")
    kind, lo, hi, _ = EDITABLE[key]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        t = str(value).strip().lower()
        if t in ("1", "on", "true", "yes", "enable", "enabled"):
            return True
        if t in ("0", "off", "false", "no", "disable", "disabled"):
            return False
        raise ValueError(f"`{key}` is a switch: use `on` or `off`.")
    try:
        n = int(str(value).replace(",", "").strip())
    except ValueError:
        raise ValueError(f"`{key}` needs a whole number.")
    if not lo <= n <= hi:
        raise ValueError(f"`{key}` must be between {lo:,} and {hi:,}.")
    return n


async def load(db):
    """Apply saved overrides on top of config.toml."""
    _remember_defaults()
    rows = await db.fetch("SELECT key, value FROM bot_settings WHERE key LIKE 'eco.%'")
    seen = set()
    for r in rows:
        key = r["key"][4:]
        try:
            config.economy[key] = coerce(key, r["value"])
            seen.add(key)
        except ValueError:
            continue
    for key, default in _DEFAULTS.items():      # an override that was removed elsewhere falls back
        if key not in seen:
            config.economy[key] = default


async def set_value(db, key: str, value):
    _remember_defaults()
    clean = coerce(key, value)
    await db.execute(
        "INSERT INTO bot_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        [f"eco.{key}", str(int(clean)) if isinstance(clean, bool) else str(clean), int(time.time())])
    config.economy[key] = clean
    return clean


async def reset_value(db, key: str):
    _remember_defaults()
    if key not in EDITABLE:
        raise ValueError(f"Unknown economy setting `{key}`.")
    await db.execute("DELETE FROM bot_settings WHERE key = ?", [f"eco.{key}"])
    config.economy[key] = _DEFAULTS.get(key)
    return config.economy[key]


def enabled(switch: str) -> bool:
    return bool(config.economy.get(switch, True))
