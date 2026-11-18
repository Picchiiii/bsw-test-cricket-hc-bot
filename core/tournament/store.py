"""Database access for tournaments. Thin, explicit SQL — the rules live in actions.py / logic.py."""
import json
import time
import uuid

from core.tournament import schema


def now() -> int:
    return int(time.time())


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def _json(text, fallback):
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text) if text else fallback
    except Exception:
        return fallback


def _tournament(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = dict(row)
    row["settings"] = schema.merged(_json(row.get("settings"), {}))
    row["cache"] = _json(row.get("cache"), {})
    row["rosters_locked"] = bool(row.get("rosters_locked"))
    return row


def _fixture(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = dict(row)
    row["summary"] = _json(row.get("summary"), {})
    return row


# ─────────────────────────────────────────────────────────── tournaments
async def get(db, tournament_id: str) -> dict | None:
    return _tournament(await db.fetchone("SELECT * FROM tournaments WHERE tournament_id = ?", [str(tournament_id)]))


async def active_for_guild(db, guild_id) -> dict | None:
    """The one running tournament of a server (setup / registration / ongoing), if any."""
    return _tournament(await db.fetchone(
        "SELECT * FROM tournaments WHERE guild_id = ? AND status IN ('setup', 'registration', 'ongoing') "
        "ORDER BY created_at DESC LIMIT 1", [str(guild_id)]))


async def latest_for_guild(db, guild_id) -> dict | None:
    """The running tournament, otherwise the most recently finished one (for read-only commands)."""
    t = await active_for_guild(db, guild_id)
    if t is not None:
        return t
    return _tournament(await db.fetchone(
        "SELECT * FROM tournaments WHERE guild_id = ? ORDER BY COALESCE(ended_at, updated_at) DESC LIMIT 1",
        [str(guild_id)]))


async def list_for_guild(db, guild_id, limit: int = 25) -> list[dict]:
    rows = await db.fetch("SELECT * FROM tournaments WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
                          [str(guild_id), limit])
    return [_tournament(r) for r in rows]


async def list_active(db) -> list[dict]:
    rows = await db.fetch("SELECT * FROM tournaments WHERE status IN ('setup', 'registration', 'ongoing')")
    return [_tournament(r) for r in rows]


async def create(db, guild_id, guild_name: str, name: str, host_id, host_name: str) -> dict:
    tid = new_id()
    ts = now()
    await db.execute(
        "INSERT INTO tournaments (tournament_id, guild_id, guild_name, name, description, status, format, settings, cache, "
        "host_id, host_name, rosters_locked, created_at, updated_at) VALUES (?, ?, ?, ?, '', 'setup', 'league', ?, '{}', "
        "?, ?, 0, ?, ?)",
        [tid, str(guild_id), guild_name, name, json.dumps(schema.defaults()), str(host_id), host_name, ts, ts])
    return await get(db, tid)


_T_FIELDS = {"name", "description", "status", "format", "host_id", "host_name", "rosters_locked", "champion_team_id",
             "runner_up_team_id", "started_at", "ended_at", "guild_name"}


async def update(db, tournament_id: str, **fields):
    sets, args = [], []
    for k, v in fields.items():
        if k not in _T_FIELDS:
            raise KeyError(k)
        sets.append(f"{k} = ?")
        args.append(int(v) if isinstance(v, bool) else v)
    sets.append("updated_at = ?")
    args.append(now())
    await db.execute(f"UPDATE tournaments SET {', '.join(sets)} WHERE tournament_id = ?", args + [tournament_id])


async def save_settings(db, tournament_id: str, settings: dict):
    await db.execute("UPDATE tournaments SET settings = ?, format = ?, updated_at = ? WHERE tournament_id = ?",
                     [json.dumps(settings), settings.get("format", "league"), now(), tournament_id])


async def save_cache(db, tournament_id: str, cache: dict):
    await db.execute("UPDATE tournaments SET cache = ? WHERE tournament_id = ?",
                     [json.dumps(cache, separators=(",", ":")), tournament_id])


async def delete(db, tournament_id: str):
    await db.batch([(f"DELETE FROM {table} WHERE tournament_id = ?", [tournament_id]) for table in (
        "tournament_staff", "tournament_teams", "tournament_players", "tournament_invites", "tournament_fixtures",
        "tournament_audit", "tournaments")])


# ─────────────────────────────────────────────────────────── staff
async def list_staff(db, tournament_id: str) -> list[dict]:
    return await db.fetch("SELECT * FROM tournament_staff WHERE tournament_id = ? ORDER BY added_at", [tournament_id])


async def is_staff(db, tournament_id: str, user_id) -> bool:
    return await db.fetchone("SELECT 1 AS x FROM tournament_staff WHERE tournament_id = ? AND user_id = ?",
                             [tournament_id, str(user_id)]) is not None


async def add_staff(db, tournament_id: str, user_id, name: str, source: str = "manual"):
    await db.execute(
        "INSERT INTO tournament_staff (tournament_id, user_id, name, source, added_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(tournament_id, user_id) DO UPDATE SET name = excluded.name, "
        "source = CASE WHEN tournament_staff.source = 'manual' THEN 'manual' ELSE excluded.source END",
        [tournament_id, str(user_id), name, source, now()])


async def remove_staff(db, tournament_id: str, user_id) -> bool:
    res = await db.execute("DELETE FROM tournament_staff WHERE tournament_id = ? AND user_id = ?",
                           [tournament_id, str(user_id)])
    return bool(res["affected"])


async def replace_role_staff(db, tournament_id: str, members: list[tuple]):
    """Mirror of who currently holds an organiser role (source = 'role'), so the website can show Manage."""
    stmts = [("DELETE FROM tournament_staff WHERE tournament_id = ? AND source = 'role'", [tournament_id])]
    for uid, name in members:
        stmts.append((
            "INSERT INTO tournament_staff (tournament_id, user_id, name, source, added_at) VALUES (?, ?, ?, 'role', ?) "
            "ON CONFLICT(tournament_id, user_id) DO NOTHING", [tournament_id, str(uid), name, now()]))
    await db.batch(stmts)


# ─────────────────────────────────────────────────────────── teams
async def list_teams(db, tournament_id: str) -> list[dict]:
    return await db.fetch("SELECT * FROM tournament_teams WHERE tournament_id = ? ORDER BY created_at, name",
                          [tournament_id])


async def get_team(db, team_id: str) -> dict | None:
    return await db.fetchone("SELECT * FROM tournament_teams WHERE team_id = ?", [team_id])


def match_team(teams: list[dict], text) -> dict | None:
    """Find a team by id, name, tag or unique name prefix (case-insensitive)."""
    want = str(text or "").strip().lower()
    if not want:
        return None
    for key in ("team_id", "name", "tag"):
        for t in teams:
            if str(t.get(key) or "").lower() == want:
                return t
    starts = [t for t in teams if t["name"].lower().startswith(want)]
    if len(starts) == 1:
        return starts[0]
    return None


async def create_team(db, tournament_id: str, name: str, tag: str = "", captain_id=None, group_name: str = "") -> dict:
    team_id = new_id()
    await db.execute(
        "INSERT INTO tournament_teams (team_id, tournament_id, name, tag, captain_id, group_name, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
        [team_id, tournament_id, name, tag, str(captain_id) if captain_id else None, group_name, now()])
    return await get_team(db, team_id)


_TEAM_FIELDS = {"name", "tag", "captain_id", "vice_captain_id", "group_name", "seed", "role_id", "role_auto", "status"}


async def update_team(db, team_id: str, **fields):
    sets, args = [], []
    for k, v in fields.items():
        if k not in _TEAM_FIELDS:
            raise KeyError(k)
        sets.append(f"{k} = ?")
        args.append(v)
    await db.execute(f"UPDATE tournament_teams SET {', '.join(sets)} WHERE team_id = ?", args + [team_id])


async def delete_team(db, tournament_id: str, team_id: str):
    await db.batch([
        ("UPDATE tournament_players SET team_id = NULL WHERE tournament_id = ? AND team_id = ?", [tournament_id, team_id]),
        ("DELETE FROM tournament_invites WHERE tournament_id = ? AND team_id = ?", [tournament_id, team_id]),
        ("DELETE FROM tournament_teams WHERE team_id = ?", [team_id]),
    ])


# ─────────────────────────────────────────────────────────── players
async def list_players(db, tournament_id: str) -> list[dict]:
    return await db.fetch("SELECT * FROM tournament_players WHERE tournament_id = ? ORDER BY joined_at", [tournament_id])


async def get_player(db, tournament_id: str, user_id) -> dict | None:
    return await db.fetchone("SELECT * FROM tournament_players WHERE tournament_id = ? AND user_id = ?",
                             [tournament_id, str(user_id)])


async def roster(db, tournament_id: str, team_id: str) -> list[dict]:
    return await db.fetch("SELECT * FROM tournament_players WHERE tournament_id = ? AND team_id = ? AND status = 'active' "
                          "ORDER BY joined_at", [tournament_id, team_id])


async def upsert_player(db, tournament_id: str, user_id, name: str, team_id=None, keep_team: bool = True):
    if keep_team:
        await db.execute(
            "INSERT INTO tournament_players (tournament_id, user_id, name, team_id, status, joined_at) "
            "VALUES (?, ?, ?, ?, 'active', ?) ON CONFLICT(tournament_id, user_id) DO UPDATE SET name = excluded.name",
            [tournament_id, str(user_id), name, team_id, now()])
    else:
        await db.execute(
            "INSERT INTO tournament_players (tournament_id, user_id, name, team_id, status, joined_at) "
            "VALUES (?, ?, ?, ?, 'active', ?) ON CONFLICT(tournament_id, user_id) DO UPDATE SET name = excluded.name, "
            "team_id = excluded.team_id, status = 'active'",
            [tournament_id, str(user_id), name, team_id, now()])


async def set_player_team(db, tournament_id: str, user_id, team_id):
    await db.batch([
        ("UPDATE tournament_players SET team_id = ? WHERE tournament_id = ? AND user_id = ?",
         [team_id, tournament_id, str(user_id)]),
        ("DELETE FROM tournament_invites WHERE tournament_id = ? AND user_id = ?", [tournament_id, str(user_id)]),
    ])


async def set_player_status(db, tournament_id: str, user_id, status: str):
    await db.execute("UPDATE tournament_players SET status = ? WHERE tournament_id = ? AND user_id = ?",
                     [status, tournament_id, str(user_id)])


async def delete_player(db, tournament_id: str, user_id):
    await db.batch([
        ("DELETE FROM tournament_players WHERE tournament_id = ? AND user_id = ?", [tournament_id, str(user_id)]),
        ("DELETE FROM tournament_invites WHERE tournament_id = ? AND user_id = ?", [tournament_id, str(user_id)]),
    ])


# ─────────────────────────────────────────────────────────── invites
async def add_invite(db, tournament_id: str, team_id: str, user_id, invited_by):
    await db.execute(
        "INSERT INTO tournament_invites (tournament_id, team_id, user_id, invited_by, created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(tournament_id, team_id, user_id) DO UPDATE SET created_at = excluded.created_at",
        [tournament_id, team_id, str(user_id), str(invited_by), now()])


async def list_invites(db, tournament_id: str, user_id=None, team_id=None) -> list[dict]:
    sql, args = "SELECT * FROM tournament_invites WHERE tournament_id = ?", [tournament_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        args.append(str(user_id))
    if team_id is not None:
        sql += " AND team_id = ?"
        args.append(team_id)
    return await db.fetch(sql + " ORDER BY created_at", args)


async def remove_invite(db, tournament_id: str, team_id: str, user_id) -> bool:
    res = await db.execute("DELETE FROM tournament_invites WHERE tournament_id = ? AND team_id = ? AND user_id = ?",
                           [tournament_id, team_id, str(user_id)])
    return bool(res["affected"])


# ─────────────────────────────────────────────────────────── fixtures
async def list_fixtures(db, tournament_id: str) -> list[dict]:
    rows = await db.fetch("SELECT * FROM tournament_fixtures WHERE tournament_id = ? ORDER BY number", [tournament_id])
    return [_fixture(r) for r in rows]


async def get_fixture(db, fixture_id: str) -> dict | None:
    return _fixture(await db.fetchone("SELECT * FROM tournament_fixtures WHERE fixture_id = ?", [fixture_id]))


async def fixture_by_number(db, tournament_id: str, number: int) -> dict | None:
    return _fixture(await db.fetchone("SELECT * FROM tournament_fixtures WHERE tournament_id = ? AND number = ?",
                                      [tournament_id, int(number)]))


async def fixture_by_match(db, match_id: str) -> dict | None:
    return _fixture(await db.fetchone("SELECT * FROM tournament_fixtures WHERE match_id = ?", [match_id]))


async def next_fixture_number(db, tournament_id: str) -> int:
    row = await db.fetchone("SELECT COALESCE(MAX(number), 0) AS n FROM tournament_fixtures WHERE tournament_id = ?",
                            [tournament_id])
    return int(row["n"]) + 1


def fixture_insert(tournament_id: str, f: dict) -> tuple:
    ts = now()
    return (
        "INSERT INTO tournament_fixtures (fixture_id, tournament_id, number, stage, round, group_name, slot, team_a_id, "
        "team_b_id, source_a, source_b, status, summary, scheduled_at, reminded, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', '{}', ?, 0, ?, ?)",
        [f["fixture_id"], tournament_id, f["number"], f.get("stage", "group"), f.get("round", 1), f.get("group_name", ""),
         f.get("slot", 0), f.get("team_a_id"), f.get("team_b_id"), f.get("source_a", ""), f.get("source_b", ""),
         f.get("scheduled_at", 0), ts, ts])


_FX_FIELDS = {"team_a_id", "team_b_id", "source_a", "source_b", "status", "match_id", "channel_id", "winner_team_id",
              "result_type", "result_text", "summary", "scheduled_at", "reminded", "stage", "round", "group_name"}


def fixture_update_stmt(fixture_id: str, **fields) -> tuple:
    sets, args = [], []
    for k, v in fields.items():
        if k not in _FX_FIELDS:
            raise KeyError(k)
        sets.append(f"{k} = ?")
        args.append(json.dumps(v) if k == "summary" and not isinstance(v, str) else v)
    sets.append("updated_at = ?")
    args.append(now())
    return (f"UPDATE tournament_fixtures SET {', '.join(sets)} WHERE fixture_id = ?", args + [fixture_id])


async def update_fixture(db, fixture_id: str, **fields):
    sql, args = fixture_update_stmt(fixture_id, **fields)
    await db.execute(sql, args)


async def delete_fixtures(db, tournament_id: str, stages: tuple | None = None, only_unplayed: bool = False):
    sql, args = "DELETE FROM tournament_fixtures WHERE tournament_id = ?", [tournament_id]
    if stages:
        sql += f" AND stage IN ({','.join('?' for _ in stages)})"
        args += list(stages)
    if only_unplayed:
        sql += " AND status = 'scheduled'"
    await db.execute(sql, args)


# ─────────────────────────────────────────────────────────── audit & stats
async def add_audit(db, tournament_id: str, actor_id, actor_name: str, action: str, detail: str, source: str = "bot"):
    await db.execute(
        "INSERT INTO tournament_audit (tournament_id, actor_id, actor_name, action, detail, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [tournament_id, str(actor_id), actor_name, action, (detail or "")[:500], source, now()])


async def list_audit(db, tournament_id: str, limit: int = 30) -> list[dict]:
    return await db.fetch("SELECT * FROM tournament_audit WHERE tournament_id = ? ORDER BY id DESC LIMIT ?",
                          [tournament_id, limit])


async def match_stat_rows(db, tournament_id: str) -> list[dict]:
    """Every player's line from every finished match that currently counts for this tournament."""
    return await db.fetch(
        "SELECT p.* FROM player_match_stats p JOIN tournament_fixtures f ON f.match_id = p.match_id "
        "WHERE f.tournament_id = ? AND f.status = 'completed'", [tournament_id])


async def tournaments_of_user(db, user_id) -> dict:
    """{'playing': [...], 'running': [...]} tournament ids for a user (dashboard / `t mine`)."""
    uid = str(user_id)
    playing = await db.fetch("SELECT tournament_id, team_id FROM tournament_players WHERE user_id = ?", [uid])
    hosting = await db.fetch("SELECT tournament_id FROM tournaments WHERE host_id = ?", [uid])
    staff = await db.fetch("SELECT tournament_id FROM tournament_staff WHERE user_id = ?", [uid])
    return {"playing": playing, "running": list({r["tournament_id"] for r in hosting + staff})}
