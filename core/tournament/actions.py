"""Everything that changes a tournament.

Both the Discord commands and the website call `perform(db, tournament, actor, action, params)`, so the
rules are enforced in exactly one place. Actions only touch the database and return a `Result` whose
`effects` tell the bot what to do in Discord afterwards (announce, sync roles, DM someone…).

Permission levels: "any" (every member of the server), "organizer" (host, staff, organiser roles,
Manage Server) and "owner" (bot owner). Captain-only rules are checked inside the action.
"""
import random
import re
import time
from dataclasses import dataclass, field

from core.config import config
from core.tournament import logic, schema, store


class TournamentError(Exception):
    """A rule was broken; the message is shown to the user as-is."""


@dataclass
class Actor:
    id: str
    name: str
    organizer: bool = False
    owner: bool = False
    source: str = "bot"


@dataclass
class Result:
    message: str
    effects: list = field(default_factory=list)
    data: dict = field(default_factory=dict)


ACTIONS: dict[str, dict] = {}


def action(name: str, level: str = "organizer", statuses: tuple = schema.ACTIVE_STATUSES):
    def deco(fn):
        ACTIONS[name] = {"fn": fn, "level": level, "statuses": statuses}
        return fn
    return deco


def now() -> int:
    return int(time.time())


P = config.prefix


async def perform(db, t: dict, actor: Actor, name: str, params: dict | None = None) -> Result:
    spec = ACTIONS.get(name)
    if spec is None:
        raise TournamentError(f"Unknown action `{name}`.")
    if spec["level"] == "owner" and not actor.owner:
        raise TournamentError("Only the bot owner can do that.")
    if spec["level"] == "organizer" and not (actor.organizer or actor.owner):
        raise TournamentError("Only tournament organisers can do that.")
    if t["status"] not in spec["statuses"]:
        raise TournamentError(f"**{t['name']}** is {t['status']} — that can't be changed any more.")
    result = await spec["fn"](db, t, actor, dict(params or {}))
    await store.add_audit(db, t["tournament_id"], actor.id, actor.name, name, _plain(result.message), actor.source)
    return result


def _plain(text: str) -> str:
    return re.sub(r"[*_`]", "", text or "")


# ─────────────────────────────────────────────────────────── helpers
def _can_manage(actor: Actor) -> bool:
    return actor.organizer or actor.owner


async def _team(db, t, ref, teams=None) -> dict:
    teams = teams if teams is not None else await store.list_teams(db, t["tournament_id"])
    team = store.match_team(teams, ref)
    if team is None:
        raise TournamentError(f"I couldn't find a team called **{ref}**. See `{P}tour teams`.")
    return team


def _user(params: dict) -> tuple[str, str]:
    uid = str(params.get("user_id") or "").strip()
    if not uid.isdigit():
        raise TournamentError("Pick a member (mention them or use their ID).")
    return uid, str(params.get("user_name") or f"User {uid}")


def _clean_name(text, what="name", lo=2, hi=32) -> str:
    name = re.sub(r"\s+", " ", str(text or "")).strip()
    name = re.sub(r"[`*_~|<>@]", "", name)
    if not lo <= len(name) <= hi:
        raise TournamentError(f"The {what} must be {lo}–{hi} characters.")
    return name


def _make_tag(name: str, taken: set) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    base = "".join(w[0] for w in words)[:4].upper() if len(words) > 1 else (words[0][:3].upper() if words else "TM")
    tag, n = base, 2
    while tag.lower() in taken:
        tag = f"{base[:3]}{n}"
        n += 1
    return tag


def _clean_tag(text, taken: set) -> str:
    tag = re.sub(r"[^A-Za-z0-9]", "", str(text or "")).upper()
    if not 1 <= len(tag) <= 5:
        raise TournamentError("A team tag is 1–5 letters or numbers.")
    if tag.lower() in taken:
        raise TournamentError(f"The tag **{tag}** is already taken.")
    return tag


async def _captain_team(db, t, actor: Actor, allow_vice: bool = True) -> dict:
    """The team the actor captains (or vice-captains)."""
    for team in await store.list_teams(db, t["tournament_id"]):
        if team["captain_id"] == actor.id or (allow_vice and team["vice_captain_id"] == actor.id):
            return team
    raise TournamentError("Only a team captain can do that.")


def _rosters_open(t, actor: Actor):
    if _can_manage(actor):
        return
    if t["rosters_locked"]:
        raise TournamentError("Rosters are locked. Ask an organiser if a change is needed.")


async def _team_scope(db, t, actor: Actor, params: dict, allow_vice: bool = True) -> dict:
    """Organisers name a team; captains act on their own."""
    if _can_manage(actor) and params.get("team"):
        return await _team(db, t, params["team"])
    team = await _captain_team(db, t, actor, allow_vice)
    _rosters_open(t, actor)
    return team


def _vs(fx, names) -> str:
    return f"{names.get(fx.get('team_a_id'), 'TBD')} v {names.get(fx.get('team_b_id'), 'TBD')}"


def _names(teams) -> dict:
    return {t["team_id"]: t["name"] for t in teams}


async def _fixture(db, t, params) -> dict:
    try:
        number = int(str(params.get("number")).lstrip("#"))
    except (TypeError, ValueError):
        raise TournamentError(f"Give the match number, e.g. `{P}tour fixtures` shows them.")
    fx = await store.fixture_by_number(db, t["tournament_id"], number)
    if fx is None:
        raise TournamentError(f"There is no match #{number}.")
    return fx


# ─────────────────────────────────────────────────────────── settings & lifecycle
@action("settings.set")
async def settings_set(db, t, actor, params):
    key = str(params.get("key") or "").lower().strip()
    spec = schema.SETTINGS.get(key)
    if spec is None:
        raise TournamentError(f"There is no setting called `{key}`. See `{P}tour settings`.")
    if spec.get("owner_only") and not actor.owner:
        raise TournamentError("Prize settings create coins, so only the bot owner can change them.")
    try:
        value = schema.coerce(key, params.get("value"))
    except schema.SettingError as e:
        raise TournamentError(str(e))
    fixtures = await store.list_fixtures(db, t["tournament_id"])
    structural = {"format", "groups", "rounds"}
    if key in structural and (t["status"] == "ongoing" or any(f["status"] != "scheduled" for f in fixtures)):
        raise TournamentError(f"`{key}` can't change once the tournament has started.")
    if key == "qualifiers" and any(f["stage"] != "group" and f["stage"] != "extra" for f in fixtures) \
            and t["settings"]["format"] != "knockout":
        raise TournamentError("The knockout bracket already exists, so `qualifiers` can't change.")
    settings = dict(t["settings"])
    settings[key] = value
    if settings["min_players"] > settings["max_players"]:
        raise TournamentError("`min_players` can't be more than `max_players`.")
    await store.save_settings(db, t["tournament_id"], settings)
    effects = []
    if key in structural and fixtures:
        await store.delete_fixtures(db, t["tournament_id"], only_unplayed=True)
        effects.append(("note", "The fixture list was cleared because the format changed."))
    if spec["type"] in ("role", "roles") or key == "auto_team_roles":
        effects.append(("roles",))
    extra = " The fixture list was cleared — it is rebuilt when you start." if key in structural and fixtures else ""
    return Result(f"⚙️ **{spec['label']}** (`{key}`) is now **{schema.describe(key, value)}**.{extra}", effects)


