"""Profiles, coins and match recording.

Profile columns `matches_played … match_log` use the same names and formulas as the HandCricket bot
(batting_average = runs / wickets_lost, rounded to 3 places; falls back to runs when never out), so
profiles can be exported/imported between the two in the same JSON shape.
"""
import json
import logging
import time

from core.config import config
from core.backend.cpu import is_cpu, has_cpu

logger = logging.getLogger(__name__)
ECO = config.economy

HANDCRICKET_FIELDS = ["userid", "name", "description", "matches_played", "matches_won", "matches_lost", "runs",
                      "balls", "wickets", "wickets_lost", "highest_score", "hattricks", "ducks", "batting_average",
                      "match_log", "status", "created_at"]
EXTENDED_FIELDS = ["matches_drawn", "matches_tied", "innings_batted", "not_outs", "fours", "sixes", "fifties",
                   "hundreds", "balls_bowled", "runs_conceded", "no_balls", "maidens", "five_wickets",
                   "best_bowling_wickets", "best_bowling_runs", "potm"]
MATCH_LOG_KEEP = 25


class InsufficientFunds(Exception):
    pass


def now() -> int:
    return int(time.time())


def batting_average(runs: int, wickets_lost: int) -> float:
    try:
        return round(runs / wickets_lost, 3)
    except ZeroDivisionError:
        return float(runs)


async def get_profile(db, user_id) -> dict | None:
    return await db.fetchone("SELECT * FROM profiles WHERE userid = ?", [str(user_id)])


def _create_stmt(user_id, name):
    return ("INSERT INTO profiles (userid, name, coins, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(userid) DO UPDATE SET name = excluded.name",
            [str(user_id), name, ECO["start_balance"], now(), now()])


async def ensure_profile(db, user) -> dict:
    row = await get_profile(db, user.id)
    if row is None:
        await db.batch([_create_stmt(user.id, user.name),
                        ("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
                         [str(user.id), ECO["start_balance"], "welcome bonus", now()])])
        row = await get_profile(db, user.id)
    elif row.get("name") != user.name:
        await db.execute("UPDATE profiles SET name = ? WHERE userid = ?", [user.name, str(user.id)])
        row["name"] = user.name
    return row


async def add_coins(db, user_id, amount: int, reason: str):
    await db.batch([
        ("UPDATE profiles SET coins = coins + ?, total_earned = total_earned + ?, updated_at = ? WHERE userid = ?",
         [amount, max(0, amount), now(), str(user_id)]),
        ("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
         [str(user_id), amount, reason, now()]),
    ])


async def adjust_coins(db, user_id, delta: int, reason: str) -> tuple[int, int]:
    """Owner adjustment: add (or take, never below zero). Returns (old balance, new balance)."""
    row = await get_profile(db, user_id)
    old = int((row or {}).get("coins") or 0)
    new = max(0, old + int(delta))
    return await set_coins(db, user_id, new, reason)


async def set_coins(db, user_id, amount: int, reason: str) -> tuple[int, int]:
    """Owner adjustment: set the balance to an exact amount. Returns (old balance, new balance)."""
    row = await get_profile(db, user_id)
    old = int((row or {}).get("coins") or 0)
    new = max(0, int(amount))
    delta = new - old
    await db.batch([
        ("UPDATE profiles SET coins = ?, total_earned = total_earned + ?, updated_at = ? WHERE userid = ?",
         [new, max(0, delta), now(), str(user_id)]),
        ("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
         [str(user_id), delta, reason, now()]),
    ])
    return old, new


async def ensure_profile_id(db, user_id, name: str = "") -> dict:
    """Like ensure_profile, for when only the ID (and maybe a name) is known (website / offline users)."""
    row = await get_profile(db, user_id)
    if row is None:
        await db.batch([_create_stmt(user_id, name or f"User {user_id}"),
                        ("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
                         [str(user_id), ECO["start_balance"], "welcome bonus", now()])])
        row = await get_profile(db, user_id)
    return row


