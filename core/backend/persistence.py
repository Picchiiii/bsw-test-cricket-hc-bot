"""Match persistence: resume-after-restart state + the public snapshot read by the website.

* ongoing_matches  — full serialised MatchInstance (one row per channel), used to resume matches.
* matches          — public, website-friendly snapshot of every started match (live and finished).

Writes are coalesced per match: the game calls schedule() after every ball; a background writer sends
only the latest snapshot, at most once per `min_interval` seconds, so the game never waits on the DB
and a slow/failed write never breaks a match.
"""
import asyncio
import json
import logging
import time

import discord

from core.backend.checks import GameChecks
from core.config import config
from core.ui import theme
from core.backend.cpu import is_cpu, has_cpu

logger = logging.getLogger(__name__)


def _now() -> int:
    return int(time.time())


def build_public(mi) -> dict:
    """Website snapshot of a match (no Discord objects, ids as strings)."""
    game = mi.game

    subs_in = {s["in_id"]: s["out_name"] for s in getattr(mi, "substitutions", []) if s.get("phase") == "match"}

    def team(side):
        cap = mi.captain(side)
        return {
            "name": mi.team_name(side),
            "players": [{"id": str(p.id), "name": p.name, "captain": p == cap, "rep": p in mi.reps,
                         "cpu": is_cpu(p), "host": p == mi.host, "sub_for": subs_in.get(p.id)}
                        for p in mi.team(side)],
            # took part, then substituted out (their figures stay on the cards)
            "subbed_out": [{"id": str(x["id"]), "name": x["name"]} for x in getattr(mi, "subbed_out", [])
                           if x.get("side") == side],
            "bench": [{"id": str(p.id), "name": p.name} for p in getattr(mi, "bench", {}).get(side, [])],
        }

    innings = [mi.innings_scorecards[n] for n in sorted(mi.innings_scorecards)]
    current = None
    if game is not None and mi.phase == "innings" and mi.game_started:
        live_card = game.build_innings_card()
        live_card["live"] = True
        innings = [c for c in innings if c.get("innings") != mi.innings] + [live_card]
        bat, bowl = mi.curr_batsman, mi.curr_bowler
        bat_row = game.row(bat) if bat else None
        bowl_row = game.row(bowl) if bowl else None
        balls = mi.overs * 6 + mi.balls_this_over
        current = {
            "innings": mi.innings,
            "batting_team": mi.batting_turn,
            "score": mi.score, "wickets": mi.wickets, "overs": f"{mi.overs}.{mi.balls_this_over}",
            "crr": round(mi.score / (balls / 6), 2) if balls else 0.0,
            "target": mi.target,
            "status_line": game.lead_trail_or_target(),
            "batter": {"id": str(bat.id), "name": bat.name, "runs": bat_row["runs"], "balls": bat_row["balls"],
                       "fours": bat_row["fours"], "sixes": bat_row["sixes"],
                       "dots_this_over": mi.zeros_by_batsman} if bat and bat_row else None,
            "bowler": {"id": str(bowl.id), "name": bowl.name, "wickets": bowl_row["wickets"],
                       "runs": bowl_row["runs_given"], "overs": theme.overs_str(bowl_row["balls_given"]),
                       "no_balls": bowl_row.get("no_balls", 0)} if bowl and bowl_row else None,
            "this_over": [e for e in _current_over(game)],
            "on_deck_batter": mi.nxt_batsman.name if mi.nxt_batsman else None,
            "next_bowler": mi.nxt_bowler.name if mi.nxt_bowler else None,
            "overs_left_today": max(0, mi.overs_per_day - mi.overs_in_the_day),
        }

    toss = None
    if mi.toss_winner:
        side = mi.side_of(mi.toss_winner)
        toss = f"{mi.team_name(side)} won the toss and chose to {mi.toss_decision or '...'}"

    status = "live"
    if mi.phase == "finished":
        status = "abandoned" if (mi.result or {}).get("type") == "abandoned" else "completed"

    result = None
    if mi.result and mi.phase == "finished":
        result = {"type": mi.result.get("type"), "winner": mi.result.get("winner"),
                  "margin": mi.result.get("margin"), "text": game.result_text() if game else "",
                  "potm": str(mi.potm) if mi.potm else None}

    return {
        "match_id": mi.match_id,
        "status": status,
        "phase": mi.phase,
        "paused": mi.paused,
        "stumps": mi.stumps_called,
        "guild": getattr(mi.guild, "name", None),
        "channel": getattr(mi.channel, "name", None),
        "host": {"id": str(mi.host.id), "name": mi.host.name} if mi.host else None,
        "teams": {"A": team("A"), "B": team("B")},
        "settings": {"overs_per_day": mi.overs_per_day, "days": mi.match_settings.get("days"),
                     "innings_overs": mi.innings_overs_cap,
                     "follow_on_pct": mi.match_settings.get("follow_on_pct"),
                     "last_man_bats": bool(mi.match_settings.get("last_man_bats")),
                     "rep_run_cap": mi.match_settings.get("rep_run_cap", 0),
                     "rep_can_bowl": bool(mi.match_settings.get("rep_can_bowl")),
                     "rep_retire_counts_wicket": bool(mi.match_settings.get("rep_retire_counts_wicket", True))},
        "substitutions": [{k: (str(v) if k in ("in_id", "out_id") else v) for k, v in x.items()}
                          for x in getattr(mi, "substitutions", [])],
        "cpu_match": has_cpu(mi),
        "toss": toss,
        "day": mi.crr_day,
        "innings_no": mi.innings,
        "target": mi.target,
        "follow_on": mi.follow_on_enforced,
        "tournament": ({"id": mi.tournament["id"], "name": mi.tournament["name"], "number": mi.tournament["number"],
                        "stage": mi.tournament["stage"], "group": mi.tournament.get("group", "")}
                       if getattr(mi, "tournament", None) else None),
        "innings": innings,
        "current": current,
        "commentary": list(mi.commentary)[-40:][::-1],
        "result": result,
        "rewards": {str(k): v for k, v in (mi.rewards or {}).items()},
        "started_at": int(mi.started_at) if mi.started_at else None,
        "updated_at": _now(),
    }


