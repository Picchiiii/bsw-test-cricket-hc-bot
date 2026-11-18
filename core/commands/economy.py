"""Profiles, stats, leaderboards and the coin economy.

Command names and aliases follow the HandCricket bot (profile/me, userstats, leaderboard/lb, matchlog)
so players moving between the two feel at home; economy commands follow common Discord conventions.
"""
import io
import json
import time
import discord
from discord.ext import commands

from core.config import config
from core.economy import profiles
from core.economy.shop import ITEMS, find_item
from core.ui import theme
from core.ui.paginator import send_pages

ECO = config.economy
DAY = 24 * 3600

LEADERBOARDS = {
    "runs": ("runs", "Most runs", lambda r: f"{r['runs']:,} runs"),
    "wickets": ("wickets", "Most wickets", lambda r: f"{r['wickets']:,} wkts"),
    "coins": ("coins", f"Richest players", lambda r: f"{theme.COIN} {r['coins']:,}"),
    "wins": ("matches_won", "Most wins", lambda r: f"{r['matches_won']} wins / {r['matches_played']}"),
    "matches": ("matches_played", "Most matches", lambda r: f"{r['matches_played']} matches"),
    "average": ("batting_average", "Best batting average", lambda r: f"avg {r['batting_average']:.2f} ({r['runs']} runs)"),
    "highest": ("highest_score", "Highest scores", lambda r: f"HS {r['highest_score']}"),
    "hattricks": ("hattricks", "Most hat-tricks", lambda r: f"{r['hattricks']} hat-tricks"),
    "sixes": ("sixes", "Most sixes", lambda r: f"{r['sixes']} sixes"),
    "potm": ("potm", "Most Player of the Match awards", lambda r: f"{r['potm']} awards"),
}
LB_ALIASES = {"run": "runs", "r": "runs", "wicket": "wickets", "wkts": "wickets", "w": "wickets", "bal": "coins",
              "money": "coins", "c": "coins", "win": "wins", "avg": "average", "hs": "highest", "6s": "sixes",
              "mom": "potm", "motm": "potm"}


def _color(row) -> int:
    try:
        return int(row.get("color") or "", 16)
    except ValueError:
        return theme.CREAM


def _badges(row) -> str:
    try:
        return " ".join(json.loads(row.get("badges") or "[]"))
    except Exception:
        return ""


