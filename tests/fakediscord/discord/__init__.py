"""A small, test-only stand-in for discord.py.

It implements the subset of the discord.py 2.x API the bot uses, with the same names and call
signatures, and enforces Discord's real limits (embed sizes, select options, view rows) so that tests
fail the same way a real send would. Messages, DMs and interactions are recorded for assertions.
"""
import asyncio
import datetime
import itertools

from . import abc, utils, ui, app_commands  # noqa: F401

_ids = itertools.count(10_000_000_000_000_000)


def next_id():
    return next(_ids)


# ───────────────────────────────────────────────────────── errors
class DiscordException(Exception):
    pass


class HTTPException(DiscordException):
    def __init__(self, response=None, message=""):
        super().__init__(message)
        self.response = response
        self.text = message
        self.status = getattr(response, "status", 400)


class Forbidden(HTTPException):
    pass


class NotFound(HTTPException):
    pass


# ───────────────────────────────────────────────────────── basics
class Colour:
    def __init__(self, value):
        self.value = value

    @classmethod
    def blue(cls): return cls(0x3498DB)

    @classmethod
    def red(cls): return cls(0xE74C3C)

    @classmethod
    def green(cls): return cls(0x2ECC71)

    @classmethod
    def gold(cls): return cls(0xF1C40F)


Color = Colour


class ButtonStyle:
    primary = blurple = 1
    secondary = grey = gray = 2
    success = green = 3
    danger = red = 4
    link = url = 5


class Intents:
    def __init__(self):
        self.message_content = False
        self.members = False
        self.guilds = True
        self.dm_messages = True

    @classmethod
    def default(cls):
        return cls()


class Game:
    def __init__(self, name):
        self.name = name


class AllowedMentions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @classmethod
    def none(cls):
        return cls(everyone=False, users=False, roles=False)


class Permissions:
    def __init__(self, **kwargs):
        self.administrator = kwargs.get("administrator", False)
        self.manage_guild = kwargs.get("manage_guild", False)
        self.manage_roles = kwargs.get("manage_roles", False)


class Role:
    def __init__(self, guild, name, *, managed=False, position=1):
        self.id = next_id()
        self.guild = guild
        self.name = name
        self.managed = managed
        self.position = position
        self.color = Colour(0)
        self.mention = f"<@&{self.id}>"
        self.deleted = False
        guild.roles.append(self)

    @property
    def members(self):
        return [m for m in self.guild.members if self in m.roles]

    def is_default(self):
        return False

    async def delete(self, reason=None):
        if self.guild.forbid_roles:
            raise Forbidden(message="Missing Permissions")
        self.deleted = True
        if self in self.guild.roles:
            self.guild.roles.remove(self)
        for m in self.guild.members:
            if self in m.roles:
                m.roles.remove(self)

    async def edit(self, *, name=None, **kwargs):
        if name is not None:
            self.name = name


class File:
    def __init__(self, fp, filename=None):
        self.fp = fp
        self.filename = filename


class SelectOption:
    def __init__(self, *, label, value=None, description=None, emoji=None, default=False):
        if not label or len(label) > 100:
            raise ValueError("SelectOption label must be 1-100 chars")
        if description is not None and len(description) > 100:
            raise ValueError("SelectOption description must be <= 100 chars")
        self.label = label
        self.value = value if value is not None else label
        self.description = description
        self.emoji = emoji
        self.default = default


class _Field:
    def __init__(self, name, value, inline):
        self.name, self.value, self.inline = name, value, inline


class _Footer:
    def __init__(self, text=None, icon_url=None):
        self.text, self.icon_url = text, icon_url


