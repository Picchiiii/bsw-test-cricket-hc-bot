"""Embeds for tournament commands (overview, tables, fixtures, bracket, teams, stats, help)."""
import discord

from core.config import config
from core.tournament import logic, schema
from core.ui import theme

P = config.prefix
STATUS_BADGE = {"setup": "🛠️ Setting up", "registration": "📝 Registration open", "ongoing": "🏏 In progress",
                "completed": "🏁 Finished", "cancelled": "🛑 Cancelled"}
FORMAT_NAME = {"league": "League", "groups": "Pools + knockout", "knockout": "Knockout"}


def _footer(e: discord.Embed, t: dict, extra: str = ""):
    e.set_footer(text=theme.footer_text(f"{t['name']}" + (f" • {extra}" if extra else "")))
    url = theme.tournament_url(t["tournament_id"])
    if url:
        e.url = url
    return e


def _clip(name: str, width: int) -> str:
    name = name or "?"
    return (name[: width - 1] + "…") if len(name) > width else name.ljust(width)


def overview(t: dict, teams: list, players: list, fixtures: list) -> discord.Embed:
    s = t["settings"]
    names = {x["team_id"]: x["name"] for x in teams}
    e = discord.Embed(title=f"🏆 {t['name']}", color=theme.GOLD)
    desc = [f"**{STATUS_BADGE.get(t['status'], t['status'])}** • {FORMAT_NAME.get(s['format'], s['format'])}"
            f" • host **{t['host_name']}**"]
    if t.get("description"):
        desc.append(t["description"])
    if t["status"] == "completed" and t.get("champion_team_id"):
        desc.append(f"🥇 Champions: **{names.get(t['champion_team_id'], '?')}**"
                    + (f" • 🥈 **{names.get(t['runner_up_team_id'], '?')}**" if t.get("runner_up_team_id") else ""))
    e.description = "\n".join(desc)
    active = [x for x in teams if x["status"] == "active"]
    in_team = len([pl for pl in players if pl["team_id"] and pl["status"] == "active"])
    free = len([pl for pl in players if not pl["team_id"] and pl["status"] == "active"])
    e.add_field(name="Teams", value=f"**{len(active)}** / {s['max_teams']}", inline=True)
    e.add_field(name="Players", value=f"**{in_team}** in teams • {free} free agents", inline=True)
    done = len([f for f in fixtures if f["status"] in logic.DONE])
    e.add_field(name="Matches", value=f"**{done}** / {len(fixtures)} played" if fixtures else "not drawn yet", inline=True)
    rules = f"{s['overs']} overs/day • {s['days']} day(s) • {s['min_players']}–{s['max_players']} a side"
    e.add_field(name="Match rules", value=rules, inline=True)
    if s["format"] == "groups":
        shape = f"{s['groups']} pools, top {s['qualifiers']} go through"
    elif s["format"] == "league":
        shape = (f"{'double' if s['rounds'] == 2 else 'single'} round-robin"
                 + (f", top {s['qualifiers']} to the knockout" if s["qualifiers"] >= 2 else ", table decides"))
    else:
        shape = "single elimination"
    e.add_field(name="Structure", value=shape, inline=True)
    e.add_field(name="Points", value=f"W {s['points_win']} • D {s['points_draw']} • T {s['points_tie']} • L {s['points_loss']}",
                inline=True)
    live = [f for f in fixtures if f["status"] == "live"]
    if live:
        e.add_field(name="🔴 Live now", value=theme.truncate("\n".join(
            f"`#{f['number']}` {names.get(f['team_a_id'])} v {names.get(f['team_b_id'])} — <#{f['channel_id']}>" for f in live)),
            inline=False)
    nxt = [f for f in fixtures if f["status"] == "scheduled" and f["team_a_id"] and f["team_b_id"]][:5]
    if nxt:
        e.add_field(name="Next up", value=theme.truncate("\n".join(fixture_line(f, names) for f in nxt)), inline=False)
    if t["status"] == "registration":
        e.add_field(name="Take part", value=f"`{P}tour register` to sign up • `{P}tour teams` to see the teams", inline=False)
    elif t["status"] == "setup":
        e.add_field(name="Organisers", value=f"`{P}tour open` opens registration • `{P}tour start` begins the tournament • "
                                             f"`{P}tour help` for everything", inline=False)
    return _footer(e, t, f"{P}tour help")