@action("rename")
async def rename(db, t, actor, params):
    name = _clean_name(params.get("name"), "tournament name", 3, 60)
    await store.update(db, t["tournament_id"], name=name)
    return Result(f"✏️ The tournament is now called **{name}**.")


@action("describe")
async def describe(db, t, actor, params):
    text = str(params.get("text") or "").strip()[:600]
    await store.update(db, t["tournament_id"], description=text)
    return Result("📝 Description updated." if text else "📝 Description cleared.")


@action("registration.open", statuses=("setup", "registration"))
async def registration_open(db, t, actor, params):
    if t["status"] == "registration":
        raise TournamentError("Registration is already open.")
    await store.update(db, t["tournament_id"], status="registration")
    return Result(f"📝 Registration for **{t['name']}** is **open**.", [
        ("announce", f"📝 **Registration is open for {t['name']}!**\nSign up with `{P}tour register`"
                     + (f", then create a team with `{P}tour team create <name>`." if t["settings"]["team_creation"] == "open"
                        else " — the organisers will place you in a team."))])


@action("registration.close", statuses=("setup", "registration"))
async def registration_close(db, t, actor, params):
    if t["status"] != "registration":
        raise TournamentError("Registration isn't open.")
    await store.update(db, t["tournament_id"], status="setup")
    return Result("🔒 Registration is **closed**.", [("announce", f"🔒 Registration for **{t['name']}** is now closed.")])


@action("rosters.lock")
async def rosters_lock(db, t, actor, params):
    await store.update(db, t["tournament_id"], rosters_locked=True)
    return Result("🔒 Rosters are **locked** — only organisers can change teams now.")


@action("rosters.unlock")
async def rosters_unlock(db, t, actor, params):
    await store.update(db, t["tournament_id"], rosters_locked=False)
    return Result("🔓 Rosters are **unlocked** — captains can change their squads.")


def _seed_order(teams: list[dict]) -> list[dict]:
    """Seeded teams first (1 is best), then everyone else in the order they were created."""
    return sorted(teams, key=lambda x: (0 if (x.get("seed") or 0) > 0 else 1, x.get("seed") or 0, x.get("created_at") or 0))


async def _draw_groups(db, t, teams, mode: str = "random") -> dict:
    count = t["settings"]["groups"]
    active = [x for x in teams if x["status"] == "active"]
    if len(active) < count * 2:
        raise TournamentError(f"{count} pools need at least {count * 2} teams (there are {len(active)}).")
    order = _seed_order(active)
    if mode == "random":
        random.shuffle(order)
    pools = {schema.GROUP_LETTERS[i]: [] for i in range(count)}
    letters = list(pools)
    for i, team in enumerate(order):                 # serpentine: A B C C B A A B C …
        lap, pos = divmod(i, count)
        letter = letters[pos] if lap % 2 == 0 else letters[count - 1 - pos]
        pools[letter].append(team)
    stmts = []
    for letter, members in pools.items():
        for team in members:
            stmts.append(("UPDATE tournament_teams SET group_name = ? WHERE team_id = ?", [letter, team["team_id"]]))
            team["group_name"] = letter
    await db.batch(stmts)
    return pools


@action("groups.draw", statuses=("setup", "registration"))
async def groups_draw(db, t, actor, params):
    if t["settings"]["format"] != "groups":
        raise TournamentError(f"Pools are only used by the `groups` format (`{P}tour set format groups`).")
    teams = await store.list_teams(db, t["tournament_id"])
    mode = "seeded" if str(params.get("mode") or "").lower().startswith("seed") else "random"
    pools = await _draw_groups(db, t, teams, mode)
    await store.delete_fixtures(db, t["tournament_id"], only_unplayed=True)
    text = "\n".join(f"**Pool {k}:** " + ", ".join(x["name"] for x in v) for k, v in pools.items())
    return Result(f"🎲 Pools drawn ({mode}):\n{text}", [("announce", f"🎲 **{t['name']} — the pools**\n{text}")])


async def _build_group_fixtures(db, t, teams) -> int:
    """(Re)create the round-robin fixtures. Returns how many were created."""
    settings = t["settings"]
    active = [x for x in teams if x["status"] == "active"]
    if settings["format"] == "groups":
        unplaced = [x for x in active if not x["group_name"]]
        if unplaced or len({x["group_name"] for x in active}) != settings["groups"]:
            await _draw_groups(db, t, teams, "seeded" if any(x.get("seed") for x in active) else "random")
        pools: dict[str, list] = {}
        for x in active:
            pools.setdefault(x["group_name"], []).append(x)
    else:
        if any(x["group_name"] for x in teams):
            await db.execute("UPDATE tournament_teams SET group_name = '' WHERE tournament_id = ?", [t["tournament_id"]])
            for x in teams:
                x["group_name"] = ""
        pools = {"": active}
    for letter, members in pools.items():
        if len(members) < 2:
            raise TournamentError(f"Pool {letter or 'table'} needs at least 2 teams.")
    schedules = {g: logic.round_robin([x["team_id"] for x in _seed_order(m)], settings["rounds"])
                 for g, m in sorted(pools.items())}
    rows, number = [], await store.next_fixture_number(db, t["tournament_id"])
    for rnd in range(max(len(s) for s in schedules.values())):
        for g, sched in schedules.items():
            if rnd >= len(sched):
                continue
            for a, b in sched[rnd]:
                rows.append({"fixture_id": store.new_id(), "number": number, "stage": "group", "round": rnd + 1,
                             "group_name": g, "team_a_id": a, "team_b_id": b})
                number += 1
    await db.batch([store.fixture_insert(t["tournament_id"], r) for r in rows])
    return len(rows)


async def _build_knockout(db, t, seeds: list) -> list[dict]:
    plan = logic.build_knockout(seeds)
    if not plan:
        raise TournamentError("A knockout needs at least 2 teams.")
    number = await store.next_fixture_number(db, t["tournament_id"])
    ids = {f["key"]: store.new_id() for f in plan}
    rows = []
    for f in plan:
        rows.append({"fixture_id": ids[f["key"]], "number": number, "stage": f["stage"], "round": f["round"],
                     "slot": f["slot"], "group_name": "", "team_a_id": f["team_a"], "team_b_id": f["team_b"],
                     "source_a": f"W:{ids[f['source_a']]}" if f["source_a"] else "",
                     "source_b": f"W:{ids[f['source_b']]}" if f["source_b"] else ""})
        number += 1
    await db.batch([store.fixture_insert(t["tournament_id"], r) for r in rows])
    return rows


async def _generate(db, t) -> str:
    teams = await store.list_teams(db, t["tournament_id"])
    active = [x for x in teams if x["status"] == "active"]
    if len(active) < 2:
        raise TournamentError("You need at least 2 teams.")
    fixtures = await store.list_fixtures(db, t["tournament_id"])
    if any(f["status"] != "scheduled" for f in fixtures):
        raise TournamentError("Matches have already been played, so the fixture list can't be rebuilt.")
    await store.delete_fixtures(db, t["tournament_id"])
    if t["settings"]["format"] == "knockout":
        rows = await _build_knockout(db, t, [x["team_id"] for x in _seed_order(active)])
        return f"a knockout bracket of **{len(rows)}** matches"
    n = await _build_group_fixtures(db, t, teams)
    return f"**{n}** {'pool' if t['settings']['format'] == 'groups' else 'league'} matches"