def _current_over(game):
    flat = game._flat_timeline()
    out = []
    for e in reversed(flat):
        if e == "||":
            break
        out.append(e)
    return list(reversed(out))


def summary_line(mi) -> str:
    if mi.phase == "finished" and mi.game is not None:
        return mi.game.result_text()
    if mi.phase == "innings":
        return (f"{mi.team_name(mi.batting_turn)} {mi.score}/{mi.wickets} ({mi.overs}.{mi.balls_this_over}) • "
                f"Day {mi.crr_day}, Inns {mi.innings}")
    return f"Innings break • Day {mi.crr_day}"


class Store:
    def __init__(self, db, min_interval: float = 1.0):
        self.db = db
        self.min_interval = min_interval
        self._pending: dict[str, list] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._finished: set[str] = set()

    # ------------------------------------------------------------- statements
    def _statements(self, mi) -> list:
        teams = mi.game.teams if mi.game is not None else None
        state = mi.to_state(teams)
        stmts = [(
            "INSERT INTO ongoing_matches (channel_id, team_one_score, team_two_score, match_state, match_settings, match_data) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET team_one_score=excluded.team_one_score, "
            "team_two_score=excluded.team_two_score, match_state=excluded.match_state, "
            "match_settings=excluded.match_settings, match_data=excluded.match_data",
            [mi.channel.id, json.dumps(mi.teamA_scores), json.dumps(mi.teamB_scores), json.dumps(state, default=str),
             json.dumps(mi.match_settings), json.dumps({"match_id": mi.match_id, "phase": mi.phase})],
        )]
        if mi.game_started:
            stmts.append(self._match_row(mi))
        return stmts

    def _match_row(self, mi):
        public = build_public(mi)
        winner = (mi.result or {}).get("winner") if mi.phase == "finished" else None
        return (
            "INSERT INTO matches (match_id, guild_id, guild_name, channel_id, channel_name, host_id, host_name, team_a, team_b, "
            "status, result_text, winner, summary, innings_no, day, overs_per_day, days, data, started_at, updated_at, ended_at, "
            "tournament_id, fixture_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(match_id) DO UPDATE SET status=excluded.status, result_text=excluded.result_text, "
            "winner=excluded.winner, summary=excluded.summary, innings_no=excluded.innings_no, day=excluded.day, "
            "team_a=excluded.team_a, team_b=excluded.team_b, data=excluded.data, updated_at=excluded.updated_at, "
            "ended_at=excluded.ended_at, tournament_id=excluded.tournament_id, fixture_id=excluded.fixture_id",
            [mi.match_id, str(mi.guild.id) if mi.guild else None, getattr(mi.guild, "name", None),
             str(mi.channel.id), getattr(mi.channel, "name", None), str(mi.host.id), mi.host.name,
             mi.team_settings['Team A name'], mi.team_settings['Team B name'], public["status"],
             public["result"]["text"] if public["result"] else None,
             (mi.team_name(winner) if winner else None), summary_line(mi), mi.innings, mi.crr_day,
             mi.overs_per_day, mi.match_settings.get('days'), json.dumps(public, default=str),
             int(mi.started_at or mi.created_at), _now(), int(mi.ended_at) if mi.ended_at else None,
             (mi.tournament or {}).get("id") if getattr(mi, "tournament", None) else None,
             (mi.tournament or {}).get("fixture_id") if getattr(mi, "tournament", None) else None],
        )

    # ------------------------------------------------------------- writer
    def schedule(self, mi, force: bool = False):
        key = mi.match_id
        if key in self._finished:
            return None
        try:
            self._pending[key] = self._statements(mi)
        except Exception:
            logger.exception("could not serialise match %s", key)
            return None
        task = self._tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self._writer(key))
            self._tasks[key] = task
        return task

    async def _writer(self, key: str):
        while key in self._pending:
            stmts = self._pending.pop(key)
            try:
                await self.db.batch(stmts)
            except Exception as e:
                logger.warning("persisting match %s failed: %s", key, e)
            if key in self._pending:
                await asyncio.sleep(self.min_interval)

    async def flush(self, mi):
        task = self.schedule(mi, force=True)
        if task is not None:
            try:
                await asyncio.shield(task)
            except Exception:
                pass

    async def _drain(self, key: str):
        self._pending.pop(key, None)
        task = self._tasks.pop(key, None)
        if task is not None and not task.done():
            try:
                await asyncio.shield(task)
            except Exception:
                pass

    async def finish(self, mi):
        """Final write for a finished/abandoned match; removes its resume state."""
        key = mi.match_id
        self._finished.add(key)
        await self._drain(key)
        stmts = [("DELETE FROM ongoing_matches WHERE channel_id = ?", [mi.channel.id])]
        if mi.game_started:
            stmts.insert(0, self._match_row(mi))
        try:
            await self.db.batch(stmts)
        except Exception as e:
            logger.warning("finishing match %s failed: %s", key, e)

    async def delete_state(self, mi):
        key = mi.match_id
        self._finished.add(key)
        await self._drain(key)
        try:
            await self.db.execute("DELETE FROM ongoing_matches WHERE channel_id = ?", [mi.channel.id])
        except Exception as e:
            logger.warning("deleting match state %s failed: %s", key, e)

    async def load_all(self) -> list[dict]:
        rows = await self.db.fetch("SELECT channel_id, match_state FROM ongoing_matches")
        out = []
        for r in rows:
            try:
                state = json.loads(r["match_state"]) if isinstance(r["match_state"], str) else r["match_state"]
                if state and state.get("version") == 2:
                    out.append(state)
            except Exception:
                logger.warning("skipping unreadable match state for channel %s", r.get("channel_id"))
        return out

    async def delete_channel(self, channel_id: int):
        await self.db.execute("DELETE FROM ongoing_matches WHERE channel_id = ?", [channel_id])