def fixture_line(f: dict, names: dict) -> str:
    a, b = names.get(f.get("team_a_id"), "TBD"), names.get(f.get("team_b_id"), "TBD")
    tag = logic.stage_label(f["stage"]) if f["stage"] != "group" else (f"Pool {f['group_name']}" if f["group_name"] else f"Round {f['round']}")
    head = f"`#{f['number']:>2}` {tag} · **{a} v {b}**"
    if f["status"] in logic.DONE:
        return f"{head}\n-# ✅ {f.get('result_text') or 'played'}"
    if f["status"] == "live":
        return f"{head}\n-# 🔴 live in <#{f['channel_id']}>"
    if f["status"] == "cancelled":
        return f"{head}\n-# cancelled"
    when = f.get("scheduled_at") or 0
    return f"{head}" + (f"\n-# 🕒 <t:{when}:F> (<t:{when}:R>)" if when else "")


def fixtures_pages(t: dict, fixtures: list, names: dict, title: str = "Fixtures") -> list[discord.Embed]:
    pages = []
    for i in range(0, len(fixtures), 8):
        e = discord.Embed(title=f"🗓️ {t['name']} — {title}", color=theme.BLUE,
                          description="\n".join(fixture_line(f, names) for f in fixtures[i:i + 8]))
        pages.append(_footer(e, t, f"{P}tm <number> marks a lobby as that match"))
    return pages


def table_embed(t: dict, tables: dict, only: str | None = None) -> discord.Embed:
    e = discord.Embed(title=f"📊 {t['name']} — points table", color=theme.GOLD)
    qual = t["settings"]["qualifiers"] if t["settings"]["format"] != "knockout" else 0
    shown = 0
    for group, rows in tables.items():
        if only is not None and group.upper() != only.upper():
            continue
        lines = [f"{'#':<2} {'Team':<14} {'P':>2} {'W':>2} {'L':>2} {'D':>2} {'T':>2} {'Pts':>3} {'NRR':>7}"]
        for r in rows:
            mark = "*" if qual and r["rank"] <= qual and len(tables) >= 1 and r["played"] else " "
            lines.append(f"{r['rank']:<2} {_clip(r['name'] + mark, 14)} {r['played']:>2} {r['won']:>2} {r['lost']:>2} "
                         f"{r['drawn']:>2} {r['tied']:>2} {r['points']:>3} {r['nrr']:>+7.3f}")
        e.add_field(name=f"Pool {group}" if group else "League table",
                    value=theme.truncate("```\n" + "\n".join(lines) + "\n```"), inline=False)
        shown += 1
    if not shown:
        e.description = "No table yet — teams appear here once they are created."
    elif qual:
        e.description = f"-# * in a qualifying place (top {qual})"
    return _footer(e, t)


