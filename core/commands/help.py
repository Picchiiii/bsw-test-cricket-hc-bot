import discord
from discord.ext import commands

from core.config import config
from core.ui import theme


def _pages():
    p = config.prefix
    g = config.game
    eco = config.economy
    pages = {}

    pages["home"] = ("🏠", "Welcome", (
        f"**{config.bot_name}** brings **Test-match hand cricket** to Discord — two teams, up to "
        f"{g['max_players']} players, four innings, multiple days, declarations and the follow-on.\n\n"
        f"**Quick start**\n"
        f"1. `{p}create` — open a lobby\n"
        f"2. Everyone `{p}join` (or press **Join Match**)\n"
        f"3. Host: `{p}so 20` overs/day and `{p}sd 3` days\n"
        f"4. Host: `{p}toss` → captain picks Heads/Tails → winner picks Bat/Bowl\n"
        f"5. Host: `{p}start` — then play your balls **in my DMs**\n\n"
        f"🏆 Running a competition? See **Tournaments** in the menu (`{p}tour help`).\n\n"
        f"Use the menu below to explore every command and rule."))

    pages["lobby"] = ("🏟️", "Lobby & host", (
        f"`{p}create` / `{p}c` — create a match in this channel\n"
        f"`{p}join` / `{p}j` — join (`{p}join rep` = join as a representative **(R)**)\n"
        f"`{p}join sub A|B` — sit on a team's bench as a substitute\n"
        f"`{p}leave` / `{p}l` — leave before the start\n"
        f"`{p}players` / `{p}pl` — lobby & teams\n"
        f"`{p}so <{g['min_overs']}-{g['max_overs']}>` — overs per day\n"
        f"`{p}sd <{g['min_days']}-{g['max_days']}>` — number of days\n"
        f"`{p}ctn <A|B> <name>` — rename a team\n"
        f"`{p}cc <A|B> @user` — change captain (host or that captain)\n"
        f"`{p}swap @a @b` — swap players between teams\n"
        f"`{p}kick @user` — remove a player\n"
        f"`{p}ll` / `{p}ul` — lock / unlock the lobby\n"
        f"`{p}ch @user` — hand over host\n"
        f"`{p}settings` — advanced rules (innings over cap, follow-on %, timers, rep run cap…)\n"
        f"`{p}cpu add [A|B] [n]` / `{p}cpu remove <name|all>` — CPU players (friendlies)\n"
        f"`{p}yeet` — delete the lobby / abandon the match"))

    pages["play"] = ("🏏", "Playing a match", (
        f"`{p}toss` — host starts the toss\n"
        f"`{p}start` — host starts the match\n"
        f"Captains pick the **opening batter & bowler**, then an **on-deck** batter and the **next over's bowler** "
        f"from dropdowns (auto-picked after {g['selection_timeout']}s).\n\n"
        f"**Each ball:** the batter and bowler get a DM. Type a number **0–6** in the DM within "
        f"**{g['ball_timeout']}s**. Picks are blind.\n\n"
        f"`{p}score` — re-post the live scoreboard\n"
        f"`{p}scorecard [innings]` / `{p}sc` — full batting & bowling card\n"
        f"`{p}declare` / `{p}dec` — batting captain declares\n"
        f"`{p}pause` — host pauses after the current ball\n"
        f"`{p}resume` / `{p}nd` — next day after stumps, or resume a pause\n"
        f"`{p}instance` / `{p}show <thing>` — match details\n"
        f"`{p}sub <out> <in> [rep]` — host/captain brings in a squad player (lobby or mid-match)\n"
        f"`{p}matchsheet [match id]` — download the public JSON match sheet"))

    pages["squad"] = ("🎗️", "Reps, subs & CPUs", (
        "**Representatives (R)**\n"
        f"• Join with `{p}join rep`; the host can mark someone with `{p}setrep <player> on|off`\n"
        f"• A rep may score at most **{g.get('rep_run_cap', 30)}** runs an innings (host: `{p}settings rep_run_cap <n>`, 0 = no cap). "
        "Runs past the cap don't count; on reaching it the rep is **retired out** (a wicket) — or retired not out with "
        f"`{p}settings rep_retire_counts_wicket 0`\n"
        f"• Reps **don't bowl** unless `{p}settings rep_can_bowl 1`. A side needs at least one non-rep to start\n"
        "• Reps are shown as **(R)** on every scorecard and the website\n\n"
        "**Substitutes**\n"
        f"• `{p}sub <out> <in>` — host or that team's captain. **Friendly:** anyone who isn't already in the match. "
        f"**Tournament:** a player from the team's registered squad (organisers can allow outsiders with `{p}tour subs on`)\n"
        "• When play resumes (next day or after a pause) the bot shows both squads first — sub anyone who isn't "
        "there today, then press **Start play**\n"
        "• Mid-match the substitute takes over straight away — at the crease, in the over (a rep can't bowl, so "
        "someone else finishes it) and as captain if needed. The outgoing player's figures stay on the card\n"
        f"• Limit per team: `{p}settings max_subs_per_team <n>`\n\n"
        "**CPU players** (friendly matches only)\n"
        f"• `{p}cpu add [A|B] [count]`, `{p}cpu remove <name|all>` — host, in the lobby\n"
        "• CPUs play their own numbers and make captain calls instantly"
        + ("; matches with a CPU don't count for stats or coins" if not g.get("cpu_matches_count") else "")
        + "\n\n**Match sheet** — when a match ends the result comes with `match_<id>.json` "
        f"(teams, rules, every innings, substitutions, player totals). `{p}matchsheet [id]` gets it again."))

    pages["rules"] = ("📜", "Test rules", (
        "**Scoring**\n"
        "• Same number from batter and bowler → **OUT** (bowler gets the wicket)\n"
        "• Different numbers → batter scores **their** number\n"
        "• Bowler picks **0** → **No Ball**: +1 run, ball replayed, batter can't be out\n"
        "• A batter may play **four** 0s in an over — the **5th dot** in the same over is **out** (not a bowler's wicket)\n\n"
        "**Innings & overs**\n"
        "• 6 legal balls an over; nobody bowls two overs in a row\n"
        "• An innings ends when the side is **all out** (one batter left unpartnered), is **declared**, or hits "
        "the innings over cap (default = overs per day)\n\n"
        "**Days**\n"
        "• When the day's overs are bowled it's **Stumps** — resume the next day with the button or "
        f"`{p}resume`. Out of days → **Draw**.\n\n"
        "**Declarations** — batting captain only, not in the 4th innings, after "
        f"{g['min_declare_overs']} overs.\n"
        f"**Follow-on** — if the side batting 2nd makes less than **{g['follow_on_pct']}%** of the 1st-innings "
        "score, the leading captain may make them bat again.\n\n"
        "**Results** — chase the target in the 4th innings to win by wickets; bowl them out to win by runs; "
        "lead on aggregate after the 3rd innings to win by **an innings**; level scores all out = **Tie**.\n\n"
        f"**AFK** — miss {g['afk_max_strikes']} balls in a row: batter is given out, bowler is replaced."))

    pages["tournament"] = ("🏆", "Tournaments", (
        "Run a full tournament in your server — teams, pools, fixtures, points table, knockout bracket and "
        "tournament stats. **One tournament per server at a time.**\n\n"
        f"**Organisers** (Manage Server, or the tournament's organiser role)\n"
        f"`{p}tour create <name>` → `{p}tour set format league|groups|knockout` → `{p}tour open` → `{p}tour start`\n"
        f"`{p}tour settings` • `{p}tour schedule <no> <time>` • `{p}tour result <no> <team|draw|tie|nr>`\n\n"
        f"**Players & captains**\n"
        f"`{p}tour register` • `{p}tour team create <name>` • `{p}tour invite @user` • `{p}tour accept`\n\n"
        f"**Playing a tournament match**\n"
        f"`{p}create` — the bot asks if it's a tournament match — or `{p}tm <match number>` at any time before "
        f"`{p}start`. Only the two teams' players can join, the tournament's rules are applied, and the result "
        f"updates the table and bracket by itself.\n\n"
        f"**Everyone**\n"
        f"`{p}tour` • `{p}tour fixtures` • `{p}tour table` • `{p}tour bracket` • `{p}tour stats` • `{p}tour teams` • `{p}tour me`\n\n"
        f"`{p}tour help` lists every tournament command."
        + (f"\n🌐 Tournament pages & management: {config.website_url}/#/tournaments" if config.website_url else "")))

    pages["stats"] = ("📊", "Stats & profile", (
        f"`{p}profile [@user]` / `{p}me` — profile card\n"
        f"`{p}userstats [@user]` / `{p}us` — in-depth batting & bowling\n"
        f"`{p}matchlog [@user]` / `{p}ml` — recent matches\n"
        f"`{p}leaderboard <runs|wickets|coins|wins|matches|average|highest|hattricks|sixes|potm> [server]` / `{p}lb`\n"
        f"`{p}setdesc <text>` — profile description\n"
        f"`{p}exportprofile` — download your profile (HandCricket JSON format)"
        + (f"\n\n🌐 Live matches & full stats: {config.website_url}" if config.website_url else "")))

    pages["economy"] = ("🪙", eco["currency_name"], (
        f"`{p}balance` / `{p}bal` — your wallet\n"
        f"`{p}daily` — {eco['daily']} {theme.COIN} (+{eco['daily_streak_bonus']} per streak day, up to "
        f"{eco['daily_streak_cap']})\n"
        f"`{p}weekly` — {eco['weekly']} {theme.COIN}\n"
        f"`{p}give @user <amount>` — send coins\n"
        f"`{p}shop` • `{p}buy <item>` • `{p}inventory` • `{p}equip <item>` • `{p}unequip title|color`\n\n"
        f"**Match rewards** (completed matches of {eco['min_balls_for_rewards']}+ balls)\n"
        f"Play {eco['participation']} • Win +{eco['win']} • Draw +{eco['draw']} • Tie +{eco['tie']}\n"
        f"Per run +{eco['per_run']} • per wicket +{eco['per_wicket']} • 50 +{eco['fifty']} • 100 +{eco['hundred']}\n"
        f"5-for +{eco['five_wickets']} • Hat-trick +{eco['hattrick']} • Player of the Match +{eco['potm']}"))
    return pages


