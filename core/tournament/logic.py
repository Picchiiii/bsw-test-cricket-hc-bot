"""Pure tournament maths: round-robins, knockout brackets, points tables, player tables, time parsing.

Nothing here touches Discord or the database, so every rule can be unit-tested directly.
"""
import datetime
import re

STAGE_LABELS = {
    "group": "Group stage", "final": "Final", "sf": "Semi-final", "qf": "Quarter-final",
    "r16": "Round of 16", "r32": "Round of 32", "r64": "Round of 64", "extra": "Extra match",
}
KNOCKOUT_STAGES = ("r64", "r32", "r16", "qf", "sf", "final")
DONE = ("completed", "walkover")


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage.title())


def stage_for(teams_in_round: int) -> str:
    return {2: "final", 4: "sf", 8: "qf", 16: "r16", 32: "r32", 64: "r64"}.get(teams_in_round, f"r{teams_in_round}")


def next_pow2(n: int) -> int:
    size = 1
    while size < n:
        size *= 2
    return size


# ─────────────────────────────────────────────────────────── fixtures
def round_robin(team_ids: list, legs: int = 1) -> list[list[tuple]]:
    """Circle method. Returns rounds; each round is a list of (home, away) pairs. Odd counts get a bye."""
    teams = list(team_ids)
    if len(teams) < 2:
        return []
    if len(teams) % 2:
        teams.append(None)
    n = len(teams)
    rounds = []
    order = list(teams)
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            if a is None or b is None:
                continue
            # alternate who is listed first so no team is always "home"
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        order = [order[0]] + [order[-1]] + order[1:-1]
    if legs >= 2:
        rounds = rounds + [[(b, a) for a, b in rnd] for rnd in rounds]
    return rounds


def bracket_order(size: int) -> list[int]:
    """Seed numbers in bracket-slot order, e.g. 8 -> [1, 8, 4, 5, 2, 7, 3, 6] (1 can only meet 2 in the final)."""
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [x for s in order for x in (s, n + 1 - s)]
    return order