async def spend_coins(db, user_id, amount: int, reason: str):
    res = await db.execute("UPDATE profiles SET coins = coins - ?, updated_at = ? WHERE userid = ? AND coins >= ?",
                           [amount, now(), str(user_id), amount])
    if res["affected"] != 1:
        raise InsufficientFunds()
    await db.execute("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
                     [str(user_id), -amount, reason, now()])


async def transfer(db, sender_id, receiver_id, amount: int):
    res = await db.execute("UPDATE profiles SET coins = coins - ?, updated_at = ? WHERE userid = ? AND coins >= ?",
                           [amount, now(), str(sender_id), amount])
    if res["affected"] != 1:
        raise InsufficientFunds()
    await db.batch([
        ("UPDATE profiles SET coins = coins + ?, updated_at = ? WHERE userid = ?", [amount, now(), str(receiver_id)]),
        ("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
         [str(sender_id), -amount, f"gift to {receiver_id}", now()]),
        ("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
         [str(receiver_id), amount, f"gift from {sender_id}", now()]),
    ])


# ─────────────────────────────────────────────────────────── match recording
def aggregate_player(mi, pid: str) -> dict:
    a = {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "outs": 0, "innings_batted": 0, "not_outs": 0,
         "highest": 0, "ducks": 0, "fifties": 0, "hundreds": 0, "wickets": 0, "balls_bowled": 0,
         "runs_conceded": 0, "no_balls": 0, "maidens": 0, "hattricks": 0, "five_wickets": 0,
         "best_w": 0, "best_r": 0}
    has_best = False
    for card in mi.innings_scorecards.values():
        for r in card.get("batting", []):
            if r["id"] != pid:
                continue
            a["innings_batted"] += 1
            a["runs"] += r["runs"]
            a["balls"] += r["balls"]
            a["fours"] += r["fours"]
            a["sixes"] += r["sixes"]
            a["highest"] = max(a["highest"], r["runs"])
            if r["is_out"]:
                a["outs"] += 1
                if r["runs"] == 0:
                    a["ducks"] += 1
            else:
                a["not_outs"] += 1
            if r["runs"] >= 100:
                a["hundreds"] += 1
            elif r["runs"] >= 50:
                a["fifties"] += 1
        for r in card.get("bowling", []):
            if r["id"] != pid:
                continue
            a["wickets"] += r["wickets"]
            a["balls_bowled"] += r["balls"]
            a["runs_conceded"] += r["runs"]
            a["no_balls"] += r.get("no_balls", 0)
            a["maidens"] += r.get("maidens", 0)
            a["hattricks"] += r.get("hattricks", 0)
            if r["wickets"] >= 5:
                a["five_wickets"] += 1
            if r["balls"] and (not has_best or _better_bowling(r["wickets"], r["runs"], a["best_w"], a["best_r"])):
                a["best_w"], a["best_r"] = r["wickets"], r["runs"]
                has_best = True
    return a


def compute_reward(a: dict, result: str, potm: bool, eligible: bool) -> int:
    if not eligible or not ECO.get("match_rewards_enabled", True):
        return 0
    coins = ECO["participation"]
    coins += {"WIN": ECO["win"], "DRAW": ECO["draw"], "TIE": ECO["tie"]}.get(result, 0)
    coins += a["runs"] * ECO["per_run"] + a["wickets"] * ECO["per_wicket"]
    coins += a["fifties"] * ECO["fifty"] + a["hundreds"] * ECO["hundred"]
    coins += a["five_wickets"] * ECO["five_wickets"] + a["hattricks"] * ECO["hattrick"]
    if potm:
        coins += ECO["potm"]
    return int(coins)


def _better_bowling(w1, r1, w2, r2) -> bool:
    """Is (w1, r1) a better bowling figure than (w2, r2)? More wickets, then fewer runs."""
    if w1 != w2:
        return w1 > w2
    return r1 < r2


