import discord
from discord.ext import commands
import logging
import pprint
from core.config import config
from core.backend.views.match_view import JoinMatchView
from core.backend.views.yeet_view import YeetMatchView
from core.backend.instance import MatchInstance, player_busy_elsewhere
from core.backend.instance import join_segregate_player
from core.backend.lobby import lobby_embed
from core.ui import theme

logger = logging.getLogger(__name__)
G = config.game


def host(bot: commands.Bot):
    if not hasattr(bot, "active_matches"):
        bot.active_matches = {}

    def get_match(ctx):
        return ctx.bot.active_matches.get(ctx.channel.id)

    async def no_match(ctx):
        await ctx.send(f"No active match in this channel. Create one with `{config.prefix}create`.")

    async def match_already_started(ctx: commands.Context):
        await ctx.send("You cannot do that. A match is already started in this channel.")

    def persist(mi):
        store = getattr(bot, "store", None)
        if store is not None:
            store.schedule(mi)

    async def tournament_fixed(ctx, mi, what: str) -> bool:
        """Tournament matches take their teams and rules from the tournament. True = blocked (message sent)."""
        if not getattr(mi, "tournament", None):
            return False
        await ctx.send(f"This is a tournament match — {what} come from **{mi.tournament['name']}** "
                       f"(`{config.prefix}t settings`). Use `{config.prefix}tm off` to make it a friendly.")
        return True

    @bot.command(name="create", aliases=["c"], help="Create a test match lobby in this channel.")
    @commands.guild_only()
    async def create_match(ctx: commands.Context):
        if ctx.channel.id in ctx.bot.active_matches:
            await ctx.send("A match is already active in this channel.")
            return
        other = player_busy_elsewhere(ctx.bot, ctx.author, ctx.channel.id)
        if other:
            await ctx.send(f"You are already in a match in <#{other}>. Finish or leave it first.")
            return

        match_instance = MatchInstance(bot, ctx)
        ctx.bot.active_matches[ctx.channel.id] = match_instance

        match_instance.players.append(ctx.author)
        join_segregate_player(match_instance, ctx.author)

        join_match_view = JoinMatchView(match_instance, None)
        join_message = await ctx.send(
            f"A match of hand cricket has been created by **{ctx.author.name}**. Click below or use `{config.prefix}join` to join the match.",
            embed=lobby_embed(match_instance),
            view=join_match_view
        )
        join_match_view.message = join_message
        persist(match_instance)
        # a tournament is running here: ask whether this is a tournament match (or use the tm command)
        mgr = getattr(ctx.bot, "tournaments", None)
        if mgr is not None:
            await mgr.prompt_on_create(match_instance)

    @bot.command(name="dump", hidden=True)
    @commands.is_owner()
    async def dump_match(ctx):
        match = get_match(ctx)

        if not match:
            await ctx.send("No active match.")
            return

        skip = {"bot", "lock", "game", "task", "interrupt", "resume_event", "scorecard_message", "pending_views",
                "channel", "guild"}
        data = pprint.pformat({k: v for k, v in vars(match).items() if k not in skip}, indent=2, width=120)

        # Split into Discord-sized chunks
        for i in range(0, len(data), 1900):
            await ctx.send(f"```py\n{data[i:i+1900]}\n```")

    @bot.command(name="instance", aliases=["i"], help="Show the match details for this channel.")
    @commands.guild_only()
    async def check_instance(ctx: commands.Context):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        mi = match_instance
        a, b = mi.teamA_scores, mi.teamB_scores

        def fmt(s):
            parts = []
            for slot in ("inning_one", "inning_two"):
                if s[slot]["batted"]:
                    parts.append(f"{s[slot]['runs']}/{s[slot]['wickets']}{'d' if s[slot]['declared'] else ''}")
            return " & ".join(parts) or "yet to bat"

        embed = discord.Embed(
            title="Match Instance Details",
            description=(
                f"Match ID: `{mi.match_id}`\n"
                f"Created: <t:{int(mi.created_at)}:R>\n"
                f"Host: **{mi.host.name}**\n"
                f"Players: {', '.join([player.name for player in mi.players])}\n"
                f"Lobby Lock: {'Locked' if mi.lobby_lock else 'Unlocked'}\n"
                f"Phase: **{mi.phase}**{' (paused)' if mi.paused else ''}{' (stumps)' if mi.stumps_called else ''}\n"
                f"Day: **{mi.crr_day}/{mi.match_settings['days'] or '-'}** • Innings: **{mi.innings}**\n"
                f"Overs (this innings): {mi.overs}.{mi.balls_this_over}\n"
                f"Team A Captain: **{mi.teamA_captain.name if mi.teamA_captain else 'Not set'}**\n"
                f"Team B Captain: **{mi.teamB_captain.name if mi.teamB_captain else 'Not set'}**\n"
                f"Toss Winner: **{mi.toss_winner.name if mi.toss_winner else 'Not set'}**\n"
                f"Current Batsman: **{mi.curr_batsman.name if mi.curr_batsman else 'Not set'}**\n"
                f"Current Bowler: **{mi.curr_bowler.name if mi.curr_bowler else 'Not set'}**\n"
                f"Batting Team: **{mi.team_name(mi.batting_turn) if mi.batting_turn else 'Not set'}**\n"
                f"Bowling Team: **{mi.team_name(mi.bowling_turn) if mi.bowling_turn else 'Not set'}**\n"
                f"{mi.team_settings['Team A name']}: {fmt(a)}\n"   # FIX (B12): real per-team fields
                f"{mi.team_settings['Team B name']}: {fmt(b)}\n"
            ), color=theme.BLUE
        )
        await ctx.send(embed=embed)

    SHOW_FIELDS = {
        "overs": lambda mi: f"Overs per day: **{mi.match_settings['overs'] or 'not set'}**",
        "days": lambda mi: f"Days: **{mi.match_settings['days'] or 'not set'}**",
        "score": lambda mi: f"**{mi.score}/{mi.wickets}** ({mi.overs}.{mi.balls_this_over})",
        "wickets": lambda mi: f"Wickets: **{mi.wickets}**",
        "innings": lambda mi: f"Innings: **{mi.innings}**",
        "day": lambda mi: f"Day: **{mi.crr_day}**",
        "target": lambda mi: f"Target: **{mi.target if mi.target is not None else 'not set yet'}**",
        "host": lambda mi: f"Host: **{mi.host.name}**",
        "captains": lambda mi: (f"{mi.team_settings['Team A name']}: **{mi.teamA_captain.name if mi.teamA_captain else '-'}**\n"
                                f"{mi.team_settings['Team B name']}: **{mi.teamB_captain.name if mi.teamB_captain else '-'}**"),
        "teams": lambda mi: (f"**{mi.team_settings['Team A name']}**: {', '.join(p.name for p in mi.teamA) or '-'}\n"
                             f"**{mi.team_settings['Team B name']}**: {', '.join(p.name for p in mi.teamB) or '-'}"),
        "settings": lambda mi: "\n".join(f"`{k}`: {v}" for k, v in mi.match_settings.items()),
    }

    @bot.command(name="show", aliases=["sho"], help="Show one piece of match info, e.g. show teams.")
    @commands.guild_only()
    async def show_match_info(ctx: commands.Context, param: str = None):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        key = (param or "").lower()
        if key not in SHOW_FIELDS:   # FIX (B16): whitelist instead of arbitrary getattr
            await ctx.send(f"Choose one of: {', '.join(f'`{k}`' for k in SHOW_FIELDS)}")
            return
        embed = discord.Embed(title=f"{key.capitalize()} Information",
                              description=SHOW_FIELDS[key](match_instance),
                              color=theme.BLUE)
        await ctx.send(embed=embed)

    @bot.command(name="yeet", aliases=["y", "abandon"], help="Host: delete the lobby or abandon the match.")
    @commands.guild_only()
    async def yeet_match(ctx: commands.Context):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        if match_instance.host.id == ctx.author.id:
            yeet_view = YeetMatchView(match_instance, None, ctx)
            extra = " The match in progress will be **abandoned** and no stats will be saved." if match_instance.game_started else ""
            yeet_message = await ctx.send(
                f"Are you sure you want to yeet the match created by **{match_instance.host.name}**? This action cannot be undone.{extra}",
                view=yeet_view
            )
            yeet_view.message = yeet_message
        else:
            await ctx.send("Only the host can yeet the match.")

    @bot.command(name="change_host", aliases=["ch"], help="Host: hand the host role to another player.")
    @commands.guild_only()
    async def change_host(ctx: commands.Context, new_host: discord.Member):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        if match_instance.host.id == ctx.author.id:
            if new_host in match_instance.players:   # FIX (B15): compare Member objects
                match_instance.host = new_host
                persist(match_instance)
                await ctx.send(f"Host has been changed to **{new_host.name}**.")
            else:
                await ctx.send("The new host must be a player in the match.")
        else:
            await ctx.send("Only the host can change the host.")

    @bot.command(name="lock_lobby", aliases=["ll"], help="Host: stop new players joining.")
    @commands.guild_only()
    async def lock_lobby(ctx: commands.Context):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        if match_instance.host.id == ctx.author.id:
            match_instance.lobby_lock = True
            persist(match_instance)
            await ctx.send("The lobby has been locked. No new players can join. 🔒")
        else:
            await ctx.send("Only the host can lock the lobby.")

    @bot.command(name="unlock_lobby", aliases=["ul"], help="Host: let players join again.")
    @commands.guild_only()
    async def unlock_lobby(ctx: commands.Context):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        if match_instance.game_started:
            await match_already_started(ctx)
            return
        if match_instance.host.id == ctx.author.id:
            match_instance.lobby_lock = False
            persist(match_instance)
            await ctx.send("The lobby has been unlocked. New players can now join. 🔓")
        else:
            await ctx.send("Only the host can unlock the lobby.")

    @bot.command(name="set_overs", aliases=["so"], help="Host: overs per day (10-90).")
    @commands.guild_only()
    async def set_overs(ctx: commands.Context, overs: int):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        if not isinstance(overs, int) or overs < G["min_overs"] or overs > G["max_overs"]:
            await ctx.send(f"Overs can only be set between {G['min_overs']} and {G['max_overs']}.")
            return
        if match_instance.game_started:
            await match_already_started(ctx)
            return
        if await tournament_fixed(ctx, match_instance, "the overs"):
            return
        if ctx.author.id == match_instance.host.id:
            match_instance.match_settings['overs'] = overs
            persist(match_instance)
            await ctx.send(f"The number of overs has been set to **{overs}** per day.")
        else:
            await ctx.send("Only the host can set the number of overs.")

    @bot.command(name="change_team_name", aliases=["ctn"], help="Host: rename a team, e.g. ctn A Lions.")
    @commands.guild_only()
    async def change_team_name(ctx: commands.Context, team: str, *, new_name: str):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        new_name = discord.utils.escape_markdown(new_name.strip())[:32]
        if not new_name:
            await ctx.send("Please give a team name.")
            return
        if await tournament_fixed(ctx, match_instance, "team names"):
            return
        if ctx.author.id == match_instance.host.id:
            if team.lower() in ("a", "1"):
                match_instance.team_settings['Team A name'] = new_name
                await ctx.send(f"Team A's name has been changed to **{new_name}**.")
            elif team.lower() in ("b", "2"):
                match_instance.team_settings['Team B name'] = new_name
                await ctx.send(f"Team B's name has been changed to **{new_name}**.")
            else:
                await ctx.send("Invalid team. Use 'A/1' or 'B/2'.")
                return
            persist(match_instance)
        else:
            await ctx.send("Only the host can change team names.")

    @bot.command(name="change_captain", aliases=["cc"], help="Host/captain: change a team's captain, e.g. cc A @user.")
    @commands.guild_only()
    async def change_captain(ctx: commands.Context, team: str, new_captain: discord.Member):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        mi = match_instance
        side = "A" if team.lower() in ("a", "1") else "B" if team.lower() in ("b", "2") else None
        if side is None:
            await ctx.send("Invalid team. Use 'A/1' or 'B/2'.")
            return
        if not (ctx.author == mi.host or ctx.author == mi.captain(side)):
            await ctx.send("Only the host or that team's current captain can change its captain.")
            return
        if new_captain not in mi.team(side):
            await ctx.send(f"The new captain must be a player in {mi.team_name(side)}.")
            return
        if side == "A":
            mi.teamA_captain = new_captain
        else:
            mi.teamB_captain = new_captain
        persist(mi)
        await ctx.send(f"{mi.team_name(side)}'s captain has been changed to **{new_captain.name}**. 🧢")

    @bot.command(name="kick", aliases=["k"], help="Host/captain: remove a player from the lobby.")
    @commands.guild_only()
    async def kick_player(ctx: commands.Context, player: discord.Member):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        mi = match_instance
        if mi.game_started:
            await match_already_started(ctx)
            return
        side = mi.side_of(player)
        allowed = ctx.author == mi.host or (side is not None and ctx.author == mi.captain(side))
        if not allowed:
            await ctx.send("Only the host or captains of their respective teams can kick players.")
            return
        if player not in mi.players:   # FIX (B5): Member objects, not ids
            await ctx.send("The specified player is not in the game.")
            return
        if player == mi.host:
            await ctx.send("The host can't be kicked. Change the host first.")
            return
        from core.backend.instance import leave_segregate_player
        mi.players.remove(player)
        leave_segregate_player(mi, player)
        persist(mi)
        await ctx.send(f"**{player.name}** has been kicked from the game.")

    @bot.command(name="swap", aliases=["sw"], help="Host: swap two players between the teams.")
    @commands.guild_only()
    async def swap_players(ctx: commands.Context, player1: discord.Member, player2: discord.Member):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        mi = match_instance
        if ctx.author.id != mi.host.id:
            await ctx.send("Only the host can swap players.")
            return
        if mi.game_started:
            await match_already_started(ctx)
            return
        if player1 not in mi.players or player2 not in mi.players:
            await ctx.send("Both players must be part of the game to swap.")
            return
        if await tournament_fixed(ctx, mi, "the teams"):
            return
        s1, s2 = mi.side_of(player1), mi.side_of(player2)
        if s1 == s2:
            await ctx.send("Both players must be on different teams to swap.")
            return
        t1, t2 = mi.team(s1), mi.team(s2)
        i1, i2 = t1.index(player1), t2.index(player2)
        t1[i1], t2[i2] = player2, player1
        # captaincy stays with the team
        for side, old, new in ((s1, player1, player2), (s2, player2, player1)):
            if mi.captain(side) == old:
                if side == "A":
                    mi.teamA_captain = new
                else:
                    mi.teamB_captain = new
        persist(mi)
        await ctx.send(f"**{player1.name}** and **{player2.name}** have been swapped between teams. 🔁")

    @bot.command(name="stday", aliases=["sd", "set_days"], help="Host: number of days (1-5).")
    @commands.guild_only()
    async def set_no_of_days(ctx: commands.Context, days: int):
        match_instance = get_match(ctx)
        if not match_instance:
            await no_match(ctx)
            return
        if days < G["min_days"] or days > G["max_days"]:
            await ctx.send(f"Days can only be set between {G['min_days']} and {G['max_days']}.")
            return
        if match_instance.game_started:
            await match_already_started(ctx)
            return
        if await tournament_fixed(ctx, match_instance, "the days"):
            return
        if ctx.author.id == match_instance.host.id:
            match_instance.match_settings['days'] = days
            persist(match_instance)
            await ctx.send(f"The match days have been set to **{days}**.")
        else:
            await ctx.send("Only the host can set the match days.")

    SETTINGS = {
        "innings_overs": ("Max overs in one innings (0 = unlimited, default = overs per day)", 0, 450),
        "follow_on_pct": ("Follow-on if 2nd innings < this % of the 1st", 0, 100),
        "min_declare_overs": ("Overs before a declaration is allowed", 0, 90),
        "ball_timeout": ("Seconds to pick a number", 10, 120),
        "selection_timeout": ("Seconds for captains to pick players", 10, 120),
        "afk_max_strikes": ("Missed balls before AFK action", 1, 10),
        "max_no_balls_per_over": ("No-balls in an over before the bowler is changed (0 = off)", 0, 10),
        "last_man_bats": ("1 = last batter bats alone, 0 = innings ends with one batter left", 0, 1),
        "rep_run_cap": ("Most runs a rep (R) may score in one innings (0 = no cap)", 0, 500),
        "rep_can_bowl": ("1 = reps may bowl, 0 = reps never bowl", 0, 1),
        "rep_retire_counts_wicket": ("1 = a rep reaching the cap is retired out (wicket), 0 = retired not out", 0, 1),
        "max_reps_per_team": ("Most reps per team (0 = no limit)", 0, 11),
        "max_subs_per_team": ("Most substitutions per team during the match (0 = no limit)", 0, 11),
    }
    BOOL_SETTINGS = {"last_man_bats", "rep_can_bowl", "rep_retire_counts_wicket"}

    @bot.command(name="settings", aliases=["set"], help="Host: view or change advanced match settings.")
    @commands.guild_only()
    async def match_settings_cmd(ctx: commands.Context, key: str = None, value: int = None):
        mi = get_match(ctx)
        if not mi:
            await no_match(ctx)
            return
        if key is None:
            e = theme.embed("⚙️ Match settings", color=theme.BLUE)
            for k, (desc, lo, hi) in SETTINGS.items():
                cur = mi.match_settings.get(k)
                if k in BOOL_SETTINGS:
                    cur = int(bool(cur))
                if k == "innings_overs" and cur is None:
                    cur = f"{mi.match_settings['overs'] or '='} (overs per day)"
                e.add_field(name=f"`{k}` = {cur}", value=f"{desc} ({lo}-{hi})", inline=False)
            e.set_footer(text=theme.footer_text(f"Change with {config.prefix}settings <name> <value>"))
            await ctx.send(embed=e)
            return
        if ctx.author != mi.host:
            await ctx.send("Only the host can change settings.")
            return
        if mi.game_started:
            await match_already_started(ctx)
            return
        if await tournament_fixed(ctx, mi, "the match rules"):
            return
        key = key.lower()
        if key not in SETTINGS or value is None:
            await ctx.send(f"Usage: `{config.prefix}settings <name> <value>` — names: {', '.join(SETTINGS)}")
            return
        desc, lo, hi = SETTINGS[key]
        if not lo <= value <= hi:
            await ctx.send(f"`{key}` must be between {lo} and {hi}.")
            return
        mi.match_settings[key] = bool(value) if key in BOOL_SETTINGS else value
        if key == "min_declare_overs":
            mi.min_declare_overs = value
        persist(mi)
        await ctx.send(f"⚙️ `{key}` set to **{value}**.")