@action("fixtures.generate", statuses=("setup", "registration"))
async def fixtures_generate(db, t, actor, params):
    what = await _generate(db, t)
    return Result(f"🗓️ Built {what}. See them with `{P}tour fixtures`.")


@action("start", statuses=("setup", "registration"))
async def start(db, t, actor, params):
    tid = t["tournament_id"]
    teams = await store.list_teams(db, tid)
    active = [x for x in teams if x["status"] == "active"]
    if len(active) < 2:
        raise TournamentError("You need at least 2 teams to start.")
    players = await store.list_players(db, tid)
    sizes = {}
    for pl in players:
        if pl["team_id"] and pl["status"] == "active":
            sizes[pl["team_id"]] = sizes.get(pl["team_id"], 0) + 1
    need = t["settings"]["min_players"]
    short = [x["name"] for x in active if sizes.get(x["team_id"], 0) < need]
    if short:
        raise TournamentError(f"These teams have fewer than {need} player(s): **{', '.join(short)}**. "
                              f"Add players, lower `min_players`, or remove the team.")
    if not await store.list_fixtures(db, tid):
        await _generate(db, t)
    await store.update(db, tid, status="ongoing", rosters_locked=True, started_at=now())
    fixtures = await store.list_fixtures(db, tid)
    names = _names(teams)
    first = [f for f in fixtures if f["team_a_id"] and f["team_b_id"]][:8]
    lines = "\n".join(f"`#{f['number']}` {_vs(f, names)}" for f in first)
    more = f"\n…and {len(fixtures) - len(first)} more (`{P}tour fixtures`)" if len(fixtures) > len(first) else ""
    return Result(
        f"🏆 **{t['name']}** has started with **{len(active)}** teams and **{len(fixtures)}** matches. Rosters are locked.\n"
        f"To play a match: `{P}create`, then `{P}tm <match number>`.",
        [("announce", f"🏆 **{t['name']} is under way!** {len(active)} teams, {len(fixtures)} matches.\n{lines}{more}\n"
                      f"Captains: open a lobby with `{P}create`, then `{P}tm <match number>`."), ("roles",)])


async def _finish(db, t, champion_id, runner_up_id, note: str = "") -> list:
    await store.update(db, t["tournament_id"], status="completed", ended_at=now(), champion_team_id=champion_id,
                       runner_up_team_id=runner_up_id)
    teams = _names(await store.list_teams(db, t["tournament_id"]))
    text = f"🏆 **{t['name']} is over!**"
    if champion_id:
        text += f"\n🥇 Champions: **{teams.get(champion_id, '?')}**"
    if runner_up_id:
        text += f"\n🥈 Runners-up: **{teams.get(runner_up_id, '?')}**"
    if note:
        text += f"\n{note}"
    return [("finale", text), ("prizes",)]


async def _maybe_advance(db, t) -> list:
    """After a result: build the knockout when the pools are done, or close the tournament after the final."""
    tid = t["tournament_id"]
    settings = t["settings"]
    fixtures = await store.list_fixtures(db, tid)
    final = next((f for f in fixtures if f["stage"] == "final"), None)
    if final is not None and final["status"] in logic.DONE and final["winner_team_id"]:
        if not settings["auto_advance"]:
            return [("note", f"The final is decided — close the tournament with `{P}tour end`.")]
        loser = final["team_b_id"] if final["winner_team_id"] == final["team_a_id"] else final["team_a_id"]
        return await _finish(db, t, final["winner_team_id"], loser)
    if settings["format"] == "knockout" or not settings["auto_advance"]:
        return []
    group = [f for f in fixtures if f["stage"] == "group"]
    if not group or any(f["status"] not in logic.DONE + ("cancelled",) for f in group):
        return []
    if any(f["stage"] in logic.KNOCKOUT_STAGES for f in fixtures):
        return []
    teams = await store.list_teams(db, tid)
    tables = logic.compute_standings(teams, fixtures, settings)
    seeds = logic.pick_qualifiers(tables, settings["qualifiers"])
    if len(seeds) >= 2:
        rows = await _build_knockout(db, t, seeds)
        names = _names(teams)
        lines = "\n".join(f"`#{r['number']}` {logic.stage_label(r['stage'])}: {_vs(r, names)}" for r in rows)
        return [("announce", f"🎯 **{t['name']} — the knockout stage is set!**\n{lines}")]
    if len(tables) == 1:
        table = next(iter(tables.values()))
        if table:
            return await _finish(db, t, table[0]["team_id"], table[1]["team_id"] if len(table) > 1 else None,
                                 "Decided on the points table.")
    return [("note", f"All pool matches are done. Close the tournament with `{P}tour end <champion team>`.")]


@action("advance", statuses=("ongoing",))
async def advance(db, t, actor, params):
    tid = t["tournament_id"]
    settings = t["settings"]
    if settings["format"] == "knockout":
        raise TournamentError("A knockout advances by itself as results come in.")
    fixtures = await store.list_fixtures(db, tid)
    if any(f["stage"] in logic.KNOCKOUT_STAGES for f in fixtures):
        raise TournamentError("The knockout bracket already exists.")
    group = [f for f in fixtures if f["stage"] == "group"]
    left = [f for f in group if f["status"] not in logic.DONE + ("cancelled",)]
    if left and not params.get("force"):
        raise TournamentError(f"{len(left)} pool match(es) are still to be played. Add `force` to advance anyway.")
    teams = await store.list_teams(db, tid)
    seeds = logic.pick_qualifiers(logic.compute_standings(teams, fixtures, settings), settings["qualifiers"])
    if len(seeds) < 2:
        raise TournamentError(f"Fewer than 2 teams qualify (`qualifiers` is {settings['qualifiers']}).")
    rows = await _build_knockout(db, t, seeds)
    names = _names(teams)
    lines = "\n".join(f"`#{r['number']}` {logic.stage_label(r['stage'])}: {_vs(r, names)}" for r in rows)
    return Result(f"🎯 Knockout bracket built:\n{lines}",
                  [("announce", f"🎯 **{t['name']} — the knockout stage is set!**\n{lines}")])


@action("end", statuses=("ongoing",))
async def end(db, t, actor, params):
    tid = t["tournament_id"]
    teams = await store.list_teams(db, tid)
    fixtures = await store.list_fixtures(db, tid)
    champion = runner = None
    if params.get("champion"):
        champion = (await _team(db, t, params["champion"], teams))["team_id"]
    else:
        final = next((f for f in fixtures if f["stage"] == "final" and f["winner_team_id"]), None)
        if final:
            champion = final["winner_team_id"]
            runner = final["team_b_id"] if champion == final["team_a_id"] else final["team_a_id"]
        else:
            tables = logic.compute_standings(teams, fixtures, t["settings"])
            if len(tables) == 1 and any(r["played"] for r in next(iter(tables.values()))):
                table = next(iter(tables.values()))
                champion = table[0]["team_id"]
                runner = table[1]["team_id"] if len(table) > 1 else None
    if params.get("runner_up"):
        runner = (await _team(db, t, params["runner_up"], teams))["team_id"]
    effects = await _finish(db, t, champion, runner)
    names = _names(teams)
    return Result(f"🏁 **{t['name']}** is finished" + (f" — champions **{names.get(champion)}**." if champion else "."),
                  effects)