def _embed(key, pages):
    emoji, title, body = pages[key]
    e = discord.Embed(title=f"{emoji} {title}", description=body, color=theme.CREAM)
    e.set_footer(text=theme.footer_text(f"Prefix: {config.prefix}"))
    return e


class HelpSelect(discord.ui.Select):
    def __init__(self, pages):
        self.pages = pages
        super().__init__(placeholder="Choose a help topic…", options=[
            discord.SelectOption(label=title, emoji=emoji, value=key) for key, (emoji, title, _) in pages.items()])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_embed(self.values[0], self.pages), view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=300)
        self.add_item(HelpSelect(pages))
        if config.website_url:
            self.add_item(discord.ui.Button(label="Website", emoji="🌐", style=discord.ButtonStyle.link, url=config.website_url))
        if config.support_url:
            self.add_item(discord.ui.Button(label="Support", style=discord.ButtonStyle.link, url=config.support_url))


def help_command(bot: commands.Bot):

    @bot.command(name="help", aliases=["h", "commands", "rules"], help="Show this help menu.")
    async def help_cmd(ctx: commands.Context, topic: str = None):
        pages = _pages()
        key = "home"
        if ctx.invoked_with == "rules":
            key = "rules"
        if topic and topic.lower() in pages:
            key = topic.lower()
        await ctx.send(embed=_embed(key, pages), view=HelpView(pages))