def build_knockout(seeds: list) -> list[dict]:
    """Bracket for `seeds` (best first). Returns fixture dicts with temporary keys:

    {key, stage, round, slot, team_a, team_b, source_a, source_b}; source_* is the key of the match whose
    winner fills that side. Byes go to the top seeds and are resolved here (no fixture is created for a bye).
    """
    n = len(seeds)
    if n < 2:
        return []
    size = next_pow2(n)
    order = bracket_order(size)
    rounds = size.bit_length() - 1
    fixtures = []
    # what fills each slot of the round being built: ("team", id) | ("win", key) | None
    feed = []
    for s in range(size):
        seed_no = order[s]
        feed.append(("team", seeds[seed_no - 1]) if seed_no <= n else None)
    for r in range(1, rounds + 1):
        teams_in_round = size // (2 ** (r - 1))
        nxt = []
        for s in range(teams_in_round // 2):
            a, b = feed[2 * s], feed[2 * s + 1]
            if a is None and b is None:
                nxt.append(None)
                continue
            if a is None or b is None:          # bye: the present side moves straight on
                nxt.append(a or b)
                continue
            key = f"r{r}s{s}"
            fixtures.append({
                "key": key, "stage": stage_for(teams_in_round), "round": r, "slot": s,
                "team_a": a[1] if a[0] == "team" else None, "team_b": b[1] if b[0] == "team" else None,
                "source_a": a[1] if a[0] == "win" else "", "source_b": b[1] if b[0] == "win" else "",
            })
            nxt.append(("win", key))
        feed = nxt
    return fixtures


# ─────────────────────────────────────────────────────────── standings
def _blank_row(team: dict) -> dict:
    return {"team_id": team["team_id"], "name": team["name"], "tag": team.get("tag") or "",
            "group": team.get("group_name") or "", "status": team.get("status") or "active",
            "played": 0, "won": 0, "lost": 0, "drawn": 0, "tied": 0, "no_result": 0, "points": 0,
            "runs_for": 0, "balls_for": 0, "runs_against": 0, "balls_against": 0, "nrr": 0.0, "form": []}


def fixture_points(fx: dict, settings: dict) -> dict:
    """{team_id: points} for one finished fixture."""
    a, b = fx.get("team_a_id"), fx.get("team_b_id")
    rt = fx.get("result_type")
    summary = fx.get("summary") or {}
    out = {a: 0, b: 0}
    if rt in ("win", "walkover"):
        w = fx.get("winner_team_id")
        loser = b if w == a else a
        out[w] = settings["points_win"] + (settings["bonus_innings_win"] if summary.get("innings_win") else 0)
        out[loser] = settings["points_loss"]
    elif rt == "tie":
        out[a] = out[b] = settings["points_tie"]
    elif rt == "draw":
        out[a] = out[b] = settings["points_draw"]
        leader = summary.get("fi_leader")
        if leader in out:
            out[leader] += settings["bonus_first_innings_lead"]
    elif rt == "no_result":
        out[a] = out[b] = settings["points_no_result"]
    return out


def compute_standings(teams: list[dict], fixtures: list[dict], settings: dict) -> dict:
    """Points tables: {group_name: [rows best-first]}. Only group-stage fixtures count."""
    rows = {t["team_id"]: _blank_row(t) for t in teams}
    played = sorted((f for f in fixtures if f.get("stage") == "group" and f.get("status") in DONE),
                    key=lambda f: (f.get("updated_at") or 0, f.get("number") or 0))
    for fx in played:
        a, b = fx.get("team_a_id"), fx.get("team_b_id")
        if a not in rows or b not in rows:
            continue
        pts = fixture_points(fx, settings)
        rt = fx.get("result_type")
        w = fx.get("winner_team_id")
        per_team = (fx.get("summary") or {}).get("teams") or {}
        for me, other in ((a, b), (b, a)):
            r = rows[me]
            r["played"] += 1
            r["points"] += pts.get(me, 0)
            if rt in ("win", "walkover"):
                won = w == me
                r["won" if won else "lost"] += 1
                r["form"].append("W" if won else "L")
            elif rt == "tie":
                r["tied"] += 1
                r["form"].append("T")
            elif rt == "draw":
                r["drawn"] += 1
                r["form"].append("D")
            else:
                r["no_result"] += 1
                r["form"].append("N")
            mine, theirs = per_team.get(me), per_team.get(other)
            if rt != "walkover" and mine and theirs:
                r["runs_for"] += mine.get("runs", 0)
                r["balls_for"] += mine.get("balls", 0)
                r["runs_against"] += theirs.get("runs", 0)
                r["balls_against"] += theirs.get("balls", 0)
    tables: dict[str, list] = {}
    for r in rows.values():
        rf = r["runs_for"] / (r["balls_for"] / 6) if r["balls_for"] else 0.0
        ra = r["runs_against"] / (r["balls_against"] / 6) if r["balls_against"] else 0.0
        r["nrr"] = round(rf - ra, 3)
        r["form"] = r["form"][-5:]
        tables.setdefault(r["group"], []).append(r)
    for group, table in tables.items():
        table.sort(key=lambda r: (-r["points"], -r["won"], -r["nrr"], -r["runs_for"], r["name"].lower()))
        for i, r in enumerate(table, start=1):
            r["rank"] = i
    return dict(sorted(tables.items()))


def pick_qualifiers(tables: dict, per_group: int) -> list:
    """Team ids that reach the knockout, in seed order (cross-pool pairings where the numbers allow it)."""
    groups = [g for g in tables if tables[g]]
    live = {g: [r for r in tables[g] if r.get("status") != "withdrawn"] for g in groups}
    if per_group <= 0 or not groups:
        return []
    if len(groups) == 1:
        return [r["team_id"] for r in live[groups[0]][:per_group]]
    count = len(groups)
    if per_group == 2 and count % 2 == 0 and all(len(live[g]) >= 2 for g in groups):
        winners = [live[g][0]["team_id"] for g in groups]
        runners = [live[groups[(count - 1 - i) ^ 1]][1]["team_id"] for i in range(count)]
        return winners + runners
    seeds = []
    for rank in range(per_group):
        tier = [live[g][rank] for g in groups if len(live[g]) > rank]
        tier.sort(key=lambda r: (-r["points"], -r["won"], -r["nrr"], r["name"].lower()))
        seeds.extend(r["team_id"] for r in tier)
    return seeds


# ─────────────────────────────────────────────────────────── player tables
def overs_text(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


def mvp_points(r: dict) -> int:
    return int(r["runs"] + 20 * r["wickets"] + 10 * r["fifties"] + 25 * r["hundreds"] + 15 * r["five_wickets"]
               + 20 * r["hattricks"] + 15 * r["potm"])


def aggregate_players(rows: list[dict], team_of: dict | None = None) -> list[dict]:
    """Collapse per-match stat rows (player_match_stats) into one tournament line per player."""
    team_of = team_of or {}
    out: dict[str, dict] = {}
    for m in rows:
        uid = str(m["userid"])
        r = out.get(uid)
        if r is None:
            r = out[uid] = {"userid": uid, "name": m.get("name") or uid, "team_id": team_of.get(uid),
                            "matches": 0, "innings": 0, "not_outs": 0, "runs": 0, "balls": 0, "fours": 0, "sixes": 0,
                            "highest": 0, "outs": 0, "fifties": 0, "hundreds": 0, "ducks": 0, "wickets": 0,
                            "balls_bowled": 0, "runs_conceded": 0, "maidens": 0, "five_wickets": 0, "hattricks": 0,
                            "best_w": 0, "best_r": 0, "potm": 0, "_bowled": False}
        r["name"] = m.get("name") or r["name"]
        r["matches"] += 1
        r["innings"] += m.get("innings_batted") or 0
        r["not_outs"] += m.get("not_outs") or 0
        r["runs"] += m.get("runs") or 0
        r["balls"] += m.get("balls") or 0
        r["fours"] += m.get("fours") or 0
        r["sixes"] += m.get("sixes") or 0
        r["highest"] = max(r["highest"], m.get("highest") or 0)
        r["outs"] += m.get("outs") or 0
        r["fifties"] += m.get("fifties") or 0
        r["hundreds"] += m.get("hundreds") or 0
        r["ducks"] += m.get("ducks") or 0
        r["wickets"] += m.get("wickets") or 0
        r["balls_bowled"] += m.get("balls_bowled") or 0
        r["runs_conceded"] += m.get("runs_conceded") or 0
        r["maidens"] += m.get("maidens") or 0
        r["five_wickets"] += m.get("five_wickets") or 0
        r["hattricks"] += m.get("hattricks") or 0
        r["potm"] += m.get("potm") or 0
        if m.get("balls_bowled"):
            bw, br = m.get("best_w") or 0, m.get("best_r") or 0
            if not r["_bowled"] or bw > r["best_w"] or (bw == r["best_w"] and br < r["best_r"]):
                r["best_w"], r["best_r"] = bw, br
            r["_bowled"] = True
    table = []
    for r in out.values():
        r.pop("_bowled")
        r["average"] = round(r["runs"] / r["outs"], 2) if r["outs"] else float(r["runs"])
        r["strike_rate"] = round(r["runs"] / r["balls"] * 100, 2) if r["balls"] else 0.0
        r["economy"] = round(r["runs_conceded"] / r["balls_bowled"] * 6, 2) if r["balls_bowled"] else 0.0
        r["bowling_average"] = round(r["runs_conceded"] / r["wickets"], 2) if r["wickets"] else 0.0
        r["mvp"] = mvp_points(r)
        table.append(r)
    table.sort(key=lambda r: (-r["mvp"], -r["runs"], r["name"].lower()))
    return table


# category -> (title, sort key, formatter, filter)
LEADERBOARDS = {
    "runs": ("Most runs", lambda r: (-r["runs"], r["balls"]), lambda r: f"{r['runs']} runs ({r['innings']} inns)",
             lambda r: r["innings"] > 0),
    "wickets": ("Most wickets", lambda r: (-r["wickets"], r["runs_conceded"]),
                lambda r: f"{r['wickets']} wkts ({overs_text(r['balls_bowled'])} ov)", lambda r: r["balls_bowled"] > 0),
    "highest": ("Highest scores", lambda r: (-r["highest"],), lambda r: f"HS {r['highest']}", lambda r: r["innings"] > 0),
    "average": ("Best batting average", lambda r: (-r["average"], -r["runs"]),
                lambda r: f"avg {r['average']:.2f} ({r['runs']} runs)", lambda r: r["innings"] >= 2),
    "strikerate": ("Best strike rate", lambda r: (-r["strike_rate"],),
                   lambda r: f"SR {r['strike_rate']:.1f} ({r['runs']} runs)", lambda r: r["balls"] >= 12),
    "economy": ("Best economy", lambda r: (r["economy"], -r["balls_bowled"]),
                lambda r: f"econ {r['economy']:.2f} ({overs_text(r['balls_bowled'])} ov)", lambda r: r["balls_bowled"] >= 12),
    "best": ("Best bowling", lambda r: (-r["best_w"], r["best_r"]), lambda r: f"{r['best_w']}/{r['best_r']}",
             lambda r: r["balls_bowled"] > 0),
    "sixes": ("Most sixes", lambda r: (-r["sixes"],), lambda r: f"{r['sixes']} sixes", lambda r: r["sixes"] > 0),
    "fours": ("Most fours", lambda r: (-r["fours"],), lambda r: f"{r['fours']} fours", lambda r: r["fours"] > 0),
    "fifties": ("Most 50+ scores", lambda r: (-(r["fifties"] + r["hundreds"]), -r["runs"]),
                lambda r: f"{r['fifties']} fifties, {r['hundreds']} hundreds", lambda r: r["fifties"] + r["hundreds"] > 0),
    "potm": ("Most Player of the Match awards", lambda r: (-r["potm"],), lambda r: f"{r['potm']} awards",
             lambda r: r["potm"] > 0),
    "mvp": ("Most valuable players", lambda r: (-r["mvp"],), lambda r: f"{r['mvp']} pts — {r['runs']} runs, {r['wickets']} wkts",
            lambda r: r["matches"] > 0),
}
LEADER_ALIASES = {"run": "runs", "r": "runs", "bat": "runs", "wkts": "wickets", "wicket": "wickets", "w": "wickets",
                  "bowl": "wickets", "hs": "highest", "high": "highest", "highscore": "highest", "avg": "average",
                  "sr": "strikerate", "eco": "economy", "econ": "economy", "bb": "best", "6s": "sixes", "4s": "fours",
                  "50s": "fifties", "mom": "potm", "motm": "potm", "points": "mvp", "pot": "mvp"}


def leaders(table: list[dict], category: str, limit: int = 10) -> list[dict]:
    _, key, _, keep = LEADERBOARDS[category]
    return sorted((r for r in table if keep(r)), key=lambda r: key(r) + (r["name"].lower(),))[:limit]


# ─────────────────────────────────────────────────────────── time
_REL = re.compile(r"(\d+)\s*(d|h|m)")


def parse_time(text: str, now: int) -> int:
    """Fixture time. Accepts a unix timestamp, a Discord timestamp (<t:...>), `+2h30m` / `in 1d`, or
    `YYYY-MM-DD HH:MM` (UTC). `none`/`clear` returns 0. Raises ValueError when it can't be read."""
    t = str(text or "").strip().lower()
    if t in ("", "none", "clear", "off", "tbd", "0"):
        return 0
    m = re.fullmatch(r"<t:(\d+)(?::[a-z])?>", t)
    if m:
        return int(m.group(1))
    if t.isdigit() and len(t) >= 9:
        return int(t)
    rel = t.removeprefix("in").strip().removeprefix("+").strip()
    parts = _REL.findall(rel)
    if parts and _REL.sub("", rel).strip() == "":
        secs = sum(int(n) * {"d": 86400, "h": 3600, "m": 60}[u] for n, u in parts)
        return now + secs
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dt%H:%M", "%Y-%m-%d %H.%M", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(t, fmt).replace(tzinfo=datetime.timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError("I couldn't read that time. Use `2025-06-30 18:30` (UTC), `+2h`, `+1d12h` or a Discord timestamp.")