@action("cancel")
async def cancel(db, t, actor, params):
    await store.update(db, t["tournament_id"], status="cancelled", ended_at=now())
    return Result(f"🛑 **{t['name']}** was cancelled. Its matches and stats stay on record.",
                  [("announce", f"🛑 **{t['name']}** has been cancelled."), ("unbind_all",)])


@action("reopen", statuses=("completed", "cancelled"))
async def reopen(db, t, actor, params):
    other = await store.active_for_guild(db, t["guild_id"])
    if other is not None:
        raise TournamentError(f"**{other['name']}** is already running in this server.")
    status = "ongoing" if t.get("started_at") else "setup"
    await store.update(db, t["tournament_id"], status=status, ended_at=None, champion_team_id=None,
                       runner_up_team_id=None)
    return Result(f"↩️ **{t['name']}** is open again ({status}).")


@action("delete", statuses=schema.STATUSES)
async def delete(db, t, actor, params):
    await store.delete(db, t["tournament_id"])
    return Result(f"🗑️ **{t['name']}** was deleted.", [("unbind_all",), ("deleted",)])


# ─────────────────────────────────────────────────────────── staff
@action("staff.add")
async def staff_add(db, t, actor, params):
    uid, name = _user(params)
    await store.add_staff(db, t["tournament_id"], uid, name)
    return Result(f"🛡️ **{name}** is now a tournament organiser.")


@action("staff.remove")
async def staff_remove(db, t, actor, params):
    uid, name = _user(params)
    if not await store.remove_staff(db, t["tournament_id"], uid):
        raise TournamentError(f"**{name}** isn't on the staff list.")
    return Result(f"🛡️ **{name}** is no longer an organiser.")


@action("host.transfer")
async def host_transfer(db, t, actor, params):
    uid, name = _user(params)
    if not (actor.owner or actor.id == t["host_id"] or params.get("_manage_guild")):
        raise TournamentError("Only the current host (or a server manager) can hand over the tournament.")
    await store.update(db, t["tournament_id"], host_id=uid, host_name=name)
    return Result(f"👑 **{name}** is now the tournament host.")


@action("announce")
async def announce(db, t, actor, params):
    text = str(params.get("text") or "").strip()[:1500]
    if not text:
        raise TournamentError("What should I announce?")
    return Result("📣 Announcement sent.", [("announce", f"📣 **{t['name']}**\n{text}", True)])


@action("roles.sync")
async def roles_sync(db, t, actor, params):
    return Result("🎭 Syncing roles…", [("roles",)])


# ─────────────────────────────────────────────────────────── registration (players)
@action("register", level="any")
async def register(db, t, actor, params):
    tid = t["tournament_id"]
    if _can_manage(actor) and params.get("user_id"):
        uid, name = _user(params)
    else:
        uid, name = actor.id, actor.name
        if not _can_manage(actor):
            if t["status"] != "registration":
                raise TournamentError("Registration isn't open right now.")
            if params.get("_missing_role"):
                raise TournamentError("You need the registration role to sign up.")
    existing = await store.get_player(db, tid, uid)
    if existing is not None:
        if existing["status"] == "banned":
            raise TournamentError(f"**{name}** is banned from this tournament.")
        raise TournamentError(f"**{name}** is already registered.")
    await store.upsert_player(db, tid, uid, name)
    how = {"invite": "wait for a captain's invite", "open": f"join a team with `{P}tour team join <team>`",
           "staff": "the organisers will place you in a team"}[t["settings"]["team_join"]]
    create = f" Create your own team with `{P}tour team create <name>`, or" if t["settings"]["team_creation"] == "open" else " Next:"
    return Result(f"✅ **{name}** is registered for **{t['name']}**.{create} {how}.", [("roles",)])


@action("unregister", level="any")
async def unregister(db, t, actor, params):
    tid = t["tournament_id"]
    if _can_manage(actor) and params.get("user_id"):
        uid, name = _user(params)
    else:
        uid, name = actor.id, actor.name
        _rosters_open(t, actor)
    pl = await store.get_player(db, tid, uid)
    if pl is None:
        raise TournamentError(f"**{name}** isn't registered.")
    team = await store.get_team(db, pl["team_id"]) if pl["team_id"] else None
    if team is not None and team["captain_id"] == uid:
        raise TournamentError(f"**{name}** captains **{team['name']}** — hand over the captaincy or disband the team first.")
    await store.delete_player(db, tid, uid)
    if team is not None and team["vice_captain_id"] == uid:
        await store.update_team(db, team["team_id"], vice_captain_id=None)
    return Result(f"👋 **{name}** left the tournament.", [("unrole", uid, team["team_id"] if team else None, True)])


@action("player.ban")
async def player_ban(db, t, actor, params):
    tid = t["tournament_id"]
    uid, name = _user(params)
    pl = await store.get_player(db, tid, uid)
    team = await store.get_team(db, pl["team_id"]) if pl and pl["team_id"] else None
    if team is not None and team["captain_id"] == uid:
        raise TournamentError(f"**{name}** captains **{team['name']}** — change the captain first.")
    await store.upsert_player(db, tid, uid, name, None, keep_team=False)
    await store.set_player_status(db, tid, uid, "banned")
    return Result(f"⛔ **{name}** is banned from **{t['name']}**.", [("unrole", uid, team["team_id"] if team else None, True)])


@action("player.unban")
async def player_unban(db, t, actor, params):
    uid, name = _user(params)
    pl = await store.get_player(db, t["tournament_id"], uid)
    if pl is None or pl["status"] != "banned":
        raise TournamentError(f"**{name}** isn't banned.")
    await store.delete_player(db, t["tournament_id"], uid)
    return Result(f"✅ **{name}** can register again.")


# ─────────────────────────────────────────────────────────── teams
@action("team.create", level="any")
async def team_create(db, t, actor, params):
    tid = t["tournament_id"]
    settings = t["settings"]
    teams = await store.list_teams(db, tid)
    manage = _can_manage(actor)
    if not manage:
        if settings["team_creation"] != "open":
            raise TournamentError("Only organisers create teams in this tournament.")
        if t["status"] != "registration":
            raise TournamentError("Teams can only be created while registration is open.")
    elif t["status"] == "ongoing" and not params.get("force"):
        raise TournamentError("The tournament has started, so the fixture list is fixed. New teams can't be added.")
    if len(teams) >= settings["max_teams"]:
        raise TournamentError(f"The tournament is full ({settings['max_teams']} teams).")
    name = _clean_name(params.get("name"), "team name")
    if any(x["name"].lower() == name.lower() for x in teams):
        raise TournamentError(f"There is already a team called **{name}**.")
    taken = {x["tag"].lower() for x in teams if x["tag"]}
    tag = _clean_tag(params["tag"], taken) if params.get("tag") else _make_tag(name, taken)
    captain_id = captain_name = None
    if manage and params.get("user_id"):
        captain_id, captain_name = _user(params)
    elif not manage:
        captain_id, captain_name = actor.id, actor.name
    if captain_id:
        pl = await store.get_player(db, tid, captain_id)
        if pl is not None and pl["status"] == "banned":
            raise TournamentError(f"**{captain_name}** is banned from this tournament.")
        if pl is not None and pl["team_id"]:
            raise TournamentError(f"**{captain_name}** is already in a team. Leave it first.")
        if pl is None and not manage:
            raise TournamentError(f"Register first with `{P}tour register`.")
    team = await store.create_team(db, tid, name, tag, captain_id)
    if t["status"] != "ongoing":
        await store.delete_fixtures(db, tid, only_unplayed=True)     # the fixture list is rebuilt for the new field
    if captain_id:
        await store.upsert_player(db, tid, captain_id, captain_name, team["team_id"], keep_team=False)
    lead = f" Captain: **{captain_name}**." if captain_id else f" Set a captain with `{P}tour team captain {tag} @user`."
    return Result(f"🛡️ Team **{name}** `[{tag}]` created.{lead}", [("roles",)], {"team_id": team["team_id"]})