class Embed:
    def __init__(self, *, title=None, description=None, color=None, colour=None, url=None, timestamp=None):
        self.title = title
        self.description = description
        self.color = color if color is not None else colour
        self.url = url
        self.timestamp = timestamp
        self.fields = []
        self.footer = _Footer()
        self.thumbnail = None
        self.image = None
        self.author = None

    def add_field(self, *, name, value, inline=True):
        self.fields.append(_Field(name, value, inline))
        return self

    def set_footer(self, *, text=None, icon_url=None):
        self.footer = _Footer(text, icon_url)
        return self

    def set_image(self, *, url):
        self.image = url
        return self

    def set_thumbnail(self, *, url):
        self.thumbnail = url
        return self

    def set_author(self, *, name, url=None, icon_url=None):
        self.author = name
        return self

    def validate(self):
        total = 0

        def chk(val, limit, what):
            nonlocal total
            if val is None:
                return
            s = str(val)
            if len(s) > limit:
                raise HTTPException(message=f"Embed {what} too long ({len(s)} > {limit})")
            total += len(s)

        chk(self.title, 256, "title")
        chk(self.description, 4096, "description")
        if len(self.fields) > 25:
            raise HTTPException(message="Embed has more than 25 fields")
        for f in self.fields:
            if not str(f.name).strip() or not str(f.value).strip():
                raise HTTPException(message=f"Embed field name/value must not be empty ({f.name!r})")
            chk(f.name, 256, "field name")
            chk(f.value, 1024, "field value")
        chk(self.footer.text, 2048, "footer")
        if total > 6000:
            raise HTTPException(message=f"Embed total length {total} > 6000")
        if self.color is not None and not isinstance(self.color, (int, Colour)):
            raise HTTPException(message="bad colour")

    def text(self):
        parts = [self.title or "", self.description or ""]
        for f in self.fields:
            parts += [str(f.name), str(f.value)]
        parts.append(self.footer.text or "")
        return "\n".join(parts)


class _Asset:
    def __init__(self, url):
        self.url = url


# ───────────────────────────────────────────────────────── messages & channels
class Message:
    def __init__(self, *, channel, author, content=None, embed=None, embeds=None, view=None, files=None):
        self.id = next_id()
        self.channel = channel
        self.author = author
        self.content = content
        self.embeds = list(embeds or ([embed] if embed is not None else []))
        self.view = view
        self.files = files or []
        self.reactions = []
        self.deleted = False
        self.edits = 0
        self.created_at = utils.utcnow()
        self.attachments = []
        self.guild = getattr(channel, "guild", None)
        self.jump_url = f"https://discord.com/channels/{getattr(self.guild, 'id', '@me')}/{channel.id}/{self.id}"

    @property
    def embed(self):
        return self.embeds[0] if self.embeds else None

    async def edit(self, *, content=..., embed=..., embeds=..., view=..., **kwargs):
        if self.deleted:
            raise NotFound(message="Unknown Message")
        if content is not ...:
            self.content = content
        if embed is not ...:
            if embed is not None:
                embed.validate()
            self.embeds = [embed] if embed is not None else []
        if embeds is not ...:
            self.embeds = list(embeds)
        if view is not ...:
            if view is not None:
                view._attach(self)
            self.view = view
        self.edits += 1
        await asyncio.sleep(0)
        return self

    async def delete(self):
        if self.deleted:
            raise NotFound(message="Unknown Message")
        self.deleted = True
        await asyncio.sleep(0)

    async def reply(self, content=None, **kwargs):
        return await self.channel.send(content, **kwargs)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)
        await asyncio.sleep(0)

    def text(self):
        return "\n".join([self.content or ""] + [e.text() for e in self.embeds])


class _Messageable:
    def __init__(self):
        self.messages: list[Message] = []
        self.listeners = []

    def _sender(self):
        return getattr(self, "_bot_user", None)

    async def send(self, content=None, *, embed=None, embeds=None, view=None, file=None, files=None, **kwargs):
        if getattr(self, "forbidden", False):
            raise Forbidden(message="Cannot send messages to this user")
        for e in ([embed] if embed is not None else []) + list(embeds or []):
            e.validate()
        if content is not None and len(str(content)) > 2000:
            raise HTTPException(message="content > 2000")
        if content is None and embed is None and not embeds and file is None and not files:
            raise HTTPException(message="Cannot send an empty message")
        msg = Message(channel=self, author=self._sender(), content=content, embed=embed, embeds=embeds,
                      view=view, files=[file] if file else files)
        if view is not None:
            view._attach(msg)
        self.messages.append(msg)
        for listener in list(self.listeners):
            res = listener(msg)
            if asyncio.iscoroutine(res):
                asyncio.ensure_future(res)
        await asyncio.sleep(0)
        return msg

    def all_text(self):
        return "\n".join(m.text() for m in self.messages)


