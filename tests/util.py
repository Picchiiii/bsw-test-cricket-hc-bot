import asyncio
import functools
import json


def run(coro_fn):
    """Run an async test function in a fresh event loop (no pytest-asyncio needed)."""
    @functools.wraps(coro_fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(asyncio.wait_for(coro_fn(*args, **kwargs), 120))
    return wrapper


def check_card_consistency(card):
    """Every innings card must add up like a real scorecard."""
    bat_runs = sum(r["runs"] for r in card["batting"])
    assert bat_runs + card["extras"] == card["runs"], (bat_runs, card["extras"], card["runs"])
    bowl_runs = sum(r["runs"] for r in card["bowling"])
    assert bowl_runs == card["runs"], (bowl_runs, card["runs"])
    bowl_balls = sum(r["balls"] for r in card["bowling"])
    assert bowl_balls == card["balls"], (bowl_balls, card["balls"])
    outs = sum(1 for r in card["batting"] if r["is_out"])
    assert outs == card["wickets"], (outs, card["wickets"])
    bowler_wkts = sum(r["wickets"] for r in card["bowling"])
    non_bowler = sum(1 for r in card["batting"] if r["is_out"] and r["dismissal"] != "clash")
    assert bowler_wkts + non_bowler == card["wickets"]
    assert len(card["fow"]) == card["wickets"]
    bat_balls = sum(r["balls"] for r in card["batting"])
    assert bat_balls == card["balls"], (bat_balls, card["balls"])


async def match_row(db, match_id):
    row = await db.fetchone("SELECT * FROM matches WHERE match_id = ?", [match_id])
    if row and row.get("data"):
        row["data"] = json.loads(row["data"])
    return row