@action("team.rename", level="any")
async def team_rename(db, t, actor, params):
    team = await _team_scope(db, t, actor, params, allow_vice=False)
    teams = await store.list_teams(db, t["tournament_id"])
    name = _clean_name(params.get("name"), "team name")
    if any(x["name"].lower() == name.lower() and x["team_id"] != team["team_id"] for x in teams):
        raise TournamentError(f"There is already a team called **{name}**.")
    await store.update_team(db, team["team_id"], name=name)
    return Result(f"✏️ **{team['name']}** is now **{name}**.", [("roles",)])


@action("team.tag", level="any")
async def team_tag(db, t, actor, params):
    team = await _team_scope(db, t, actor, params, allow_vice=False)
    teams = await store.list_teams(db, t["tournament_id"])
    tag = _clean_tag(params.get("tag"), {x["tag"].lower() for x in teams if x["tag"] and x["team_id"] != team["team_id"]})
    await store.update_team(db, team["team_id"], tag=tag)
    return Result(f"🏷️ **{team['name']}** now uses the tag **{tag}**.")


async def _team_has_fixtures(db, t, team_id) -> bool:
    return any(team_id in (f["team_a_id"], f["team_b_id"]) for f in await store.list_fixtures(db, t["tournament_id"]))


@action("team.delete", level="any")
async def team_delete(db, t, actor, params):
    team = await _team_scope(db, t, actor, params, allow_vice=False)
    if await _team_has_fixtures(db, t, team["team_id"]):
        if t["status"] == "ongoing":
            raise TournamentError(f"**{team['name']}** has fixtures. Use `{P}tour team withdraw {team['tag']}` instead.")
        await store.delete_fixtures(db, t["tournament_id"], only_unplayed=True)
    members = await store.roster(db, t["tournament_id"], team["team_id"])
    await store.delete_team(db, t["tournament_id"], team["team_id"])
    effects = [("unrole", m["user_id"], team["team_id"], True, team.get("role_id")) for m in members]
    if team.get("role_auto") and team.get("role_id"):
        effects.append(("delete_role", team["role_id"]))
    return Result(f"🗑️ Team **{team['name']}** was disbanded. Its players are free agents.", effects)


@action("team.withdraw", statuses=("ongoing",))
async def team_withdraw(db, t, actor, params):
    team = await _team(db, t, params.get("team"))
    await store.update_team(db, team["team_id"], status="withdrawn")
    effects, given = [], 0
    for fx in await store.list_fixtures(db, t["tournament_id"]):
        if fx["status"] != "scheduled" or team["team_id"] not in (fx["team_a_id"], fx["team_b_id"]):
            continue
        other = fx["team_b_id"] if fx["team_a_id"] == team["team_id"] else fx["team_a_id"]
        if not other:
            continue
        res = await apply_result(db, t, fx, "walkover", other, None, {"decided_by": "walkover"})
        effects += res.effects
        given += 1
    return Result(f"🏳️ **{team['name']}** withdrew. {given} remaining match(es) were awarded to their opponents.", effects)


@action("team.group", statuses=("setup", "registration"))
async def team_group(db, t, actor, params):
    if t["settings"]["format"] != "groups":
        raise TournamentError("Pools are only used by the `groups` format.")
    team = await _team(db, t, params.get("team"))
    letter = str(params.get("group") or "").strip().upper()[:1]
    allowed = schema.GROUP_LETTERS[:t["settings"]["groups"]]
    if letter not in allowed or not letter:
        raise TournamentError(f"Choose a pool from **{', '.join(allowed)}**.")
    await store.update_team(db, team["team_id"], group_name=letter)
    await store.delete_fixtures(db, t["tournament_id"], only_unplayed=True)
    return Result(f"📦 **{team['name']}** is in **Pool {letter}**.")


@action("team.seed", statuses=("setup", "registration"))
async def team_seed(db, t, actor, params):
    team = await _team(db, t, params.get("team"))
    try:
        seed = int(params.get("seed"))
    except (TypeError, ValueError):
        raise TournamentError("The seed is a number (1 = top seed, 0 = unseeded).")
    if not 0 <= seed <= 64:
        raise TournamentError("The seed must be between 0 and 64.")
    await store.update_team(db, team["team_id"], seed=seed)
    await store.delete_fixtures(db, t["tournament_id"], only_unplayed=True)
    return Result(f"🌱 **{team['name']}** is {'seed ' + str(seed) if seed else 'unseeded'}.")


@action("team.role")
async def team_role(db, t, actor, params):
    team = await _team(db, t, params.get("team"))
    try:
        role_id = schema.coerce("player_role", params.get("role"))
    except schema.SettingError:
        raise TournamentError("Mention a role (or `none` to clear it).")
    await store.update_team(db, team["team_id"], role_id=role_id, role_auto=0)
    return Result(f"🎭 **{team['name']}** " + (f"uses <@&{role_id}>." if role_id else "has no team role now."), [("roles",)])


@action("team.captain", level="any")
async def team_captain(db, t, actor, params):
    team = await _team_scope(db, t, actor, params, allow_vice=False)
    uid, name = _user(params)
    tid = t["tournament_id"]
    pl = await store.get_player(db, tid, uid)
    if _can_manage(actor):
        if pl is not None and pl["status"] == "banned":
            raise TournamentError(f"**{name}** is banned from this tournament.")
        if pl is None or pl["team_id"] != team["team_id"]:
            await _check_squad_space(db, t, team)
            await store.upsert_player(db, tid, uid, name, team["team_id"], keep_team=False)
    elif pl is None or pl["team_id"] != team["team_id"]:
        raise TournamentError(f"**{name}** isn't in **{team['name']}**.")
    fields = {"captain_id": uid}
    if team["vice_captain_id"] == uid:
        fields["vice_captain_id"] = None
    await store.update_team(db, team["team_id"], **fields)
    return Result(f"🧢 **{name}** now captains **{team['name']}**.", [("roles",)])


@action("team.vice", level="any")
async def team_vice(db, t, actor, params):
    team = await _team_scope(db, t, actor, params, allow_vice=False)
    if str(params.get("user_id") or "").lower() in ("", "none"):
        await store.update_team(db, team["team_id"], vice_captain_id=None)
        return Result(f"**{team['name']}** has no vice-captain now.")
    uid, name = _user(params)
    pl = await store.get_player(db, t["tournament_id"], uid)
    if pl is None or pl["team_id"] != team["team_id"]:
        raise TournamentError(f"**{name}** isn't in **{team['name']}**.")
    if team["captain_id"] == uid:
        raise TournamentError(f"**{name}** is already the captain.")
    await store.update_team(db, team["team_id"], vice_captain_id=uid)
    return Result(f"🧢 **{name}** is now vice-captain of **{team['name']}**.")


