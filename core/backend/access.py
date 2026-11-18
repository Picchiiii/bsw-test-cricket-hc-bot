"""Server whitelist: the bot only works in servers the owner has allowed.

* `guild_access` (database) is the source of truth; an in-memory copy makes the per-command check free.
* A row is valid while status = 'allowed' and it has not expired (expires_at = 0 means forever).
* The bot owner always passes. In DMs a user passes if they share at least one allowed server with the bot.
* The website's owner panel edits the same table (through the bot), so both always agree.
"""
import logging
import time

from discord.ext import commands

from core.config import config

logger = logging.getLogger(__name__)

# Commands that must work everywhere (so the owner can manage access from any server).
ALWAYS_ALLOWED = {"ping", "owner", "server", "sync"}
DAY = 86400


class GuildNotAllowed(commands.CheckFailure):
    """Raised by the global check when a server is not on the whitelist."""


def _now() -> int:
    return int(time.time())


class Access:
    def __init__(self, bot):
        self.bot = bot
        self.rows: dict[str, dict] = {}
        self.loaded_at = 0
        self._told: dict[int, float] = {}   # channel id -> last time we explained (anti-spam)

    @property
    def enabled(self) -> bool:
        return bool(config.access.get("whitelist_enabled", True))

    # ------------------------------------------------------------- storage
    async def load(self):
        rows = await self.bot.db.fetch("SELECT * FROM guild_access")
        self.rows = {str(r["guild_id"]): r for r in rows}
        # `server whitelist on|off` is remembered across restarts
        saved = await self.bot.db.fetchone("SELECT value FROM bot_settings WHERE key = 'access.whitelist_enabled'")
        if saved is not None:
            config.access["whitelist_enabled"] = str(saved["value"]) == "1"
        self.loaded_at = _now()
        return self.rows

    def row(self, guild_id) -> dict | None:
        return self.rows.get(str(guild_id))

    def is_allowed(self, guild_id) -> bool:
        if not self.enabled:
            return True
        r = self.row(guild_id)
        if not r or r.get("status") != "allowed":
            return False
        exp = r.get("expires_at") or 0
        return not exp or exp > _now()

    def state(self, guild_id) -> str:
        """'allowed' | 'expired' | 'blocked' | 'unlisted' (for messages and lists)."""
        r = self.row(guild_id)
        if not r:
            return "unlisted"
        if r.get("status") != "allowed":
            return "blocked"
        exp = r.get("expires_at") or 0
        if exp and exp <= _now():
            return "expired"
        return "allowed"

    async def allow(self, guild_id, guild_name: str = "", days: int = 0, note: str = "", by=None) -> dict:
        """Allow a server. days = 0 means no expiry."""
        gid = str(guild_id)
        now = _now()
        expires = now + int(days) * DAY if days and int(days) > 0 else 0
        old = self.row(gid) or {}
        name = guild_name or old.get("guild_name") or ""
        await self.bot.db.execute(
            "INSERT INTO guild_access (guild_id, guild_name, status, note, added_by, added_at, expires_at, updated_at) "
            "VALUES (?, ?, 'allowed', ?, ?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET guild_name = excluded.guild_name, "
            "status = 'allowed', note = CASE WHEN excluded.note = '' THEN guild_access.note ELSE excluded.note END, "
            "expires_at = excluded.expires_at, updated_at = excluded.updated_at",
            [gid, name, note or "", str(by) if by else None, now, expires, now])
        await self.load()
        return self.row(gid)

    async def extend(self, guild_id, days: int) -> dict | None:
        """Add days to a server's access (from today if it has already run out)."""
        gid = str(guild_id)
        r = self.row(gid)
        if not r:
            return None
        base = max(r.get("expires_at") or 0, _now())
        await self.bot.db.execute(
            "UPDATE guild_access SET status = 'allowed', expires_at = ?, updated_at = ? WHERE guild_id = ?",
            [base + int(days) * DAY, _now(), gid])
        await self.load()
        return self.row(gid)

    async def revoke(self, guild_id, note: str = "") -> bool:
        gid = str(guild_id)
        if not self.row(gid):
            await self.bot.db.execute(
                "INSERT INTO guild_access (guild_id, guild_name, status, note, added_at, expires_at, updated_at) "
                "VALUES (?, '', 'blocked', ?, ?, 0, ?)", [gid, note or "", _now(), _now()])
        else:
            await self.bot.db.execute(
                "UPDATE guild_access SET status = 'blocked', note = CASE WHEN ? = '' THEN note ELSE ? END, updated_at = ? "
                "WHERE guild_id = ?", [note or "", note or "", _now(), gid])
        await self.load()
        return True

    async def forget(self, guild_id) -> bool:
        res = await self.bot.db.execute("DELETE FROM guild_access WHERE guild_id = ?", [str(guild_id)])
        await self.load()
        return bool(res["affected"])

    # ------------------------------------------------------------- messages
    def contact_text(self) -> str:
        contact = (config.access.get("contact") or "").strip()
        if contact:
            return contact
        owners = list(getattr(self.bot, "owner_ids", None) or [])
        if not owners and getattr(self.bot, "owner_id", None):
            owners = [self.bot.owner_id]
        parts = [f"<@{o}>" for o in owners[:3]]
        text = " or ".join(parts) if parts else "the bot owner"
        if config.support_url:
            text += f" ({config.support_url})"
        return text

    def denied_text(self, guild=None) -> str:
        state = self.state(guild.id) if guild is not None else "unlisted"
        if state == "expired":
            lead = "This server's access to the bot has **expired**."
        elif state == "blocked":
            lead = "This server's access to the bot has been **turned off**."
        else:
            lead = "This server is **not authorised** to use the bot yet."
        gid = f"\n-# Server ID: `{guild.id}`" if guild is not None else ""
        return f"🔒 {lead}\nPlease ask {self.contact_text()} to enable **{config.bot_name}** here.{gid}"

    def should_tell(self, channel_id: int, every: float = 30.0) -> bool:
        """True at most once per `every` seconds per channel, so denied commands can't be used to spam."""
        now = time.time()
        if now - self._told.get(channel_id, 0) < every:
            return False
        self._told[channel_id] = now
        if len(self._told) > 2000:
            self._told = {k: v for k, v in self._told.items() if now - v < every}
        return True

    # ------------------------------------------------------------- the check
    async def user_has_allowed_guild(self, user) -> bool:
        for g in getattr(self.bot, "guilds", []) or []:
            if self.is_allowed(g.id) and g.get_member(user.id) is not None:
                return True
        return False

    async def check(self, ctx) -> bool:
        if not self.enabled:
            return True
        if ctx.command is not None and ctx.command.name in ALWAYS_ALLOWED:
            return True
        if await self.bot.is_owner(ctx.author):
            return True
        if ctx.guild is None:
            if await self.user_has_allowed_guild(ctx.author):
                return True
            raise GuildNotAllowed("dm")
        if self.is_allowed(ctx.guild.id):
            return True
        raise GuildNotAllowed(str(ctx.guild.id))