async def restore_matches(bot) -> int:
    """Rebuild every saved match after a restart. Running matches come back paused."""
    from core.backend.instance import MatchInstance
    from core.backend.game import Game
    from core.backend.lobby import lobby_embed
    from core.backend.views.match_view import JoinMatchView
    from core.backend.views.stumps_view import StumpsView

    store: Store = bot.store
    try:
        states = await store.load_all()
    except Exception as e:
        logger.warning("could not load saved matches: %s", e)
        return 0
    restored = 0
    for state in states:
        channel_id = int(state["channel_id"])
        if channel_id in bot.active_matches:
            continue
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                channel = None
        if channel is None:
            logger.info("dropping saved match for missing channel %s", channel_id)
            await store.delete_channel(channel_id)
            continue
        try:
            mi = await MatchInstance.from_state(bot, channel, state)
        except Exception:
            logger.exception("failed to restore match in channel %s", channel_id)
            continue
        if mi.host is None or not mi.players:
            await store.delete_channel(channel_id)
            continue
        bot.active_matches[channel_id] = mi
        restored += 1
        try:
            if not mi.game_started:
                view = JoinMatchView(mi, None)
                msg = await channel.send(content="🔄 The bot restarted — your lobby has been restored.",
                                         embed=lobby_embed(mi), view=view)
                view.message = msg
                continue
            game = Game(None, mi)
            await game.initialise()
            if mi.phase == "finished":
                game.start_task(resume=True)   # finish recording the result
                continue
            if mi.stumps_called:
                view = StumpsView(mi)
                e = theme.embed("🔄 Match restored — Stumps",
                                f"The bot restarted during stumps of Day {mi.crr_day}. "
                                f"Start Day {mi.crr_day + 1} with the button or `{config.prefix}resume`.", theme.BLUE)
                msg = await channel.send(embed=e, view=view)
                view.message = msg
            else:
                mi.paused = True
                mi.pause_reason = "restart"
                e = theme.embed("🔄 Match restored",
                                f"The bot restarted, but your match was saved.\n"
                                f"**{summary_line(mi)}**\n\nHost or a captain: `{config.prefix}resume` to carry on.",
                                theme.BLUE)
                await channel.send(embed=e)
        except discord.HTTPException:
            logger.warning("could not announce restored match in %s", channel_id)
    return restored