def bracket_embed(t: dict, fixtures: list, names: dict) -> discord.Embed:
    e = discord.Embed(title=f"🎯 {t['name']} — knockout bracket", color=theme.PURPLE)
    by_stage: dict[str, list] = {}
    for f in fixtures:
        if f["stage"] in logic.KNOCKOUT_STAGES or f["stage"].startswith("r"):
            by_stage.setdefault(f["stage"], []).append(f)
    if not by_stage:
        e.description = "The bracket appears when the knockout stage is drawn."
        return _footer(e, t)
    by_no = {f["fixture_id"]: f["number"] for f in fixtures}

    def side(f, key, src):
        if f.get(key):
            name = names.get(f[key], "?")
            return f"**{name}**" if f.get("winner_team_id") == f[key] else name
        ref = f.get(src) or ""
        return f"*winner of #{by_no.get(ref[2:], '?')}*" if ref.startswith("W:") else "*TBD*"

    for stage in sorted(by_stage, key=lambda s: min(f["round"] for f in by_stage[s])):
        lines = []
        for f in sorted(by_stage[stage], key=lambda f: f["slot"]):
            status = "✅" if f["status"] in logic.DONE else ("🔴" if f["status"] == "live" else "▫️")
            lines.append(f"{status} `#{f['number']}` {side(f, 'team_a_id', 'source_a')} v {side(f, 'team_b_id', 'source_b')}"
                         + (f"\n-# {f['result_text']}" if f.get("result_text") else ""))
        e.add_field(name=logic.stage_label(stage), value=theme.truncate("\n".join(lines)), inline=False)
    return _footer(e, t)


def teams_pages(t: dict, teams: list, players: list) -> list[discord.Embed]:
    by_team: dict[str, list] = {}
    for pl in players:
        if pl["team_id"] and pl["status"] == "active":
            by_team.setdefault(pl["team_id"], []).append(pl)
    pages = []
    ordered = sorted(teams, key=lambda x: (x["group_name"], x["name"].lower()))
    for i in range(0, len(ordered), 6):
        e = discord.Embed(title=f"🛡️ {t['name']} — teams ({len(teams)})", color=theme.BLUE)
        for team in ordered[i:i + 6]:
            roster = by_team.get(team["team_id"], [])
            lines = []
            for pl in roster:
                mark = " (C)" if pl["user_id"] == team["captain_id"] else " (VC)" if pl["user_id"] == team["vice_captain_id"] else ""
                lines.append(f"{pl['name']}{mark}")
            head = f"{team['name']} [{team['tag']}]" + (f" · Pool {team['group_name']}" if team["group_name"] else "")
            if team["status"] != "active":
                head += " · withdrawn"
            e.add_field(name=theme.truncate(head, 256), value=theme.truncate(", ".join(lines) or "*no players yet*"), inline=False)
        pages.append(_footer(e, t, f"{P}tour team <name> for details"))
    return pages


def team_embed(t: dict, team: dict, roster: list, fixtures: list, names: dict, stats: dict) -> discord.Embed:
    e = discord.Embed(title=f"🛡️ {team['name']} [{team['tag']}]", color=theme.BLUE)
    bits = []
    if team["group_name"]:
        bits.append(f"Pool **{team['group_name']}**")
    if team.get("seed"):
        bits.append(f"Seed **{team['seed']}**")
    if team.get("role_id"):
        bits.append(f"<@&{team['role_id']}>")
    if team["status"] != "active":
        bits.append("**withdrawn**")
    e.description = " • ".join(bits) or None
    lines = []
    for pl in roster:
        mark = " 🧢 captain" if pl["user_id"] == team["captain_id"] else " · vice-captain" if pl["user_id"] == team["vice_captain_id"] else ""
        st = stats.get(pl["user_id"])
        fig = f" — {st['runs']} runs, {st['wickets']} wkts" if st else ""
        lines.append(f"<@{pl['user_id']}>{mark}{fig}")
    e.add_field(name=f"Squad ({len(roster)}/{t['settings']['max_squad']})", value=theme.truncate("\n".join(lines) or "*empty*"),
                inline=False)
    mine = [f for f in fixtures if team["team_id"] in (f["team_a_id"], f["team_b_id"])]
    if mine:
        e.add_field(name="Matches", value=theme.truncate("\n".join(fixture_line(f, names) for f in mine[:8])), inline=False)
    return _footer(e, t)


