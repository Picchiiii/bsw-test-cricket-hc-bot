"""Bot-owner commands: server whitelist (`server`), economy control (`eco`) and maintenance."""
import time

import discord
from discord.ext import commands

from core.backend.resolve import find_role, find_user, parse_id
from core.config import config
from core.economy import profiles
from core.economy import settings as eco_settings
from core.ui import theme
from core.ui.paginator import send_pages

DAY = 86400


def _when(ts: int) -> str:
    return f"<t:{int(ts)}:D> (<t:{int(ts)}:R>)" if ts else "never"


def owner(bot: commands.Bot):
    p = config.prefix

    @bot.command(name="owner", aliases=["o"], hidden=True)
    @commands.is_owner()
    async def owner_command(ctx: commands.Context):
        e = theme.embed("👑 Owner tools", color=theme.GOLD)
        e.add_field(name="Servers (whitelist)", value=(
            f"`{p}server list` — every server and its access\n"
            f"`{p}server allow [server id] [days] [note]` — allow (no days = forever)\n"
            f"`{p}server revoke [server id] [reason]` — turn access off\n"
            f"`{p}server extend <server id> <days>` • `{p}server info [server id]`\n"
            f"`{p}server forget <server id>` • `{p}server leave <server id>`\n"
            f"`{p}server whitelist on|off` — enforce the whitelist or let every server in"), inline=False)
        e.add_field(name="Economy", value=(
            f"`{p}eco add|remove|set @user <amount> [reason]`\n"
            f"`{p}eco reset @user` • `{p}eco view @user`\n"
            f"`{p}eco role @role <amount> [reason]` — pay everyone with a role\n"
            f"`{p}eco config` — amounts & switches • `{p}eco config <name> <value>`\n"
            f"`{p}eco stats` — coins in circulation"), inline=False)
        e.add_field(name="Maintenance", value=f"`{p}matches` • `{p}dump` • `{p}sync` • `{p}importprofile @user`", inline=False)
        await ctx.send(embed=e)

    @bot.command(name="ping", aliases=["p"], help="Check the bot's latency.")
    async def ping(ctx: commands.Context):
        start_time = time.time()
        message = await ctx.send("Pinging...")
        end_time = time.time()
        latency = (end_time - start_time) * 1000
        ws = bot.latency * 1000 if bot.latency == bot.latency else 0
        await message.edit(content=f"Pong! 🏓 Message: {latency:.0f} ms • Gateway: {ws:.0f} ms")

    @bot.command(name="matches", aliases=["active"], hidden=True)
    @commands.is_owner()
    async def active_matches(ctx: commands.Context):
        if not bot.active_matches:
            await ctx.send("No active matches.")
            return
        lines = []
        for cid, mi in bot.active_matches.items():
            state = mi.phase + (" (paused)" if mi.paused else "") + (" (stumps)" if mi.stumps_called else "")
            tag = " 🏆" if getattr(mi, "tournament", None) else ""
            lines.append(f"<#{cid}> `{mi.match_id}`{tag} • {state} • {len(mi.players)} players • host {mi.host.name}")
        e = theme.embed(f"Active matches ({len(lines)})", theme.truncate("\n".join(lines), 4000), theme.BLUE)
        await ctx.send(embed=e)

    @bot.command(name="sync", hidden=True)
    @commands.is_owner()
    async def sync_tree(ctx: commands.Context):
        synced = await bot.tree.sync()
        await ctx.send(f"Synced {len(synced)} application commands.")

    # ───────────────────────────────────────────────────────────── whitelist
    def _guild_name(gid) -> str:
        g = bot.get_guild(int(gid)) if hasattr(bot, "get_guild") else None
        if g is not None:
            return g.name
        row = bot.access.row(gid)
        return (row or {}).get("guild_name") or "unknown server"

    def _target_guild(ctx, args) -> tuple[int | None, list]:
        """(guild id, remaining args): an explicit ID first, otherwise the server the command is used in."""
        args = list(args)
        if args and str(args[0]).isdigit() and len(str(args[0])) >= 15:
            return int(args.pop(0)), args
        return (ctx.guild.id if ctx.guild else None), args

    @bot.command(name="server", aliases=["servers", "guilds", "whitelist", "wl"], hidden=True)
    @commands.is_owner()
    async def server_cmd(ctx: commands.Context, action: str = "list", *args):
        access = bot.access
        action = (action or "list").lower()
        await access.load()

        if action in ("list", "ls", "all"):
            rows = dict(access.rows)
            lines = []
            icon = {"allowed": "🟢", "expired": "🟠", "blocked": "🔴", "unlisted": "⚪"}
            seen = set()
            for g in sorted(getattr(bot, "guilds", []) or [], key=lambda g: g.name.lower()):
                seen.add(str(g.id))
                st = access.state(g.id)
                exp = (rows.get(str(g.id)) or {}).get("expires_at") or 0
                lines.append(f"{icon[st]} **{g.name}** `{g.id}` — {st}"
                             + (f", until <t:{exp}:D>" if exp and st == "allowed" else "")
                             + f" • {getattr(g, 'member_count', '?')} members")
            for gid, r in rows.items():
                if gid in seen:
                    continue
                st = access.state(gid)
                lines.append(f"{icon[st]} *{r.get('guild_name') or 'unknown'}* `{gid}` — {st} (bot not in server)")
            if not lines:
                await ctx.send("I'm not in any servers and the whitelist is empty.")
                return
            head = (f"Whitelist is **{'ON' if access.enabled else 'OFF (every server can use the bot)'}**.\n"
                    f"🟢 allowed 🟠 expired 🔴 blocked ⚪ not listed\n")
            pages = []
            for i in range(0, len(lines), 15):
                pages.append(theme.embed(f"🌐 Servers ({len(lines)})", head + "\n".join(lines[i:i + 15]), theme.BLUE))
            await send_pages(ctx, pages)
            return

        if action in ("whitelist", "enforce"):
            value = (args[0].lower() if args else "")
            if value not in ("on", "off"):
                await ctx.send(f"Whitelist is **{'ON' if access.enabled else 'OFF'}**. Use `{p}server whitelist on|off`.")
                return
            config.access["whitelist_enabled"] = value == "on"
            await bot.db.execute(
                "INSERT INTO bot_settings (key, value, updated_at) VALUES ('access.whitelist_enabled', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                ["1" if value == "on" else "0", int(time.time())])
            await ctx.send("🔒 Whitelist **ON** — only allowed servers can use the bot." if value == "on"
                           else "🔓 Whitelist **OFF** — every server can use the bot.")
            return

        gid, rest = _target_guild(ctx, args)
        if gid is None:
            await ctx.send(f"Give a server ID, e.g. `{p}server {action} 123456789012345678`.")
            return

        if action in ("allow", "add", "approve", "enable"):
            days = 0
            if rest and str(rest[0]).isdigit():
                days = int(rest.pop(0))
            note = " ".join(rest)[:200]
            row = await access.allow(gid, _guild_name(gid) if _guild_name(gid) != "unknown server" else "", days, note,
                                     by=ctx.author.id)
            await ctx.send(f"{theme.TICK} **{_guild_name(gid)}** (`{gid}`) can now use the bot"
                           + (f" until {_when(row['expires_at'])}." if row.get("expires_at") else " with no time limit."))
        elif action in ("revoke", "remove", "block", "deny", "disable"):
            await access.revoke(gid, " ".join(rest)[:200])
            await ctx.send(f"🔴 **{_guild_name(gid)}** (`{gid}`) can no longer use the bot.")
        elif action == "extend":
            if not rest or not str(rest[0]).lstrip("-").isdigit():
                await ctx.send(f"Usage: `{p}server extend <server id> <days>`")
                return
            row = await access.extend(gid, int(rest[0]))
            if row is None:
                await ctx.send(f"That server isn't on the list yet. Use `{p}server allow {gid} {rest[0]}`.")
                return
            await ctx.send(f"{theme.TICK} **{_guild_name(gid)}** now has access until {_when(row['expires_at'])}.")
        elif action in ("forget", "delete"):
            ok = await access.forget(gid)
            await ctx.send(f"Removed `{gid}` from the list." if ok else "That server wasn't on the list.")
        elif action == "leave":
            g = bot.get_guild(gid) if hasattr(bot, "get_guild") else None
            if g is None:
                await ctx.send("I'm not in that server.")
                return
            await g.leave()
            await ctx.send(f"👋 Left **{g.name}**.")
        elif action in ("info", "show", "status"):
            row = access.row(gid) or {}
            st = access.state(gid)
            g = bot.get_guild(gid) if hasattr(bot, "get_guild") else None
            e = theme.embed(f"🌐 {_guild_name(gid)}", color=theme.GREEN if st == "allowed" else theme.RED)
            e.add_field(name="Server ID", value=f"`{gid}`")
            e.add_field(name="Access", value=st if access.enabled else f"{st} (whitelist is off)")
            e.add_field(name="Expires", value=_when(row.get("expires_at") or 0))
            e.add_field(name="Bot in server", value="yes" if g is not None else "no")
            if g is not None:
                e.add_field(name="Members", value=str(getattr(g, "member_count", "?")))
            if row.get("added_at"):
                e.add_field(name="Listed", value=f"<t:{row['added_at']}:D>")
            if row.get("note"):
                e.add_field(name="Note", value=theme.truncate(row["note"]), inline=False)
            await ctx.send(embed=e)
        else:
            await ctx.send(f"Unknown action. See `{p}owner`.")

    # ───────────────────────────────────────────────────────────── economy
    async def _amount(ctx, text) -> int | None:
        try:
            n = int(str(text).replace(",", "").replace("_", ""))
        except (TypeError, ValueError):
            await ctx.send("The amount must be a whole number.")
            return None
        if n < 0 or n > 1_000_000_000:
            await ctx.send("The amount must be between 0 and 1,000,000,000.")
            return None
        return n

    async def _eco_user(ctx, text):
        user = await find_user(bot, text)
        if user is None and ctx.guild is not None:
            from core.backend.resolve import find_member
            user = await find_member(ctx.guild, text)
        if user is None:
            await ctx.send("I couldn't find that user. Mention them or use their ID.")
        elif user.bot:
            await ctx.send("Bots don't have wallets.")
            return None
        return user

    @bot.command(name="eco", aliases=["economy", "ecoadmin"], hidden=True)
    @commands.is_owner()
    async def eco_cmd(ctx: commands.Context, action: str = None, *args):
        action = (action or "help").lower()
        args = list(args)

        if action in ("add", "give", "remove", "take", "set"):
            if len(args) < 2:
                await ctx.send(f"Usage: `{p}eco {action} @user <amount> [reason]`")
                return
            user = await _eco_user(ctx, args[0])
            if user is None:
                return
            amount = await _amount(ctx, args[1])
            if amount is None:
                return
            note = " ".join(args[2:])[:120]
            reason = f"owner {action} by {ctx.author.id}" + (f": {note}" if note else "")
            await profiles.ensure_profile(bot.db, user)
            if action == "set":
                old, new = await profiles.set_coins(bot.db, user.id, amount, reason)
            else:
                delta = amount if action in ("add", "give") else -amount
                old, new = await profiles.adjust_coins(bot.db, user.id, delta, reason)
            await ctx.send(f"{theme.TICK} **{user.name}**: {theme.money(old)} → {theme.money(new)}"
                           + (f"\n-# {note}" if note else ""))
            return

        if action == "reset":
            if not args:
                await ctx.send(f"Usage: `{p}eco reset @user`")
                return
            user = await _eco_user(ctx, args[0])
            if user is None:
                return
            await profiles.ensure_profile(bot.db, user)
            old, new = await profiles.set_coins(bot.db, user.id, config.economy["start_balance"],
                                                f"owner reset by {ctx.author.id}")
            await ctx.send(f"{theme.TICK} **{user.name}**'s wallet was reset: {theme.money(old)} → {theme.money(new)}")
            return

        if action in ("view", "show", "history", "wallet"):
            if not args:
                await ctx.send(f"Usage: `{p}eco view @user`")
                return
            user = await _eco_user(ctx, args[0])
            if user is None:
                return
            row = await profiles.ensure_profile(bot.db, user)
            tx = await bot.db.fetch("SELECT amount, reason, created_at FROM transactions WHERE userid = ? "
                                    "ORDER BY id DESC LIMIT 12", [str(user.id)])
            lines = [f"`{t['amount']:+,}` {t['reason']} • <t:{t['created_at']}:R>" for t in tx] or ["No transactions."]
            e = theme.embed(f"💼 {user.name}", f"Balance {theme.money(row['coins'])} • earned in total "
                                              f"{row['total_earned']:,}\n\n" + "\n".join(lines), theme.GOLD)
            await ctx.send(embed=e)
            return

        if action == "role":
            if len(args) < 2 or ctx.guild is None:
                await ctx.send(f"Usage (in a server): `{p}eco role @role <amount> [reason]`")
                return
            role = find_role(ctx.guild, args[0])
            if role is None:
                await ctx.send("I couldn't find that role.")
                return
            amount = await _amount(ctx, args[1])
            if amount is None:
                return
            note = " ".join(args[2:])[:120]
            members = [m for m in getattr(role, "members", []) if not m.bot]
            if not members:
                await ctx.send("Nobody has that role.")
                return
            for m in members:
                await profiles.ensure_profile(bot.db, m)
                await profiles.add_coins(bot.db, m.id, amount, f"owner grant to role {role.id} by {ctx.author.id}"
                                         + (f": {note}" if note else ""))
            await ctx.send(f"{theme.TICK} Gave {theme.money(amount)} to **{len(members)}** member(s) with **{role.name}**.")
            return

        if action in ("config", "settings", "cfg"):
            if not args:
                e = theme.embed("⚙️ Economy settings", color=theme.GOLD)
                amounts, switches = [], []
                for key, (kind, lo, hi, desc) in eco_settings.EDITABLE.items():
                    cur = config.economy.get(key)
                    if kind == "bool":
                        switches.append(f"`{key}` — **{'on' if cur else 'off'}** • {desc}")
                    else:
                        amounts.append(f"`{key}` — **{cur:,}** • {desc}")
                e.add_field(name="Amounts", value=theme.truncate("\n".join(amounts)), inline=False)
                e.add_field(name="Switches", value=theme.truncate("\n".join(switches)), inline=False)
                e.set_footer(text=theme.footer_text(f"{p}eco config <name> <value> • {p}eco config reset <name>"))
                await ctx.send(embed=e)
                return
            try:
                if args[0].lower() == "reset":
                    if len(args) < 2:
                        await ctx.send(f"Usage: `{p}eco config reset <name>`")
                        return
                    value = await eco_settings.reset_value(bot.db, args[1].lower())
                    await ctx.send(f"{theme.TICK} `{args[1].lower()}` is back to its default: **{value}**.")
                    return
                if len(args) < 2:
                    await ctx.send(f"Usage: `{p}eco config <name> <value>`")
                    return
                value = await eco_settings.set_value(bot.db, args[0].lower(), args[1])
            except ValueError as err:
                await ctx.send(str(err))
                return
            shown = ("on" if value else "off") if isinstance(value, bool) else f"{value:,}"
            await ctx.send(f"{theme.TICK} `{args[0].lower()}` is now **{shown}**.")
            return

        if action in ("stats", "total", "supply"):
            row = await bot.db.fetchone("SELECT COUNT(*) AS n, COALESCE(SUM(coins), 0) AS coins, "
                                        "COALESCE(MAX(coins), 0) AS top FROM profiles")
            top = await bot.db.fetch("SELECT name, coins FROM profiles ORDER BY coins DESC LIMIT 5")
            e = theme.embed("🏦 Economy", f"Wallets: **{row['n']:,}**\nCoins in circulation: {theme.money(row['coins'])}",
                            theme.GOLD)
            if top:
                e.add_field(name="Richest", value="\n".join(f"**{t['name']}** — {t['coins']:,}" for t in top))
            await ctx.send(embed=e)
            return

        await ctx.send(f"See `{p}owner` for the economy commands.")

    # kept for compatibility with earlier versions
    @bot.command(name="addcoins", hidden=True)
    @commands.is_owner()
    async def add_coins(ctx: commands.Context, user: discord.User, amount: int):
        await profiles.ensure_profile(bot.db, user)
        await profiles.add_coins(bot.db, user.id, amount, f"owner adjustment by {ctx.author.id}")
        await ctx.send(f"Added {theme.money(amount)} to **{user.name}**.")

    @bot.command(name="removecoins", hidden=True)
    @commands.is_owner()
    async def remove_coins(ctx: commands.Context, user: discord.User, amount: int):
        await profiles.ensure_profile(bot.db, user)
        await bot.db.execute("UPDATE profiles SET coins = MAX(0, coins - ?) WHERE userid = ?", [amount, str(user.id)])
        await bot.db.execute("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
                             [str(user.id), -amount, f"owner adjustment by {ctx.author.id}", int(time.time())])
        await ctx.send(f"Removed {theme.money(amount)} from **{user.name}**.")
