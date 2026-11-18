"""Turn text typed after a command (mention, ID or name) into members, users, roles and channels."""
import re

_ID = re.compile(r"(\d{15,21})")


def parse_id(text) -> int | None:
    """ID from a raw number or any mention form: <@1>, <@!1>, <@&1>, <#1>."""
    if text is None:
        return None
    if isinstance(text, int):
        return text
    m = _ID.search(str(text))
    return int(m.group(1)) if m else None


def _norm(s) -> str:
    return str(s or "").strip().lower()


async def find_member(guild, text):
    """Member of `guild` from a mention, ID, username or display name (case-insensitive)."""
    if guild is None or text is None:
        return None
    if hasattr(text, "id") and hasattr(text, "name"):
        return text
    uid = parse_id(text)
    if uid is not None:
        m = guild.get_member(uid)
        if m is None:
            try:
                m = await guild.fetch_member(uid)
            except Exception:
                m = None
        if m is not None:
            return m
    want = _norm(text).lstrip("@")
    if not want:
        return None
    for m in getattr(guild, "members", []) or []:
        if want in (_norm(m.name), _norm(getattr(m, "display_name", "")), _norm(getattr(m, "global_name", ""))):
            return m
    return None


async def find_user(bot, text):
    """Any Discord user by mention or ID (they don't have to share a server with the bot)."""
    if text is None:
        return None
    if hasattr(text, "id") and hasattr(text, "name"):
        return text
    uid = parse_id(text)
    if uid is None:
        return None
    user = bot.get_user(uid)
    if user is None:
        try:
            user = await bot.fetch_user(uid)
        except Exception:
            user = None
    return user


def find_role(guild, text):
    if guild is None or text is None:
        return None
    if hasattr(text, "id") and hasattr(text, "name"):
        return text
    rid = parse_id(text)
    if rid is not None:
        role = guild.get_role(rid)
        if role is not None:
            return role
    want = _norm(text).lstrip("@")
    for role in getattr(guild, "roles", []) or []:
        if _norm(role.name) == want:
            return role
    return None


def find_channel(guild, text):
    if guild is None or text is None:
        return None
    if hasattr(text, "id") and hasattr(text, "send"):
        return text
    cid = parse_id(text)
    if cid is not None:
        ch = guild.get_channel(cid)
        if ch is not None:
            return ch
    want = _norm(text).lstrip("#")
    for ch in getattr(guild, "text_channels", None) or getattr(guild, "channels", []) or []:
        if _norm(getattr(ch, "name", "")) == want:
            return ch
    return None


def to_bool(text) -> bool | None:
    t = _norm(text)
    if t in ("1", "on", "true", "yes", "y", "enable", "enabled"):
        return True
    if t in ("0", "off", "false", "no", "n", "disable", "disabled"):
        return False
    return None