async def _check_squad_space(db, t, team):
    size = len(await store.roster(db, t["tournament_id"], team["team_id"]))
    if size >= t["settings"]["max_squad"]:
        raise TournamentError(f"**{team['name']}** is full ({t['settings']['max_squad']} players).")


@action("team.add")
async def team_add(db, t, actor, params):
    tid = t["tournament_id"]
    team = await _team(db, t, params.get("team"))
    uid, name = _user(params)
    pl = await store.get_player(db, tid, uid)
    if pl is not None and pl["status"] == "banned":
        raise TournamentError(f"**{name}** is banned from this tournament.")
    if pl is not None and pl["team_id"] == team["team_id"]:
        raise TournamentError(f"**{name}** is already in **{team['name']}**.")
    old = await store.get_team(db, pl["team_id"]) if pl and pl["team_id"] else None
    if old is not None and old["captain_id"] == uid:
        raise TournamentError(f"**{name}** captains **{old['name']}** — change that team's captain first.")
    await _check_squad_space(db, t, team)
    await store.upsert_player(db, tid, uid, name, team["team_id"], keep_team=False)
    await store.set_player_team(db, tid, uid, team["team_id"])
    effects = [("roles",)]
    if old is not None:
        if old["vice_captain_id"] == uid:
            await store.update_team(db, old["team_id"], vice_captain_id=None)
        effects.insert(0, ("unrole", uid, old["team_id"], False, old.get("role_id")))
    if not team["captain_id"]:
        await store.update_team(db, team["team_id"], captain_id=uid)
    moved = f" (moved from {old['name']})" if old else ""
    return Result(f"➕ **{name}** joined **{team['name']}**{moved}.", effects)


@action("team.remove", level="any")
async def team_remove(db, t, actor, params):
    """Organiser: remove anyone from their team. Captain: kick a player from their own team."""
    tid = t["tournament_id"]
    uid, name = _user(params)
    pl = await store.get_player(db, tid, uid)
    if pl is None or not pl["team_id"]:
        raise TournamentError(f"**{name}** isn't in a team.")
    team = await store.get_team(db, pl["team_id"])
    if not _can_manage(actor):
        mine = await _captain_team(db, t, actor)
        _rosters_open(t, actor)
        if mine["team_id"] != team["team_id"]:
            raise TournamentError(f"**{name}** isn't in your team.")
    if team["captain_id"] == uid:
        raise TournamentError(f"**{name}** is the captain — choose a new captain first (`{P}tour team captain`).")
    await store.set_player_team(db, tid, uid, None)
    if team["vice_captain_id"] == uid:
        await store.update_team(db, team["team_id"], vice_captain_id=None)
    return Result(f"➖ **{name}** was removed from **{team['name']}** and is a free agent.",
                  [("unrole", uid, team["team_id"], False, team.get("role_id"))])


@action("team.invite", level="any")
async def team_invite(db, t, actor, params):
    tid = t["tournament_id"]
    team = await _team_scope(db, t, actor, params)
    uid, name = _user(params)
    if not _can_manage(actor) and t["settings"]["team_join"] == "staff":
        raise TournamentError("Organisers place players in teams in this tournament.")
    pl = await store.get_player(db, tid, uid)
    if pl is None:
        raise TournamentError(f"**{name}** hasn't registered yet (`{P}tour register`).")
    if pl["status"] == "banned":
        raise TournamentError(f"**{name}** is banned from this tournament.")
    if pl["team_id"]:
        raise TournamentError(f"**{name}** is already in a team.")
    await _check_squad_space(db, t, team)
    await store.add_invite(db, tid, team["team_id"], uid, actor.id)
    return Result(f"✉️ **{name}** was invited to **{team['name']}**. They accept with `{P}tour accept {team['tag']}`.",
                  [("invite", uid, team["team_id"], team["name"])])


async def _join_team(db, t, team, uid, name):
    tid = t["tournament_id"]
    await _check_squad_space(db, t, team)
    await store.set_player_team(db, tid, uid, team["team_id"])
    if not team["captain_id"]:
        await store.update_team(db, team["team_id"], captain_id=uid)


@action("invite.accept", level="any")
async def invite_accept(db, t, actor, params):
    tid = t["tournament_id"]
    _rosters_open(t, actor)
    pl = await store.get_player(db, tid, actor.id)
    if pl is None:
        raise TournamentError(f"Register first with `{P}tour register`.")
    if pl["team_id"]:
        raise TournamentError("You're already in a team.")
    invites = await store.list_invites(db, tid, user_id=actor.id)
    if not invites:
        raise TournamentError("You have no invites.")
    teams = await store.list_teams(db, tid)
    if params.get("team"):
        team = await _team(db, t, params["team"], teams)
        if not any(i["team_id"] == team["team_id"] for i in invites):
            raise TournamentError(f"**{team['name']}** hasn't invited you.")
    elif len(invites) == 1:
        team = next((x for x in teams if x["team_id"] == invites[0]["team_id"]), None)
        if team is None:
            raise TournamentError("That team no longer exists.")
    else:
        names = ", ".join(f"**{x['name']}**" for x in teams if any(i["team_id"] == x["team_id"] for i in invites))
        raise TournamentError(f"You have several invites ({names}). Use `{P}tour accept <team>`.")
    await _join_team(db, t, team, actor.id, actor.name)
    return Result(f"🤝 **{actor.name}** joined **{team['name']}**!", [("roles",)])


@action("invite.decline", level="any")
async def invite_decline(db, t, actor, params):
    tid = t["tournament_id"]
    invites = await store.list_invites(db, tid, user_id=actor.id)
    if not invites:
        raise TournamentError("You have no invites.")
    if params.get("team"):
        team = await _team(db, t, params["team"])
        await store.remove_invite(db, tid, team["team_id"], actor.id)
        return Result(f"You declined the invite from **{team['name']}**.")
    for i in invites:
        await store.remove_invite(db, tid, i["team_id"], actor.id)
    return Result("You declined your invite(s).")


@action("team.join", level="any")
async def team_join(db, t, actor, params):
    tid = t["tournament_id"]
    _rosters_open(t, actor)
    if t["settings"]["team_join"] != "open":
        raise TournamentError("Teams are joined by invite in this tournament." if t["settings"]["team_join"] == "invite"
                              else "Organisers place players in teams in this tournament.")
    pl = await store.get_player(db, tid, actor.id)
    if pl is None:
        raise TournamentError(f"Register first with `{P}tour register`.")
    if pl["status"] == "banned":
        raise TournamentError("You are banned from this tournament.")
    if pl["team_id"]:
        raise TournamentError("You're already in a team.")
    team = await _team(db, t, params.get("team"))
    if team["status"] != "active":
        raise TournamentError(f"**{team['name']}** has withdrawn.")
    await _join_team(db, t, team, actor.id, actor.name)
    return Result(f"🤝 **{actor.name}** joined **{team['name']}**!", [("roles",)])