def leaders_pages(t: dict, table: list, category: str, team_names: dict) -> list[discord.Embed]:
    title, _, fmt, _ = logic.LEADERBOARDS[category]
    rows = logic.leaders(table, category, 30)
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    pages = []
    for i in range(0, max(len(rows), 1), 10):
        lines = []
        for rank, r in enumerate(rows[i:i + 10], start=i + 1):
            team = team_names.get(r.get("team_id"))
            lines.append(f"{medals.get(rank, f'`#{rank:>2}`')} **{r['name']}**" + (f" ({team})" if team else "") + f" — {fmt(r)}")
        e = discord.Embed(title=f"🏅 {t['name']} — {title}", color=theme.GOLD,
                          description="\n".join(lines) or "No tournament matches have been finished yet.")
        pages.append(_footer(e, t, f"{P}tour stats <{'|'.join(list(logic.LEADERBOARDS)[:6])}|…>"))
    return pages


def player_embed(t: dict, r: dict | None, name: str, team_name: str | None, status: str) -> discord.Embed:
    e = discord.Embed(title=f"👤 {name} — {t['name']}", color=theme.BLUE)
    e.description = (f"Team: **{team_name}**" if team_name else "Free agent") + (" • **banned**" if status == "banned" else "")
    if r is None:
        e.add_field(name="Stats", value="No tournament matches played yet.", inline=False)
        return _footer(e, t)
    e.add_field(name=f"{theme.BAT} Batting", value=(
        f"Matches **{r['matches']}** • Innings **{r['innings']}** • Not out **{r['not_outs']}**\n"
        f"Runs **{r['runs']}** • HS **{r['highest']}** • Avg **{r['average']:.2f}** • SR **{r['strike_rate']:.1f}**\n"
        f"50s/100s **{r['fifties']}/{r['hundreds']}** • 4s/6s **{r['fours']}/{r['sixes']}** • Ducks **{r['ducks']}**"), inline=False)
    best = f"{r['best_w']}/{r['best_r']}" if r["balls_bowled"] else "-"
    e.add_field(name=f"{theme.BALL} Bowling", value=(
        f"Overs **{logic.overs_text(r['balls_bowled'])}** • Wickets **{r['wickets']}** • Best **{best}**\n"
        f"Econ **{r['economy']:.2f}** • Avg **{r['bowling_average']:.2f}** • 5W **{r['five_wickets']}** • "
        f"Hat-tricks **{r['hattricks']}**"), inline=False)
    e.add_field(name="Awards", value=f"Player of the Match **{r['potm']}** • MVP points **{r['mvp']}**", inline=False)
    return _footer(e, t)


def settings_pages(t: dict) -> list[discord.Embed]:
    groups: dict[str, list] = {}
    for key, spec in schema.SETTINGS.items():
        groups.setdefault(spec["group"], []).append((key, spec))
    pages = []
    for group, items in groups.items():
        e = discord.Embed(title=f"⚙️ {t['name']} — settings · {group}", color=theme.BLUE)
        for key, spec in items:
            lock = " 👑" if spec.get("owner_only") else ""
            e.add_field(name=f"{spec['label']}{lock}",
                        value=f"`{key}` = **{schema.describe(key, t['settings'][key])}**\n-# {spec['help']}", inline=False)
        pages.append(_footer(e, t, f"{P}tour set <name> <value>"))
    return pages


