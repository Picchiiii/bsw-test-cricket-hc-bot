"""Helpers for tournament tests: a server admin, quick team set-up and playing a fixture end to end."""
import asyncio

from harness import Player, World

STRONG = set()      # names of batters who score 6 a ball (their team wins); everyone else scores 2


FIRST_INNINGS_BOOST = set()   # batters who score 3 a ball in the first two innings only (lead, then a draw)


def strength_strategy(role, player, mi):
    if role == "bowler":
        return 1
    if player.member.name in FIRST_INNINGS_BOOST and mi is not None and mi.innings <= 2:
        return 3
    return 6 if player.member.name in STRONG else 2


def last(ch):
    return ch.messages[-1].text()


async def world():
    w = World()
    await w.setup()
    ch = w.channel("lobby")
    admin = Player(w, "Admin", strategy=strength_strategy)
    admin.member.guild_permissions.manage_guild = True
    return w, ch, admin


def mention(p):
    return p.member.mention if isinstance(p, Player) else p.mention


async def tour(w, who, ch, *args):
    """Run `+tour …` and return the text of the bot's reply."""
    before = len(ch.messages)
    await w.cmd("tour", who, ch, *[str(a) for a in args])
    return "\n".join(m.text() for m in ch.messages[before:])


async def make_teams(w, ch, admin, spec: dict, start=True, settings=None):
    """spec = {"Lions": ["L1", "L2"], ...}. Creates the tournament, registers everyone, builds the teams.

    Returns {team name: [Player, ...]} (the first player is the captain)."""
    out = await tour(w, admin, ch, "create", "BSW", "Cup")
    assert "created" in out, out
    base = {"overs": 2, "days": 4, "min_players": 1, "team_join": "open"}
    base.update(settings or {})
    for k, v in base.items():
        out = await tour(w, admin, ch, "set", k, v)
        assert "is now" in out, out
    assert "open" in await tour(w, admin, ch, "open")
    teams = {}
    for name, members in spec.items():
        players = [Player(w, n, strategy=strength_strategy) for n in members]
        teams[name] = players
        for p in players:
            assert "registered" in await tour(w, p, ch, "register")
        out = await tour(w, players[0], ch, "team", "create", name)
        assert "created" in out, out
        for p in players[1:]:
            out = await tour(w, p, ch, "team", "join", name)
            assert "joined" in out, out
    if start:
        out = await tour(w, admin, ch, "start")
        assert "has started" in out, out
    return teams


async def tournament(w, ch):
    from core.tournament import store
    return await store.latest_for_guild(w.db, ch.guild.id)


async def fixtures(w, ch):
    from core.tournament import store
    t = await tournament(w, ch)
    return await store.list_fixtures(w.db, t["tournament_id"])


async def play_fixture(w, number, teams_by_id_name, bat_first=None, channel=None):
    """Create a lobby, mark it as fixture `number`, fill both rosters, toss, start and play to a result."""
    from core.tournament import store
    ch = channel or w.channel("match")
    t = await tournament(w, ch)
    fx = await store.fixture_by_number(w.db, t["tournament_id"], number)
    names = {x["team_id"]: x["name"] for x in await store.list_teams(w.db, t["tournament_id"])}
    a, b = teams_by_id_name[names[fx["team_a_id"]]], teams_by_id_name[names[fx["team_b_id"]]]
    host = a[0]
    await w.cmd("create", host, ch)
    await w.cmd("tm", host, ch, str(number))
    assert "is now" in last(ch), last(ch)
    for p in a[1:] + b:
        await w.cmd("join", p, ch)
        assert "has joined" in last(ch), last(ch)
    mi = w.bot.active_matches[ch.id]
    assert [m.name for m in mi.teamA] == [p.member.name for p in a]
    assert [m.name for m in mi.teamB] == [p.member.name for p in b]
    await w.cmd("toss", host, ch)
    toss_msg = ch.messages[-1]
    await w.click(toss_msg, toss_msg.view.allowed_user, "Heads")
    await asyncio.sleep(0.01)
    bb_msg = ch.messages[-1]
    winner = bb_msg.view.allowed_user
    side = "A" if winner == mi.teamA_captain else "B"
    want = bat_first or "A"
    await w.click(bb_msg, winner, "Bat" if side == want else "Bowl")
    await w.cmd("start", host, ch)
    assert mi.game_started, last(ch)
    await w.finish(mi, timeout=90)
    return mi, ch
