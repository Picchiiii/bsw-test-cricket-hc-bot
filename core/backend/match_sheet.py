"""Public JSON match sheet.

When a match finishes the bot posts `match_<id>.json`: everything that is public about the match — teams
and squads (captains, reps, substitutes, CPU players), rules, toss, every innings card (batting, bowling,
fall of wickets, extras), substitutions, per-player totals, the result and the Player of the Match.
It contains no Discord-private data (no DMs, no server/channel IDs, no tokens) — only what the website
and the result card already show. `+matchsheet [match id]` downloads it again later.
"""
import io
import json
import time

import discord

from core.config import config

SHEET_VERSION = 1


def _player_totals(data: dict) -> list:
    flags = {}
    for side in ("A", "B"):
        team = (data.get("teams") or {}).get(side) or {}
        for p in team.get("players", []):
            flags[p["id"]] = {"id": p["id"], "name": p["name"], "team": side, "team_name": team.get("name"),
                              "captain": bool(p.get("captain")), "rep": bool(p.get("rep")), "cpu": bool(p.get("cpu")),
                              "sub_for": p.get("sub_for"), "subbed_out": False}
        for p in team.get("subbed_out", []):
            flags.setdefault(p["id"], {"id": p["id"], "name": p["name"], "team": side, "team_name": team.get("name"),
                                       "captain": False, "rep": False, "cpu": False, "sub_for": None})
            flags[p["id"]]["subbed_out"] = True

    totals = {}

    def entry(pid, name, side):
        if pid not in totals:
            base = dict(flags.get(pid) or {"id": pid, "name": name, "team": side, "captain": False, "rep": False,
                                           "cpu": False, "sub_for": None, "subbed_out": False})
            base.update({"batting": {"innings": 0, "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "outs": 0,
                                     "highest": 0, "scores": []},
                         "bowling": {"balls": 0, "overs": "0.0", "runs": 0, "wickets": 0, "maidens": 0, "no_balls": 0}})
            totals[pid] = base
        return totals[pid]

    for card in data.get("innings", []):
        for r in card.get("batting", []):
            t = entry(r["id"], r["name"], card.get("team"))
            b = t["batting"]
            b["innings"] += 1
            b["runs"] += r["runs"]
            b["balls"] += r["balls"]
            b["fours"] += r.get("fours", 0)
            b["sixes"] += r.get("sixes", 0)
            b["outs"] += 1 if r.get("is_out") else 0
            b["highest"] = max(b["highest"], r["runs"])
            b["scores"].append({"innings": card.get("innings"), "runs": r["runs"], "balls": r["balls"],
                                "not_out": not r.get("is_out"), "status": r.get("status")})
            if r.get("rep"):
                t["rep"] = True
        for r in card.get("bowling", []):
            t = entry(r["id"], r["name"], card.get("bowling_team"))
            w = t["bowling"]
            w["balls"] += r["balls"]
            w["runs"] += r["runs"]
            w["wickets"] += r["wickets"]
            w["maidens"] += r.get("maidens", 0)
            w["no_balls"] += r.get("no_balls", 0)
    for t in totals.values():
        balls = t["bowling"]["balls"]
        t["bowling"]["overs"] = f"{balls // 6}.{balls % 6}"
    # everyone in the squads appears, even without figures
    for pid, f in flags.items():
        entry(pid, f["name"], f["team"])
    return sorted(totals.values(), key=lambda t: (t["team"] or "", -t["batting"]["runs"], -t["bowling"]["wickets"]))


def sheet_from_public(data: dict) -> dict:
    """Turn the public website snapshot of a match into the match sheet."""
    data = json.loads(json.dumps(data))   # deep copy
    result = data.get("result") or {}
    players = _player_totals(data)
    if result.get("potm"):
        result["potm_name"] = next((p["name"] for p in players if p["id"] == result["potm"]), None)
    teams = data.get("teams") or {}
    return {
        "sheet_version": SHEET_VERSION,
        "generated_by": config.bot_name,
        "generated_at": int(time.time()),
        "match_id": data.get("match_id"),
        "url": f"{config.website_url}/#/match/{data.get('match_id')}" if config.website_url else None,
        "status": data.get("status"),
        "title": f"{(teams.get('A') or {}).get('name', 'Team A')} v {(teams.get('B') or {}).get('name', 'Team B')}",
        "tournament": data.get("tournament"),
        "host": data.get("host"),
        "rules": data.get("settings"),
        "toss": data.get("toss"),
        "days_played": data.get("day"),
        "started_at": data.get("started_at"),
        "teams": teams,
        "result": result or None,
        "innings": data.get("innings", []),
        "substitutions": data.get("substitutions", []),
        "players": players,
        "cpu_match": bool(data.get("cpu_match")),
        "rewards": data.get("rewards", {}),
        "commentary": list(reversed(data.get("commentary", []))),
    }


def build_match_sheet(mi) -> dict:
    from core.backend.persistence import build_public
    sheet = sheet_from_public(build_public(mi))
    sheet["ended_at"] = int(mi.ended_at) if getattr(mi, "ended_at", None) else None
    return sheet


def sheet_bytes(sheet: dict) -> bytes:
    return json.dumps(sheet, indent=2, ensure_ascii=False).encode("utf-8")


def sheet_file(sheet: dict) -> discord.File:
    return discord.File(io.BytesIO(sheet_bytes(sheet)), filename=f"match_{sheet.get('match_id') or 'sheet'}.json")