def help_pages() -> list[discord.Embed]:
    p = P
    pages = [
        ("🏆 Tournaments — overview", (
            "A server runs **one tournament at a time**. The bot keeps the teams, pools, fixtures, points table, "
            "knockout bracket and every player's tournament stats.\n\n"
            "**Fast start (organiser)**\n"
            f"1. `{p}tour create <name>` — needs Manage Server\n"
            f"2. `{p}tour set format league|groups|knockout` and `{p}tour set overs 10`, `{p}tour set days 2`\n"
            f"3. `{p}tour open` — players `{p}tour register`, captains `{p}tour team create <name>`\n"
            f"4. `{p}tour start` — fixtures are drawn, rosters lock\n"
            f"5. For each match: `{p}create` → `{p}tm <match number>` → teams join → `{p}toss` → `{p}start`\n"
            "The result, table and bracket update by themselves when the match ends.\n\n"
            f"Everyone: `{p}tour` (overview) • `{p}tour fixtures` • `{p}tour table` • `{p}tour bracket` • `{p}tour stats` • `{p}tour teams`"
            + (f"\n🌐 Manage everything on the website too: {config.website_url}/#/tournaments" if config.website_url else ""))),
        ("👥 Players & captains", (
            f"`{p}tour register` — sign up (when registration is open)\n"
            f"`{p}tour unregister` — leave the tournament\n"
            f"`{p}tour team create <name> [tag]` — create a team (you become captain)\n"
            f"`{p}tour invite @user` — captain: invite a registered player\n"
            f"`{p}tour accept [team]` / `{p}tour decline [team]` — answer an invite\n"
            f"`{p}tour team join <team>` — join directly (if the tournament allows it)\n"
            f"`{p}tour leave` — leave your team\n"
            f"`{p}tour team kick @user` • `{p}tour team captain @user` • `{p}tour team vice @user`\n"
            f"`{p}tour team rename <name>` • `{p}tour team tag <TAG>` • `{p}tour team disband`\n"
            f"`{p}tour me` — your team, next match and stats\n"
            f"`{p}tm [match number]` — captain: mark the lobby in this channel as your tournament match")),
        ("📋 Info for everyone", (
            f"`{p}tour` — overview • `{p}tour rules` — format, points and match rules\n"
            f"`{p}tour teams` • `{p}tour team <name>` • `{p}tour players` (free agents)\n"
            f"`{p}tour fixtures [team|pool|live|todo]` • `{p}tour results`\n"
            f"`{p}tour table [pool]` • `{p}tour bracket`\n"
            f"`{p}tour stats [runs|wickets|highest|average|strikerate|economy|best|sixes|fours|fifties|potm|mvp]`\n"
            f"`{p}tour player [@user]` — tournament stats for one player\n"
            f"`{p}tour history` — past tournaments in this server")),
        ("🛠️ Organisers — set-up", (
            f"`{p}tour create <name>` • `{p}tour name <new name>` • `{p}tour desc <text>`\n"
            f"`{p}tour settings` — every setting • `{p}tour set <name> <value>`\n"
            f"`{p}tour open` / `{p}tour close` — registration\n"
            f"`{p}tour lock` / `{p}tour unlock` — rosters (transfer window)\n"
            f"`{p}tour subs on|off` — allow match substitutes from outside a team's squad\n"
            f"`{p}tour team create <name> [tag] [@captain]` • `{p}tour team add <team> @user` • `{p}tour team remove @user`\n"
            f"`{p}tour team captain <team> @user` • `{p}tour team rename <team> <name>` • `{p}tour team delete <team>`\n"
            f"`{p}tour team pool <team> <A-H>` • `{p}tour team seed <team> <n>` • `{p}tour draw [seeded]`\n"
            f"`{p}tour add @user` — register someone • `{p}tour autofill` — spread free agents over the teams\n"
            f"`{p}tour ban @user` / `{p}tour unban @user`\n"
            f"`{p}tour staff add|remove @user` • `{p}tour host @user`")),
        ("🛠️ Organisers — running it", (
            f"`{p}tour generate` — preview the fixture list • `{p}tour start` — begin\n"
            f"`{p}tm <number>` — mark the lobby in this channel as that match (`{p}tm off` to undo)\n"
            f"`{p}tour schedule <number> <time>` — e.g. `2025-07-01 18:30` (UTC), `+2h`, `none`\n"
            f"`{p}tour result <number> <team|draw|tie|nr>` — enter or correct a result by hand\n"
            f"`{p}tour walkover <number> <team>` • `{p}tour fixture reset <number>` (replay)\n"
            f"`{p}tour fixture add <team> <team> [extra] [time]` • `{p}tour fixture remove <number>`\n"
            f"`{p}tour fixture teams <number> <team> <team>`\n"
            f"`{p}tour team withdraw <team>` — team pulls out, opponents get walkovers\n"
            f"`{p}tour advance` — build the knockout (automatic by default)\n"
            f"`{p}tour end [champion]` • `{p}tour cancel` • `{p}tour reopen` • `{p}tour delete`\n"
            f"`{p}tour announce <text>` • `{p}tour log` — who changed what")),
        ("🎭 Roles & channels", (
            f"`{p}tour role organizer @role…` — members with these roles can run the tournament\n"
            f"`{p}tour role player @role` — given to every player on a team\n"
            f"`{p}tour role captain @role` — given to captains\n"
            f"`{p}tour role team <team> @role` — a role for one team\n"
            f"`{p}tour role auto on|off` — the bot creates a role per team\n"
            f"`{p}tour role register @role` — only this role may register\n"
            f"`{p}tour role sync` — fix roles • `{p}tour role clear` — remove them all after the tournament\n"
            f"`{p}tour channel announce|results|log #channel`\n\n"
            "Use `none` instead of a role/channel to clear it. The bot needs **Manage Roles** and its own role "
            "above the roles it hands out.")),
    ]
    out = []
    for i, (title, body) in enumerate(pages, start=1):
        e = discord.Embed(title=title, description=body, color=theme.CREAM)
        e.set_footer(text=theme.footer_text(f"Tournament help {i}/{len(pages)} • {p}tour is short for {p}tournament"))
        out.append(e)
    return out