@action("team.leave", level="any")
async def team_leave(db, t, actor, params):
    tid = t["tournament_id"]
    _rosters_open(t, actor)
    pl = await store.get_player(db, tid, actor.id)
    if pl is None or not pl["team_id"]:
        raise TournamentError("You're not in a team.")
    team = await store.get_team(db, pl["team_id"])
    members = await store.roster(db, tid, team["team_id"])
    if team["captain_id"] == actor.id:
        if len(members) > 1:
            raise TournamentError(f"You're the captain — hand over with `{P}tour team captain @user` or disband with "
                                  f"`{P}tour team disband`.")
        if await _team_has_fixtures(db, t, team["team_id"]):
            raise TournamentError("Your team has fixtures. Ask an organiser to withdraw the team.")
        await store.delete_team(db, tid, team["team_id"])
        effects = [("unrole", actor.id, team["team_id"], True, team.get("role_id"))]
        if team.get("role_auto") and team.get("role_id"):
            effects.append(("delete_role", team["role_id"]))
        return Result(f"👋 **{actor.name}** left and **{team['name']}** was disbanded.", effects)
    await store.set_player_team(db, tid, actor.id, None)
    if team["vice_captain_id"] == actor.id:
        await store.update_team(db, team["team_id"], vice_captain_id=None)
    return Result(f"👋 **{actor.name}** left **{team['name']}**.",
                  [("unrole", actor.id, team["team_id"], False, team.get("role_id"))])


@action("players.autofill")
async def players_autofill(db, t, actor, params):
    """Spread the free agents over the teams with the fewest players."""
    tid = t["tournament_id"]
    teams = [x for x in await store.list_teams(db, tid) if x["status"] == "active"]
    if not teams:
        raise TournamentError("Create some teams first.")
    players = await store.list_players(db, tid)
    free = [pl for pl in players if not pl["team_id"] and pl["status"] == "active"]
    if not free:
        raise TournamentError("There are no free agents.")
    sizes = {x["team_id"]: 0 for x in teams}
    for pl in players:
        if pl["team_id"] in sizes and pl["status"] == "active":
            sizes[pl["team_id"]] += 1
    random.shuffle(free)
    cap = t["settings"]["max_squad"]
    placed = 0
    by_id = {x["team_id"]: x for x in teams}
    for pl in free:
        team_id = min(sizes, key=lambda k: sizes[k])
        if sizes[team_id] >= cap:
            break
        await store.set_player_team(db, tid, pl["user_id"], team_id)
        if not by_id[team_id]["captain_id"]:
            await store.update_team(db, team_id, captain_id=pl["user_id"])
            by_id[team_id]["captain_id"] = pl["user_id"]
        sizes[team_id] += 1
        placed += 1
    left = len(free) - placed
    return Result(f"🎲 Placed **{placed}** free agent(s) into teams." + (f" {left} couldn't be placed (squads full)." if left else ""),
                  [("roles",)])


# ─────────────────────────────────────────────────────────── fixtures
@action("fixture.add")
async def fixture_add(db, t, actor, params):
    tid = t["tournament_id"]
    teams = await store.list_teams(db, tid)
    a = await _team(db, t, params.get("team_a"), teams)
    b = await _team(db, t, params.get("team_b"), teams)
    if a["team_id"] == b["team_id"]:
        raise TournamentError("A team can't play itself.")
    stage = str(params.get("stage") or "group").lower()
    if stage in ("friendly", "exhibition", "x"):
        stage = "extra"
    if stage not in ("group", "extra"):
        raise TournamentError("Extra fixtures are `group` (counts for the table) or `extra` (doesn't count).")
    when = 0
    if params.get("time"):
        try:
            when = logic.parse_time(params["time"], now())
        except ValueError as e:
            raise TournamentError(str(e))
    number = await store.next_fixture_number(db, tid)
    group = a["group_name"] if a["group_name"] == b["group_name"] else ""
    sql, args = store.fixture_insert(tid, {"fixture_id": store.new_id(), "number": number, "stage": stage, "round": 0,
                                          "group_name": group, "team_a_id": a["team_id"], "team_b_id": b["team_id"],
                                          "scheduled_at": when})
    await db.execute(sql, args)
    return Result(f"🗓️ Added match `#{number}`: **{a['name']} v {b['name']}**"
                  + (" (doesn't count for the table)" if stage == "extra" else "") + (f" at <t:{when}:F>" if when else "") + ".")


@action("fixture.remove")
async def fixture_remove(db, t, actor, params):
    fx = await _fixture(db, t, params)
    if fx["status"] != "scheduled":
        raise TournamentError(f"Match #{fx['number']} is {fx['status']} — reset it first (`{P}tour fixture reset {fx['number']}`).")
    fixtures = await store.list_fixtures(db, t["tournament_id"])
    if fx["stage"] in logic.KNOCKOUT_STAGES or any(f"W:{fx['fixture_id']}" in (f["source_a"], f["source_b"]) for f in fixtures):
        raise TournamentError("Bracket matches can't be removed — award a walkover instead.")
    await db.execute("DELETE FROM tournament_fixtures WHERE fixture_id = ?", [fx["fixture_id"]])
    return Result(f"🗑️ Match `#{fx['number']}` was removed.", [("unbind", fx["fixture_id"])])


@action("fixture.schedule")
async def fixture_schedule(db, t, actor, params):
    fx = await _fixture(db, t, params)
    try:
        when = logic.parse_time(params.get("time"), now())
    except ValueError as e:
        raise TournamentError(str(e))
    if when and when < now() - 300:
        raise TournamentError("That time is in the past.")
    await store.update_fixture(db, fx["fixture_id"], scheduled_at=when, reminded=0)
    names = _names(await store.list_teams(db, t["tournament_id"]))
    if not when:
        return Result(f"🕒 Match `#{fx['number']}` has no set time now.")
    return Result(f"🕒 Match `#{fx['number']}` ({_vs(fx, names)}) is set for <t:{when}:F> (<t:{when}:R>).",
                  [("announce", f"🕒 **{t['name']}** — match `#{fx['number']}` **{_vs(fx, names)}** will be played "
                                f"<t:{when}:F> (<t:{when}:R>).")])


@action("fixture.teams")
async def fixture_teams(db, t, actor, params):
    fx = await _fixture(db, t, params)
    if fx["status"] != "scheduled":
        raise TournamentError(f"Match #{fx['number']} is {fx['status']}.")
    teams = await store.list_teams(db, t["tournament_id"])
    a = await _team(db, t, params.get("team_a"), teams)
    b = await _team(db, t, params.get("team_b"), teams)
    if a["team_id"] == b["team_id"]:
        raise TournamentError("A team can't play itself.")
    await store.update_fixture(db, fx["fixture_id"], team_a_id=a["team_id"], team_b_id=b["team_id"], source_a="", source_b="")
    return Result(f"🔁 Match `#{fx['number']}` is now **{a['name']} v {b['name']}**.", [("unbind", fx["fixture_id"])])