def economy(bot: commands.Bot):

    async def db_profile(user):
        return await profiles.ensure_profile(bot.db, user)

    # ─────────────────────────────────────────────── profile & stats
    @bot.command(name="profile", aliases=["me"], help="Your hand cricket profile (or someone else's).")
    async def profile(ctx: commands.Context, user: discord.User = None):
        user = user or ctx.author
        if user.bot:
            user = ctx.author
        row = await db_profile(user)
        e = discord.Embed(title=f"{user.name}'s Profile", color=_color(row))
        e.set_thumbnail(url=user.display_avatar.url)
        head = []
        if row.get("title"):
            head.append(f"🎖️ **{row['title']}**")
        if _badges(row):
            head.append(_badges(row))
        if row.get("description"):
            head.append(f"*{row['description']}*")
        e.description = "\n".join(head) or None
        played = row["matches_played"] or 0
        win_pct = (row["matches_won"] / played * 100) if played else 0
        e.add_field(name="Matches Played", value=f"{played}", inline=True)
        e.add_field(name="Matches Won", value=f"{row['matches_won']} ({win_pct:.0f}%)", inline=True)
        e.add_field(name="Matches Lost", value=f"{row['matches_lost']}", inline=True)
        e.add_field(name="Drawn / Tied", value=f"{row['matches_drawn']} / {row['matches_tied']}", inline=True)
        e.add_field(name="Runs", value=f"{row['runs']:,}", inline=True)
        e.add_field(name="Balls", value=f"{row['balls']:,}", inline=True)
        e.add_field(name="Wickets", value=f"{row['wickets']}", inline=True)
        e.add_field(name="Wickets Lost", value=f"{row['wickets_lost']}", inline=True)
        e.add_field(name="Highest Score", value=f"{row['highest_score']}", inline=True)
        e.add_field(name="Hattricks", value=f"{row['hattricks']}", inline=True)
        e.add_field(name="Ducks", value=f"{row['ducks']}", inline=True)
        e.add_field(name="Batting Average", value=f"{row['batting_average']:.2f}", inline=True)
        e.add_field(name=theme.CURRENCY, value=theme.money(row["coins"]), inline=True)
        e.add_field(name="Player of the Match", value=f"{row['potm']}", inline=True)
        url = theme.player_url(user.id)
        if url:
            e.url = url
        e.set_footer(text=theme.footer_text(f"{config.prefix}userstats for in-depth stats"))
        await ctx.send(embed=e)

    @bot.command(name="userstats", aliases=["us", "stats"], help="In-depth batting & bowling stats.")
    async def userstats(ctx: commands.Context, user: discord.User = None):
        user = user or ctx.author
        row = await db_profile(user)
        inns = row["innings_batted"] or 0
        e = discord.Embed(title=f"📊 {user.name} — detailed stats", color=_color(row))
        e.set_thumbnail(url=user.display_avatar.url)
        sr = theme.strike_rate(row["runs"], row["balls"])
        e.add_field(name=f"{theme.BAT} Batting", value=(
            f"Innings: **{inns}** • Not outs: **{row['not_outs']}**\n"
            f"Runs: **{row['runs']:,}** • HS: **{row['highest_score']}**\n"
            f"Average: **{row['batting_average']:.2f}** • SR: **{sr:.2f}**\n"
            f"50s / 100s: **{row['fifties']} / {row['hundreds']}**\n"
            f"4s / 6s: **{row['fours']} / {row['sixes']}** • Ducks: **{row['ducks']}**"), inline=False)
        bb = row["balls_bowled"] or 0
        wk = row["wickets"] or 0
        bowl_avg = (row["runs_conceded"] / wk) if wk else 0
        bowl_sr = (bb / wk) if wk else 0
        best = f"{row['best_bowling_wickets']}/{row['best_bowling_runs']}" if bb else "-"
        e.add_field(name=f"{theme.BALL} Bowling", value=(
            f"Overs: **{theme.overs_str(bb)}** • Maidens: **{row['maidens']}**\n"
            f"Wickets: **{wk}** • Best: **{best}** • 5W: **{row['five_wickets']}**\n"
            f"Average: **{bowl_avg:.2f}** • Economy: **{theme.economy_rate(row['runs_conceded'], bb):.2f}** • SR: **{bowl_sr:.1f}**\n"
            f"Hat-tricks: **{row['hattricks']}** • No-balls: **{row['no_balls']}**"), inline=False)
        played = row["matches_played"] or 0
        e.add_field(name="🏆 Results", value=(
            f"Played **{played}** • Won **{row['matches_won']}** • Lost **{row['matches_lost']}** • "
            f"Drawn **{row['matches_drawn']}** • Tied **{row['matches_tied']}**\n"
            f"Win rate: **{(row['matches_won'] / played * 100) if played else 0:.1f}%** • POTM: **{row['potm']}**"),
            inline=False)
        url = theme.player_url(user.id)
        if url:
            e.url = url
        await ctx.send(embed=e)

    @bot.command(name="matchlog", aliases=["ml", "history"], help="Your recent matches.")
    async def matchlog(ctx: commands.Context, user: discord.User = None):
        user = user or ctx.author
        rows = await bot.db.fetch(
            "SELECT p.*, m.team_a, m.team_b, m.result_text FROM player_match_stats p LEFT JOIN matches m "
            "ON m.match_id = p.match_id WHERE p.userid = ? ORDER BY p.created_at DESC LIMIT 50", [str(user.id)])
        if not rows:
            await ctx.send(f"**{user.name}** hasn't finished a match yet.")
            return
        pages = []
        icon = {"WIN": "🟢", "LOSS": "🔴", "DRAW": "⚪", "TIE": "🟡"}
        for i in range(0, len(rows), 5):
            e = discord.Embed(title=f"📜 {user.name}'s match log", color=theme.CREAM)
            for r in rows[i:i + 5]:
                e.add_field(
                    name=f"{icon.get(r['result'], '•')} {r['team_a']} v {r['team_b']} — {r['result']}",
                    value=(f"Bat **{r['runs']}** ({r['balls']}) • Bowl **{r['wickets']}/{r['runs_conceded']}** "
                           f"({theme.overs_str(r['balls_bowled'])})"
                           f"{' • 🌟 POTM' if r['potm'] else ''} • +{r['coins']} {theme.COIN}\n"
                           f"-# {r['result_text'] or ''} • <t:{r['created_at']}:R> • `{r['match_id']}`"),
                    inline=False)
            pages.append(e)
        await send_pages(ctx, pages)

    @bot.command(name="setdesc", aliases=["description", "bio"], help="Set the description on your profile.")
    async def set_description(ctx: commands.Context, *, text: str = ""):
        await db_profile(ctx.author)
        text = discord.utils.escape_mentions(text.strip())[:150]
        await bot.db.execute("UPDATE profiles SET description = ? WHERE userid = ?", [text, str(ctx.author.id)])
        await ctx.send("Profile description " + ("updated ✏️" if text else "cleared."))

    @bot.command(name="leaderboard", aliases=["lb", "top"],
                 help="Leaderboards: runs, wickets, coins, wins, matches, average, highest, hattricks, sixes, potm. Add 'server' for this server only.")
    async def leaderboard(ctx: commands.Context, category: str = "runs", scope: str = "global"):
        category = LB_ALIASES.get(category.lower(), category.lower())
        if category in ("server", "global"):
            category, scope = "runs", category
        if category not in LEADERBOARDS:
            await ctx.send(f"Pick one of: {', '.join(f'`{k}`' for k in LEADERBOARDS)}")
            return
        col, title, fmt = LEADERBOARDS[category]
        where = "WHERE matches_played > 0" if category != "coins" else "WHERE 1=1"
        if category == "average":
            where += " AND innings_batted >= 3"
        args = []
        if scope.lower() in ("server", "s", "guild") and ctx.guild is not None:
            ids = [str(m.id) for m in ctx.guild.members if not m.bot][:900]
            if not ids:
                await ctx.send("No players found in this server.")
                return
            where += f" AND userid IN ({','.join('?' for _ in ids)})"
            args = ids
            title += f" — {ctx.guild.name}"
        rows = await bot.db.fetch(f"SELECT * FROM profiles {where} ORDER BY {col} DESC, matches_played DESC LIMIT 50", args)
        if not rows:
            await ctx.send("No one is on this leaderboard yet — go play a match!")
            return
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        pages = []
        for i in range(0, len(rows), 10):
            lines = []
            for rank, r in enumerate(rows[i:i + 10], start=i + 1):
                me = " ← you" if r["userid"] == str(ctx.author.id) else ""
                lines.append(f"{medals.get(rank, f'`#{rank:>2}`')} **{r['name']}** — {fmt(r)}{me}")
            e = discord.Embed(title=f"🏆 {title}", description="\n".join(lines), color=theme.GOLD)
            e.set_footer(text=theme.footer_text(f"{config.prefix}lb <{'|'.join(list(LEADERBOARDS)[:4])}|…> [server]"))
            if config.website_url:
                e.url = f"{config.website_url}/#/leaderboard"
            pages.append(e)
        await send_pages(ctx, pages)

    # ─────────────────────────────────────────────── coins
    @bot.command(name="balance", aliases=["bal", "coins", "wallet"], help=f"Check your {ECO['currency_name']}.")
    async def balance(ctx: commands.Context, user: discord.User = None):
        user = user or ctx.author
        row = await db_profile(user)
        e = discord.Embed(title=f"{user.name}'s wallet", color=_color(row),
                          description=f"{theme.money(row['coins'])} {theme.CURRENCY}\n-# Earned in total: {row['total_earned']:,}")
        await ctx.send(embed=e)

    @bot.command(name="daily", help="Claim your daily coins (streaks give a bonus).")
    async def daily(ctx: commands.Context):
        if not ECO.get("daily_enabled", True):
            await ctx.send("The daily reward is switched off at the moment.")
            return
        row = await db_profile(ctx.author)
        now = int(time.time())
        last = row.get("daily_last") or 0
        if now - last < DAY:
            await ctx.send(f"⏳ You've already claimed today. Come back <t:{last + DAY}:R>.")
            return
        streak = (row.get("daily_streak") or 0) + 1 if now - last < 2 * DAY else 1
        bonus = min(streak - 1, ECO["daily_streak_cap"]) * ECO["daily_streak_bonus"]
        amount = ECO["daily"] + bonus
        res = await bot.db.execute("UPDATE profiles SET daily_last = ?, daily_streak = ? WHERE userid = ? AND daily_last = ?",
                                   [now, streak, str(ctx.author.id), last])
        if res["affected"] != 1:
            await ctx.send("You've already claimed today.")
            return
        await profiles.add_coins(bot.db, ctx.author.id, amount, "daily")
        e = discord.Embed(title="🎁 Daily reward", color=theme.GREEN,
                          description=f"You received {theme.money(amount)}!\n🔥 Streak: **{streak}** day{'s' if streak != 1 else ''}"
                                      + (f" (+{bonus} bonus)" if bonus else ""))
        await ctx.send(embed=e)

    @bot.command(name="weekly", help="Claim your weekly coins.")
    async def weekly(ctx: commands.Context):
        if not ECO.get("weekly_enabled", True):
            await ctx.send("The weekly reward is switched off at the moment.")
            return
        row = await db_profile(ctx.author)
        now = int(time.time())
        last = row.get("weekly_last") or 0
        if now - last < 7 * DAY:
            await ctx.send(f"⏳ Your weekly reward is ready <t:{last + 7 * DAY}:R>.")
            return
        res = await bot.db.execute("UPDATE profiles SET weekly_last = ? WHERE userid = ? AND weekly_last = ?",
                                   [now, str(ctx.author.id), last])
        if res["affected"] != 1:
            await ctx.send("You've already claimed this week.")
            return
        await profiles.add_coins(bot.db, ctx.author.id, ECO["weekly"], "weekly")
        await ctx.send(embed=discord.Embed(title="🎉 Weekly reward", color=theme.GREEN,
                                           description=f"You received {theme.money(ECO['weekly'])}!"))

    @bot.command(name="give", aliases=["pay", "send"], help="Give coins to another player.")
    @commands.guild_only()
    async def give(ctx: commands.Context, user: discord.Member, amount: int):
        if not ECO.get("give_enabled", True):
            await ctx.send("Sending coins between players is switched off at the moment.")
            return
        if user.bot or user == ctx.author:
            await ctx.send("You can't give coins to yourself or to bots.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        await db_profile(ctx.author)
        await db_profile(user)
        try:
            await profiles.transfer(bot.db, ctx.author.id, user.id, amount)
        except profiles.InsufficientFunds:
            await ctx.send("You don't have enough coins for that.")
            return
        await ctx.send(f"💸 **{ctx.author.name}** gave {theme.money(amount)} to **{user.name}**.")

    # ─────────────────────────────────────────────── shop
    @bot.command(name="shop", aliases=["store"], help="Cosmetic titles, profile colours and badges.")
    async def shop(ctx: commands.Context):
        pages = []
        for kind, label in (("title", "🎖️ Titles"), ("color", "🎨 Profile colours"), ("badge", "🏅 Badges")):
            items = [i for i in ITEMS if i["type"] == kind]
            lines = []
            for i in items:
                preview = i["value"] if kind == "badge" else ("" if kind == "title" else f"`#{i['value']}`")
                lines.append(f"**{i['name']}** {preview} — {theme.money(i['price'])}\n-# `{config.prefix}buy {i['id']}`")
            e = discord.Embed(title=f"🛒 Shop — {label}", description="\n".join(lines), color=theme.GOLD)
            e.set_footer(text=theme.footer_text("Everything is cosmetic. Earn coins by playing matches!"))
            pages.append(e)
        await send_pages(ctx, pages)

    @bot.command(name="buy", help="Buy a shop item: buy <item id>.")
    async def buy(ctx: commands.Context, *, item_name: str):
        if not ECO.get("shop_enabled", True):
            await ctx.send("The shop is closed at the moment.")
            return
        item = find_item(item_name)
        if item is None:
            await ctx.send(f"No item called **{item_name}**. See `{config.prefix}shop`.")
            return
        row = await db_profile(ctx.author)
        inv = json.loads(row.get("inventory") or "[]")
        if item["id"] in inv:
            await ctx.send("You already own that.")
            return
        try:
            await profiles.spend_coins(bot.db, ctx.author.id, item["price"], f"shop: {item['id']}")
        except profiles.InsufficientFunds:
            await ctx.send(f"You need {theme.money(item['price'])} for **{item['name']}** (you have {theme.money(row['coins'])}).")
            return
        inv.append(item["id"])
        sets = ["inventory = ?"]
        args = [json.dumps(inv)]
        if item["type"] == "badge":
            badges = json.loads(row.get("badges") or "[]")
            badges.append(item["value"])
            sets.append("badges = ?")
            args.append(json.dumps(badges, ensure_ascii=False))
        elif not row.get(item["type"]):
            sets.append(f"{item['type']} = ?")
            args.append(item["value"])
        await bot.db.execute(f"UPDATE profiles SET {', '.join(sets)} WHERE userid = ?", args + [str(ctx.author.id)])
        extra = "" if item["type"] == "badge" else f" Equip it with `{config.prefix}equip {item['id']}`."
        await ctx.send(f"🛍️ You bought **{item['name']}** for {theme.money(item['price'])}!{extra}")

    @bot.command(name="inventory", aliases=["inv"], help="Items you own.")
    async def inventory(ctx: commands.Context, user: discord.User = None):
        user = user or ctx.author
        row = await db_profile(user)
        inv = json.loads(row.get("inventory") or "[]")
        if not inv:
            await ctx.send(f"**{user.name}** doesn't own anything yet. Check out `{config.prefix}shop`.")
            return
        lines = []
        for iid in inv:
            item = find_item(iid)
            if not item:
                continue
            equipped = (item["type"] in ("title", "color") and row.get(item["type"]) == item["value"]) or item["type"] == "badge"
            lines.append(f"{'✅' if equipped else '▫️'} **{item['name']}** ({item['type']}) — `{item['id']}`")
        await ctx.send(embed=discord.Embed(title=f"🎒 {user.name}'s inventory", description="\n".join(lines), color=_color(row)))

    @bot.command(name="equip", help="Equip a title or colour you own.")
    async def equip(ctx: commands.Context, *, item_name: str):
        item = find_item(item_name)
        row = await db_profile(ctx.author)
        inv = json.loads(row.get("inventory") or "[]")
        if item is None or item["id"] not in inv:
            await ctx.send("You don't own that item.")
            return
        if item["type"] == "badge":
            await ctx.send("Badges are always shown on your profile.")
            return
        await bot.db.execute(f"UPDATE profiles SET {item['type']} = ? WHERE userid = ?", [item["value"], str(ctx.author.id)])
        await ctx.send(f"✨ Equipped **{item['name']}**.")

    @bot.command(name="unequip", help="Remove your title or colour: unequip title|color.")
    async def unequip(ctx: commands.Context, slot: str):
        slot = slot.lower().replace("colour", "color")
        if slot not in ("title", "color"):
            await ctx.send("Use `title` or `color`.")
            return
        await db_profile(ctx.author)
        await bot.db.execute(f"UPDATE profiles SET {slot} = '' WHERE userid = ?", [str(ctx.author.id)])
        await ctx.send(f"Removed your {slot}.")

    # ─────────────────────────────────────────────── HandCricket compatibility
    @bot.command(name="exportprofile", aliases=["export"], help="Download your profile as HandCricket-format JSON.")
    async def export_profile(ctx: commands.Context):
        row = await db_profile(ctx.author)
        data = json.dumps(profiles.export_profile(row), indent=2)
        await ctx.send("📦 Your profile in HandCricket-compatible JSON:",
                       file=discord.File(io.BytesIO(data.encode()), filename=f"profile_{ctx.author.id}.json"))

    @bot.command(name="importprofile", hidden=True)
    @commands.is_owner()
    async def import_profile(ctx: commands.Context, user: discord.User):
        """Owner only: attach a HandCricket profile JSON to merge its stats into a user's profile."""
        if not ctx.message.attachments:
            await ctx.send("Attach the profile .json file.")
            return
        raw = await ctx.message.attachments[0].read()
        try:
            data = json.loads(raw.decode())
        except Exception:
            await ctx.send("That file isn't valid JSON.")
            return
        await bot.db.batch(profiles.import_statements(data, str(user.id), user.name))
        await ctx.send(f"✅ Imported HandCricket stats into **{user.name}**'s profile.")