async def record_match(db, mi) -> dict:
    """Update every player's profile for a finished match. Idempotent per match_id.

    Returns {user_id(str): coins_awarded}.
    """
    res = mi.result or {}
    if res.get("type") not in ("win", "draw", "tie"):
        return {}
    done = await db.fetch("SELECT userid, coins FROM player_match_stats WHERE match_id = ?", [mi.match_id])
    if done:
        return {r["userid"]: r["coins"] for r in done}

    if has_cpu(mi) and not config.game.get("cpu_matches_count", False):
        return {}   # matches against CPU players don't count (no stats, no coins)
    total_balls = sum(c.get("balls", 0) for c in mi.innings_scorecards.values())
    eligible = total_balls >= ECO["min_balls_for_rewards"]
    # everyone who took part — including players substituted out mid-match — but never CPU players
    participants = [p for p in (mi.featured_players() if hasattr(mi, "featured_players") else mi.players)
                    if not is_cpu(p)]
    ids = [str(p.id) for p in participants]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    existing = {r["userid"]: r for r in await db.fetch(f"SELECT * FROM profiles WHERE userid IN ({placeholders})", ids)}

    stmts = []
    rewards = {}
    ts = now()
    for player in participants:
        pid = str(player.id)
        side = mi.side_of_any(player) if hasattr(mi, "side_of_any") else mi.side_of(player)
        if res["type"] == "win":
            result = "WIN" if res.get("winner") == side else "LOSS"
        elif res["type"] == "tie":
            result = "TIE"
        else:
            result = "DRAW"
        a = aggregate_player(mi, pid)
        potm = str(mi.potm) == pid if mi.potm else False
        coins = compute_reward(a, result, potm, eligible)
        rewards[pid] = coins

        prof = existing.get(pid)
        if prof is None:
            stmts.append(_create_stmt(pid, player.name))
            stmts.append(("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
                          [pid, ECO["start_balance"], "welcome bonus", ts]))
            prof = {k: 0 for k in HANDCRICKET_FIELDS + EXTENDED_FIELDS}
            prof["match_log"] = "[]"

        runs = (prof.get("runs") or 0) + a["runs"]
        wickets_lost = (prof.get("wickets_lost") or 0) + a["outs"]
        best_w, best_r = prof.get("best_bowling_wickets") or 0, prof.get("best_bowling_runs") or 0
        never_bowled = not (prof.get("balls_bowled") or 0)
        if a["balls_bowled"] and (never_bowled or _better_bowling(a["best_w"], a["best_r"], best_w, best_r)):
            best_w, best_r = a["best_w"], a["best_r"]
        try:
            log = json.loads(prof.get("match_log") or "[]")
        except Exception:
            log = []
        log.append({"match_id": mi.match_id, "result": result, "runs": a["runs"], "balls": a["balls"],
                    "wickets": a["wickets"], "runs_conceded": a["runs_conceded"], "team": mi.team_name(side),
                    "opponent": mi.team_name(mi.other(side)), "potm": potm, "time": ts})
        log = log[-MATCH_LOG_KEEP:]

        stmts.append((
            "UPDATE profiles SET name = ?, matches_played = matches_played + 1, matches_won = matches_won + ?, "
            "matches_lost = matches_lost + ?, matches_drawn = matches_drawn + ?, matches_tied = matches_tied + ?, "
            "runs = ?, balls = balls + ?, wickets = wickets + ?, wickets_lost = ?, "
            "highest_score = MAX(highest_score, ?), hattricks = hattricks + ?, ducks = ducks + ?, batting_average = ?, "
            "match_log = ?, innings_batted = innings_batted + ?, not_outs = not_outs + ?, fours = fours + ?, "
            "sixes = sixes + ?, fifties = fifties + ?, hundreds = hundreds + ?, balls_bowled = balls_bowled + ?, "
            "runs_conceded = runs_conceded + ?, no_balls = no_balls + ?, maidens = maidens + ?, "
            "five_wickets = five_wickets + ?, best_bowling_wickets = ?, best_bowling_runs = ?, potm = potm + ?, "
            "coins = coins + ?, total_earned = total_earned + ?, updated_at = ? WHERE userid = ?",
            [player.name, int(result == "WIN"), int(result == "LOSS"), int(result == "DRAW"), int(result == "TIE"),
             runs, a["balls"], a["wickets"], wickets_lost, a["highest"], a["hattricks"], a["ducks"],
             batting_average(runs, wickets_lost), json.dumps(log), a["innings_batted"], a["not_outs"], a["fours"],
             a["sixes"], a["fifties"], a["hundreds"], a["balls_bowled"], a["runs_conceded"], a["no_balls"],
             a["maidens"], a["five_wickets"], best_w, best_r, int(potm), coins, coins, ts, pid]))
        if coins:
            stmts.append(("INSERT INTO transactions (userid, amount, reason, created_at) VALUES (?, ?, ?, ?)",
                          [pid, coins, f"match {mi.match_id}", ts]))
        stmts.append((
            "INSERT INTO player_match_stats (match_id, userid, name, team, team_name, result, runs, balls, fours, sixes, "
            "outs, innings_batted, highest, wickets, balls_bowled, runs_conceded, no_balls, hattricks, ducks, potm, coins, "
            "created_at, not_outs, fifties, hundreds, five_wickets, maidens, best_w, best_r) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [mi.match_id, pid, player.name, side, mi.team_name(side), result, a["runs"], a["balls"], a["fours"],
             a["sixes"], a["outs"], a["innings_batted"], a["highest"], a["wickets"], a["balls_bowled"],
             a["runs_conceded"], a["no_balls"], a["hattricks"], a["ducks"], int(potm), coins, ts,
             a["not_outs"], a["fifties"], a["hundreds"], a["five_wickets"], a["maidens"], a["best_w"], a["best_r"]]))
    await db.batch(stmts)
    return rewards


