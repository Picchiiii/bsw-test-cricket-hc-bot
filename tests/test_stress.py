"""Randomised soak test: many full matches with AFKs, no-balls, ignored dropdowns and odd team sizes.

Set BSW_STRESS=<n> to run more matches (default 6).
"""
import asyncio
import os
import random

from harness import World, make_players
from util import run, check_card_consistency


def chaotic(role, player, mi):
    r = random.random()
    if r < 0.03:
        return None                    # AFK
    if role == "bowler":
        return 0 if r < 0.06 else random.randint(1, 6)   # occasional no-ball
    return random.randint(0, 6)


@run
async def test_random_matches_soak():
    n = int(os.getenv("BSW_STRESS", "6"))
    seed = int(os.getenv("BSW_SEED", "1234"))
    rng = random.Random(seed)
    w = World()
    await w.setup()
    jobs = []
    for i in range(n):
        random.seed(seed + i)
        na, nb = rng.randint(1, 5), rng.randint(1, 5)
        ch = w.channel(f"soak{i}")
        a = make_players(w, [f"S{i}A{j}" for j in range(na)], strategy=chaotic)
        b = make_players(w, [f"S{i}B{j}" for j in range(nb)], strategy=chaotic)
        settings = {}
        if rng.random() < 0.5:
            settings["innings_overs"] = 0
        if rng.random() < 0.3:
            settings["max_no_balls_per_over"] = 2
        if rng.random() < 0.3:
            settings["last_man_bats"] = True
        w.follow_on = rng.random() < 0.5
        mi = await w.setup_match(ch, a, b, overs=rng.choice([1, 2, 3]), days=rng.randint(1, 5),
                                 bat_first=rng.choice("AB"), **settings)
        jobs.append(mi)
    w.captain_mode = os.getenv("BSW_CAPTAINS", "pick")
    results = await asyncio.gather(*(w.finish(mi, timeout=240) for mi in jobs), return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, errors
    for mi in jobs:
        assert mi.phase == "finished", (mi.match_id, mi.phase)
        assert mi.result["type"] in ("win", "draw", "tie")
        for c in mi.innings_scorecards.values():
            check_card_consistency(c)
        # all channel embeds were valid (the fake raises on any Discord limit violation)
    for ch in w.channels:
        assert "Something went wrong" not in ch.all_text()
    assert not w.bot.active_matches
    rows = await w.db.fetch("SELECT status FROM matches")
    assert len(rows) == n and all(r["status"] == "completed" for r in rows)