async def apply_result(db, t, fx: dict, result_type: str, winner_id, text: str | None, summary: dict | None = None,
                       match_id: str | None = None) -> Result:
    """Store a fixture's result and do everything that follows from it (bracket, table, next stage)."""
    tid = t["tournament_id"]
    settings = t["settings"]
    teams = await store.list_teams(db, tid)
    names = _names(teams)
    summary = dict(summary or {})
    a, b = fx["team_a_id"], fx["team_b_id"]
    knockout = fx["stage"] in logic.KNOCKOUT_STAGES
    pending = False
    if result_type in ("win", "walkover"):
        if winner_id not in (a, b):
            raise TournamentError("The winner must be one of the two teams in that match.")
        base = text or (f"{names.get(winner_id)} won" if result_type == "win" else f"{names.get(winner_id)} won by walkover")
    else:
        winner_id = None
        base = text or {"draw": "Match drawn", "tie": "Match tied", "no_result": "No result"}[result_type]
        if knockout:
            leader = summary.get("fi_leader")
            if settings["knockout_draw_rule"] == "first_innings" and leader in (a, b):
                winner_id = leader
                summary["decided_by"] = "first_innings"
                base += f" — {names.get(leader)} go through on first-innings lead"
            else:
                pending = True
                base += " — organiser to decide who goes through"
    stmts = [store.fixture_update_stmt(fx["fixture_id"], status="walkover" if result_type == "walkover" else "completed",
                                       winner_team_id=winner_id, result_type=result_type, result_text=base,
                                       summary=summary, match_id=match_id if match_id is not None else fx.get("match_id"))]
    effects = []
    stmts += await _advance_stmts(db, t, fx, winner_id)
    await db.batch(stmts)
    head = f"`#{fx['number']}` {logic.stage_label(fx['stage'])}" + (f" · Pool {fx['group_name']}" if fx["group_name"] else "")
    line = f"**{names.get(a, 'TBD')} v {names.get(b, 'TBD')}** — {base}"
    effects.append(("result", f"📋 **{t['name']}** · {head}\n{line}", match_id or fx.get("match_id")))
    if pending:
        effects.append(("note", f"Match #{fx['number']} was a {result_type} in the knockout. An organiser decides who "
                                f"advances: `{P}tour result {fx['number']} <team>`."))
    fresh = await store.get(db, tid)
    effects += await _maybe_advance(db, fresh)
    return Result(f"{head}: {line}", effects)


async def _advance_stmts(db, t, fx, winner_id) -> list:
    """Put the winner into the next bracket match (refusing if that match was already played)."""
    stmts = []
    key = f"W:{fx['fixture_id']}"
    for nxt in await store.list_fixtures(db, t["tournament_id"]):
        for side, src in (("team_a_id", "source_a"), ("team_b_id", "source_b")):
            if nxt[src] != key:
                continue
            if nxt[side] == winner_id:
                continue
            if nxt["status"] != "scheduled":
                raise TournamentError(f"Match #{nxt['number']} (the next round) has already been played. "
                                      f"Reset it first with `{P}tour fixture reset {nxt['number']}`.")
            stmts.append(store.fixture_update_stmt(nxt["fixture_id"], **{side: winner_id}))
    return stmts


@action("fixture.result", statuses=("ongoing",))
async def fixture_result(db, t, actor, params):
    """Enter or correct a result by hand: a team (wins), draw, tie or nr."""
    fx = await _fixture(db, t, params)
    if not fx["team_a_id"] or not fx["team_b_id"]:
        raise TournamentError(f"Match #{fx['number']} doesn't have both teams yet.")
    if fx["status"] == "live" and not params.get("force"):
        raise TournamentError(f"Match #{fx['number']} is being played right now. Add `force` to overrule it.")
    outcome = str(params.get("outcome") or "").strip()
    low = outcome.lower()
    kinds = {"draw": "draw", "drawn": "draw", "tie": "tie", "tied": "tie", "nr": "no_result", "noresult": "no_result",
             "no_result": "no_result", "abandoned": "no_result"}
    keep = fx["status"] in logic.DONE          # correcting a played match keeps its scorecard and stats
    summary = dict(fx["summary"]) if keep else {}
    summary["decided_by"] = "organiser"
    if low in kinds:
        res = await apply_result(db, t, fx, kinds[low], None, None, summary, fx["match_id"] if keep else None)
    else:
        team = await _team(db, t, outcome)
        if team["team_id"] not in (fx["team_a_id"], fx["team_b_id"]):
            raise TournamentError(f"**{team['name']}** isn't playing in match #{fx['number']}.")
        if keep and fx["result_type"] in ("draw", "tie", "no_result") and fx["stage"] in logic.KNOCKOUT_STAGES:
            # a drawn knockout match: keep the result, just name who goes through
            text = f"{fx['result_text'].split(' — ')[0]} — {team['name']} go through (organiser's decision)"
            stmts = [store.fixture_update_stmt(fx["fixture_id"], winner_team_id=team["team_id"], result_text=text,
                                               summary=summary)]
            stmts += await _advance_stmts(db, t, fx, team["team_id"])
            await db.batch(stmts)
            effects = [("result", f"📋 **{t['name']}** · `#{fx['number']}` {logic.stage_label(fx['stage'])}\n{text}", fx["match_id"])]
            effects += await _maybe_advance(db, await store.get(db, t["tournament_id"]))
            return Result(f"`#{fx['number']}`: {text}", effects + [("unbind", fx["fixture_id"])])
        res = await apply_result(db, t, fx, "win", team["team_id"], None, summary, fx["match_id"] if keep else None)
    res.effects.append(("unbind", fx["fixture_id"]))
    return res


@action("fixture.walkover", statuses=("ongoing",))
async def fixture_walkover(db, t, actor, params):
    fx = await _fixture(db, t, params)
    if fx["status"] in logic.DONE:
        raise TournamentError(f"Match #{fx['number']} already has a result. Reset it first.")
    if not fx["team_a_id"] or not fx["team_b_id"]:
        raise TournamentError(f"Match #{fx['number']} doesn't have both teams yet.")
    team = await _team(db, t, params.get("winner"))
    res = await apply_result(db, t, fx, "walkover", team["team_id"], None, {"decided_by": "walkover"})
    res.effects.append(("unbind", fx["fixture_id"]))
    return res


@action("fixture.reset", statuses=("ongoing",))
async def fixture_reset(db, t, actor, params):
    """Wipe a result so the match can be replayed (its scorecard stops counting for the tournament)."""
    fx = await _fixture(db, t, params)
    if fx["status"] == "scheduled":
        raise TournamentError(f"Match #{fx['number']} has no result to reset.")
    stmts = [store.fixture_update_stmt(fx["fixture_id"], status="scheduled", winner_team_id=None, result_type=None,
                                       result_text=None, summary={}, match_id=None, channel_id=None)]
    key = f"W:{fx['fixture_id']}"
    for nxt in await store.list_fixtures(db, t["tournament_id"]):
        for side, src in (("team_a_id", "source_a"), ("team_b_id", "source_b")):
            if nxt[src] == key and nxt[side]:
                if nxt["status"] != "scheduled":
                    raise TournamentError(f"Match #{nxt['number']} depends on this result and has been played. "
                                          f"Reset #{nxt['number']} first.")
                stmts.append(store.fixture_update_stmt(nxt["fixture_id"], **{side: None}))
    await db.batch(stmts)
    return Result(f"↩️ Match `#{fx['number']}` was reset and can be played again.", [("unbind", fx["fixture_id"])])
