import io
import json
import random
import time

import discord

from harness import World, make_players, random_strategy
from util import run
from core.config import config
from core.economy import profiles

ECO = config.economy


def last(ch):
    return ch.messages[-1].text()


async def world_with_match(seed=1):
    random.seed(seed)
    w = World()
    w.bot.owner_ids.add(999)
    await w.setup()
    ch = w.channel()
    a = make_players(w, ["Ana", "Ben", "Cy"], strategy=random_strategy)
    b = make_players(w, ["Dee", "Eve", "Flo"], strategy=random_strategy)
    mi = await w.setup_match(ch, a, b, overs=10, days=4)
    await w.finish(mi)
    return w, ch, mi, a, b


@run
async def test_profiles_after_match_match_scorecards_and_coins():
    w, ch, mi, a, b = await world_with_match()
    rows = {r["name"]: r for r in await w.db.fetch("SELECT * FROM profiles")}
    for p in a + b:
        pid = str(p.member.id)
        agg = profiles.aggregate_player(mi, pid)
        r = rows[p.member.name]
        assert r["runs"] == agg["runs"] and r["balls"] == agg["balls"] and r["wickets"] == agg["wickets"]
        assert r["wickets_lost"] == agg["outs"] and r["highest_score"] == agg["highest"]
        assert r["batting_average"] == profiles.batting_average(agg["runs"], agg["outs"])
        assert r["coins"] == ECO["start_balance"] + mi.rewards[pid]
        log = json.loads(r["match_log"])
        assert log[-1]["match_id"] == mi.match_id
    res = mi.result
    if res["type"] == "win":
        winners = {p.name for p in mi.team(res["winner"])}
        assert all(rows[n]["matches_won"] == 1 for n in winners)
        assert sum(r["matches_lost"] for r in rows.values()) == 3
    # ledger matches balances
    for r in rows.values():
        total = sum(t["amount"] for t in await w.db.fetch("SELECT amount FROM transactions WHERE userid = ?", [r["userid"]]))
        assert total == r["coins"]
    # recording again (e.g. after a restart) never double counts
    again = await profiles.record_match(w.db, mi)
    assert again == {k: v for k, v in mi.rewards.items()}
    rows2 = {r["name"]: r for r in await w.db.fetch("SELECT * FROM profiles")}
    assert all(rows2[n]["matches_played"] == 1 for n in rows2)
    # the result embed lists coins earned
    assert "Coins earned" in ch.all_text()


@run
async def test_stat_commands_render():
    w, ch, mi, a, b = await world_with_match(2)
    for name, args in (("profile", ()), ("me", (b[0].member,)), ("userstats", ()), ("us", (a[1].member,)),
                       ("matchlog", ()), ("lb", ()), ("lb", ("wickets",)), ("lb", ("coins", "server")),
                       ("lb", ("average",)), ("lb", ("potm",)), ("lb", ("hs",)), ("balance", ())):
        await w.cmd(name, a[0], ch, *args)
        assert ch.messages[-1].embed is not None or "No one" in last(ch), (name, last(ch))
    await w.cmd("lb", a[0], ch, "nonsense")
    assert "Pick one of" in last(ch)
    await w.cmd("setdesc", a[0], ch, text="Opening bat @everyone")
    await w.cmd("profile", a[0], ch)
    assert "Opening bat" in last(ch) and "@everyone" not in last(ch).replace("@​everyone", "")
    await w.cmd("export", a[0], ch)
    f = ch.messages[-1].files[0]
    data = json.loads(f.fp.getvalue())
    for key in ("userid", "matches_played", "matches_won", "runs", "balls", "wickets", "wickets_lost",
                "highest_score", "hattricks", "ducks", "batting_average", "match_log"):
        assert key in data
    assert isinstance(data["match_log"], list)