class Guild:
    def __init__(self, name="Test Guild"):
        self.id = next_id()
        self.name = name
        self.members = []
        self.channels = []
        self.roles = []
        self.owner_id = None
        self.icon = None
        self.system_channel = None
        self.forbid_roles = False     # simulate "Missing Permissions" for role management
        self.left = False

    @property
    def member_count(self):
        return len(self.members)

    @property
    def text_channels(self):
        return list(self.channels)

    def get_role(self, role_id):
        for r in self.roles:
            if r.id == role_id:
                return r
        return None

    def get_channel(self, channel_id):
        for c in self.channels:
            if c.id == channel_id:
                return c
        return None

    async def create_role(self, *, name, mentionable=False, reason=None, **kwargs):
        if self.forbid_roles:
            raise Forbidden(message="Missing Permissions")
        return Role(self, name)

    async def leave(self):
        self.left = True

    def get_member(self, user_id):
        for m in self.members:
            if m.id == user_id:
                return m
        return None

    async def fetch_member(self, user_id):
        m = self.get_member(user_id)
        if m is None:
            raise NotFound(message="Unknown Member")
        return m


class TextChannel(_Messageable):
    def __init__(self, guild, name="general", bot_user=None):
        super().__init__()
        self.id = next_id()
        self.guild = guild
        self.name = name
        self._bot_user = bot_user
        self.mention = f"<#{self.id}>"
        self.jump_url = f"https://discord.com/channels/{guild.id}/{self.id}"
        guild.channels.append(self)


class DMChannel(_Messageable):
    def __init__(self, recipient, bot_user=None):
        super().__init__()
        self.id = next_id()
        self.recipient = recipient
        self.guild = None
        self._bot_user = bot_user


class User(abc.User):
    def __init__(self, name, *, bot=False, user_id=None):
        self.id = user_id or next_id()
        self.name = name
        self.display_name = name
        self.global_name = name
        self.bot = bot
        self.mention = f"<@{self.id}>"
        self.display_avatar = _Asset(f"https://cdn.example/avatars/{self.id}.png")
        self.dm_channel = DMChannel(self)
        self.forbidden_dm = False

    async def send(self, content=None, **kwargs):
        self.dm_channel.forbidden = self.forbidden_dm
        return await self.dm_channel.send(content, **kwargs)

    def __eq__(self, other):
        return isinstance(other, abc.User) and other.id == self.id

    def __hash__(self):
        return hash(self.id) >> 22

    def __repr__(self):
        return f"<User {self.name}>"


class Member(User):
    def __init__(self, name, guild, **kw):
        super().__init__(name, **kw)
        self.guild = guild
        self.roles = []
        self.guild_permissions = Permissions()
        guild.members.append(self)

    async def add_roles(self, *roles, reason=None):
        if self.guild.forbid_roles:
            raise Forbidden(message="Missing Permissions")
        for r in roles:
            if r not in self.roles:
                self.roles.append(r)

    async def remove_roles(self, *roles, reason=None):
        if self.guild.forbid_roles:
            raise Forbidden(message="Missing Permissions")
        for r in roles:
            if r in self.roles:
                self.roles.remove(r)


class Webhook:
    @classmethod
    def from_url(cls, url, session=None):
        return cls()

    async def send(self, **kwargs):
        return None


# ───────────────────────────────────────────────────────── interactions
class _Response:
    def __init__(self, interaction):
        self._i = interaction
        self._done = False
        self.sent = []

    def is_done(self):
        return self._done

    def _mark(self):
        if self._done:
            raise HTTPException(message="Interaction has already been acknowledged.")
        self._done = True

    async def defer(self, **kwargs):
        self._mark()

    async def send_message(self, content=None, *, embed=None, view=None, ephemeral=False, **kwargs):
        self._mark()
        if embed is not None:
            embed.validate()
        self.sent.append({"content": content, "embed": embed, "ephemeral": ephemeral})

    async def edit_message(self, *, content=..., embed=..., view=..., **kwargs):
        self._mark()
        if self._i.message is not None:
            await self._i.message.edit(content=content, embed=embed, view=view)


class _Followup:
    def __init__(self, interaction):
        self._i = interaction
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


class Interaction:
    def __init__(self, *, user, channel, client, message=None):
        self.user = user
        self.channel = channel
        self.guild = getattr(channel, "guild", None)
        self.client = client
        self.message = message
        self.response = _Response(self)
        self.followup = _Followup(self)