def install(bot) -> Access:
    """Attach the whitelist to the bot and register the global check + join/leave notices."""
    access = Access(bot)
    bot.access = access
    bot.add_check(access.check)

    async def notify_owner(text: str):
        if not config.access.get("notify_owner_on_join", True):
            return
        owners = list(getattr(bot, "owner_ids", None) or [])
        if not owners and getattr(bot, "owner_id", None):
            owners = [bot.owner_id]
        for oid in owners[:3]:
            try:
                user = bot.get_user(oid) or await bot.fetch_user(oid)
                await user.send(text)
            except Exception:
                pass

    @bot.listen("on_guild_join")
    async def _access_guild_join(guild):
        if not access.enabled:
            return
        row = access.row(guild.id)
        if row and not row.get("guild_name"):
            await bot.db.execute("UPDATE guild_access SET guild_name = ? WHERE guild_id = ?", [guild.name, str(guild.id)])
            await access.load()
        if access.is_allowed(guild.id):
            return
        p = config.prefix
        await notify_owner(
            f"➕ I was added to **{guild.name}** (`{guild.id}`, {getattr(guild, 'member_count', '?')} members) — it is "
            f"**not on the whitelist**.\nAllow it with `{p}server allow {guild.id}` (add a number of days for a "
            f"time-limited pass, e.g. `{p}server allow {guild.id} 30`).")
        channel = getattr(guild, "system_channel", None)
        try:
            if channel is not None:
                await channel.send(access.denied_text(guild))
        except Exception:
            pass
        if config.access.get("leave_unlisted", False):
            try:
                await guild.leave()
            except Exception:
                pass

    return access