@run
async def test_daily_weekly_give_and_shop():
    w = World()
    await w.setup()
    ch = w.channel()
    p, q = make_players(w, ["Payer", "Payee"])
    await w.cmd("daily", p, ch)
    assert f"{ECO['daily']}" in last(ch)
    await w.cmd("daily", p, ch)
    assert "already claimed" in last(ch)
    # streak: claimed 30h ago -> streak 2 with bonus
    await w.db.execute("UPDATE profiles SET daily_last = ? WHERE userid = ?", [int(time.time()) - 30 * 3600, str(p.member.id)])
    await w.cmd("daily", p, ch)
    assert "Streak: **2**" in last(ch) and f"+{ECO['daily_streak_bonus']} bonus" in last(ch)
    # streak broken after > 48h
    await w.db.execute("UPDATE profiles SET daily_last = ? WHERE userid = ?", [int(time.time()) - 50 * 3600, str(p.member.id)])
    await w.cmd("daily", p, ch)
    assert "Streak: **1**" in last(ch)
    await w.cmd("weekly", p, ch)
    await w.cmd("weekly", p, ch)
    assert "ready" in last(ch)
    bal = (await profiles.get_profile(w.db, p.member.id))["coins"]
    expected = ECO["start_balance"] + ECO["daily"] * 3 + ECO["daily_streak_bonus"] + ECO["weekly"]
    assert bal == expected
    await w.cmd("give", p, ch, q.member, bal + 1)
    assert "don't have enough" in last(ch)
    await w.cmd("give", p, ch, p.member, 5)
    assert "yourself" in last(ch)
    await w.cmd("give", p, ch, q.member, -5)
    assert "positive" in last(ch)
    await w.cmd("give", p, ch, q.member, 100)
    assert (await profiles.get_profile(w.db, q.member.id))["coins"] == ECO["start_balance"] + 100
    assert (await profiles.get_profile(w.db, p.member.id))["coins"] == bal - 100
    # shop
    await profiles.add_coins(w.db, p.member.id, 10_000, "test top-up")
    bal += 10_000
    await w.cmd("shop", p, ch)
    assert "Shop" in last(ch)
    await w.cmd("buy", p, ch, item_name="test_legend")
    assert "You need" in last(ch)
    await w.cmd("buy", p, ch, item_name="Royal Blue")
    await w.cmd("buy", p, ch, item_name="badge_fire")
    await w.cmd("buy", p, ch, item_name="rookie")
    await w.cmd("buy", p, ch, item_name="rookie")
    assert "already own" in last(ch)
    prof = await profiles.get_profile(w.db, p.member.id)
    assert prof["color"] == "2F5DD6" and prof["title"] == "Rookie" and "🔥" in prof["badges"]
    assert prof["coins"] == bal - 100 - 2000 - 3000 - 500
    await w.cmd("unequip", p, ch, "title")
    assert (await profiles.get_profile(w.db, p.member.id))["title"] == ""
    await w.cmd("equip", p, ch, item_name="rookie")
    assert (await profiles.get_profile(w.db, p.member.id))["title"] == "Rookie"
    await w.cmd("equip", p, ch, item_name="gold")
    assert "don't own" in last(ch)
    await w.cmd("inventory", p, ch)
    assert "Royal Blue" in last(ch)
    await w.cmd("buy", p, ch, item_name="no such thing")
    assert "No item" in last(ch)


@run
async def test_owner_coin_tools_and_handcricket_import():
    w = World()
    owner = make_players(w, ["Owner"])[0]
    w.bot.owner_ids.add(owner.member.id)
    await w.setup()
    ch = w.channel()
    user = make_players(w, ["Imported"])[0]
    await w.cmd("addcoins", owner, ch, user.member, 1000)
    assert (await profiles.get_profile(w.db, user.member.id))["coins"] == ECO["start_balance"] + 1000
    await w.cmd("removecoins", owner, ch, user.member, 10_000)
    assert (await profiles.get_profile(w.db, user.member.id))["coins"] == 0
    await w.cmd("addcoins", user, ch, user.member, 1000)
    assert "Only the bot owner" in last(ch)
    hc = {"userid": user.member.id, "name": "Imported", "description": "from HandCricket", "matches_played": 10,
          "matches_won": 6, "matches_lost": 4, "runs": 300, "balls": 250, "wickets": 12, "wickets_lost": 8,
          "highest_score": 77, "hattricks": 1, "ducks": 2, "batting_average": 37.5, "match_log": []}
    msg = discord.Message(channel=ch, author=owner.member, content="+importprofile")

    class Att:
        async def read(self):
            return json.dumps(hc).encode()
    msg.attachments = [Att()]
    ctx = w.ctx(owner.member, ch)
    ctx.message = msg
    await w.bot.invoke_command("importprofile", ctx, user.member)
    prof = await profiles.get_profile(w.db, user.member.id)
    assert prof["matches_played"] == 10 and prof["runs"] == 300 and prof["highest_score"] == 77
    assert prof["batting_average"] == 37.5 and prof["description"] == "from HandCricket"