# ─────────────────────────────────────────────────────────── import / export
def export_profile(row: dict) -> dict:
    """Profile in the HandCricket JSON shape (plus our extended stats under 'bsw')."""
    out = {k: row.get(k) for k in HANDCRICKET_FIELDS}
    try:
        out["match_log"] = json.loads(row.get("match_log") or "[]")
    except Exception:
        out["match_log"] = []
    out["bsw"] = {k: row.get(k) for k in EXTENDED_FIELDS + ["coins", "total_earned", "title", "color"]}
    return out


def import_statements(data: dict, user_id: str, name: str) -> list:
    """Statements that merge a HandCricket-format profile into ours (adds counts, keeps the best highs)."""
    def num(key):
        try:
            return int(float(data.get(key) or 0))
        except Exception:
            return 0
    runs, wl = num("runs"), num("wickets_lost")
    return [
        _create_stmt(user_id, name),
        ("UPDATE profiles SET matches_played = matches_played + ?, matches_won = matches_won + ?, "
         "matches_lost = matches_lost + ?, runs = runs + ?, balls = balls + ?, wickets = wickets + ?, "
         "wickets_lost = wickets_lost + ?, highest_score = MAX(highest_score, ?), hattricks = hattricks + ?, "
         "ducks = ducks + ?, description = CASE WHEN description = '' THEN ? ELSE description END, updated_at = ? "
         "WHERE userid = ?",
         [num("matches_played"), num("matches_won"), num("matches_lost"), runs, num("balls"), num("wickets"), wl,
          num("highest_score"), num("hattricks"), num("ducks"), str(data.get("description") or "")[:200], now(), user_id]),
        ("UPDATE profiles SET batting_average = CASE WHEN wickets_lost > 0 THEN ROUND(CAST(runs AS REAL) / wickets_lost, 3) "
         "ELSE runs END WHERE userid = ?", [user_id]),
    ]