def rules_embed(t: dict) -> discord.Embed:
    s = t["settings"]
    e = discord.Embed(title=f"📜 {t['name']} — rules", color=theme.CREAM)
    e.add_field(name="Format", value=schema.FORMATS[s["format"]], inline=False)
    if s["format"] == "groups":
        e.add_field(name="Pools", value=f"{s['groups']} pools, {'home and away' if s['rounds'] == 2 else 'single round-robin'}; "
                                        f"top **{s['qualifiers']}** of each pool reach the knockout", inline=False)
    elif s["format"] == "league":
        e.add_field(name="League", value=f"{'Home and away' if s['rounds'] == 2 else 'Everyone plays everyone once'}; "
                    + (f"top **{s['qualifiers']}** reach the knockout" if s["qualifiers"] >= 2 else "the table decides the champion"),
                    inline=False)
    e.add_field(name="Matches", value=(
        f"**{s['overs']}** overs a day, **{s['days']}** day(s)\n"
        f"Innings cap: {'overs per day' if s['innings_overs'] < 0 else ('none' if s['innings_overs'] == 0 else str(s['innings_overs']) + ' overs')}\n"
        f"Follow-on below **{s['follow_on_pct']}%** • declare after **{s['min_declare_overs']}** overs\n"
        f"**{s['min_players']}–{s['max_players']}** players a side • squads of up to **{s['max_squad']}**"), inline=False)
    e.add_field(name="Points", value=(
        f"Win **{s['points_win']}** • Draw **{s['points_draw']}** • Tie **{s['points_tie']}** • Loss **{s['points_loss']}** • "
        f"No result **{s['points_no_result']}**\n"
        + (f"Innings win bonus **+{s['bonus_innings_win']}**\n" if s["bonus_innings_win"] else "")
        + (f"First-innings lead in a draw **+{s['bonus_first_innings_lead']}**\n" if s["bonus_first_innings_lead"] else "")
        + "Level on points: most wins, then net run rate."), inline=False)
    if s["format"] != "league" or s["qualifiers"] >= 2:
        e.add_field(name="Drawn knockout match", value=(
            "The side with the **first-innings lead** goes through." if s["knockout_draw_rule"] == "first_innings"
            else "An organiser decides who goes through."), inline=False)
    return _footer(e, t)
