import asyncio
import random

from harness import World, make_players
from util import run, check_card_consistency, match_row


@run
async def test_full_random_match_completes():
    random.seed(7)
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["Ash", "Bea", "Cal"])
    b = make_players(w, ["Dev", "Eli", "Fay"])
    mi = await w.setup_match(ch, a, b, overs=10, days=4)
    await w.finish(mi)
    assert mi.phase == "finished"
    assert mi.result and mi.result["type"] in ("win", "draw", "tie")
    assert ch.id not in w.bot.active_matches
    for n, card in mi.innings_scorecards.items():
        check_card_consistency(card)
    row = await match_row(w.db, mi.match_id)
    assert row["status"] == "completed"
    assert row["data"]["result"]["text"]
    left = await w.db.fetch("SELECT * FROM ongoing_matches")
    assert left == []
    profs = await w.db.fetch("SELECT * FROM profiles")
    assert len(profs) == 6
    assert all(p["matches_played"] == 1 for p in profs)
    print(mi.game.result_text(), [ (c["team_name"], c["runs"], c["wickets"]) for c in mi.innings_scorecards.values()])
