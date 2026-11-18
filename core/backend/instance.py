from discord.ext import commands
import discord
import asyncio
import logging
import time
import uuid
from collections import deque

from core.config import config
from core.backend.cpu import CpuPlayer, is_cpu, is_cpu_id

logger = logging.getLogger(__name__)

GAME_CFG = config.game


def fresh_batter_stats() -> dict:
    return {"runs": 0, "balls": 0, "is_out": False, "last_action": 0, "over_timeline": deque(maxlen=12)}


def fresh_bowler_stats() -> dict:
    return {"runs_given": 0, "balls_given": 0, "wickets": 0, "last_action": 0, "hattrick": False,
            "duck": False, "over_timeline": deque(maxlen=12)}


def fresh_team_scores() -> dict:
    return {
        "inning_one": {"runs": 0, "balls": 0, "wickets": 0, "follow_on": False, "declared": False, "FOW": [], "batted": False},
        "inning_two": {"runs": 0, "balls": 0, "wickets": 0, "follow_on": False, "declared": False, "FOW": [], "batted": False},
    }


class MatchInstance:
    """All state for one match. Lives in bot.active_matches[channel_id] (shape unchanged)."""

    def __init__(self, bot: commands.Bot, ctx: commands.Context = None, *, channel=None, host=None):
        self.bot = bot
        self.channel = ctx.channel if ctx else channel
        self.guild = getattr(self.channel, "guild", None)
        self.host = ctx.author if ctx else host
        self.created_at = time.time()
        self.match_id = uuid.uuid4().hex[:12]
        self.players: list = []
        self.teamA: list = []
        self.teamB: list = []
        self.reps: list = []           # players who joined as representatives (shown with (R))
        # squad players on the bench (+join sub) who can be brought in with +sub; never in the playing XI
        self.bench: dict = {"A": [], "B": []}
        # every substitution made: {"side", "out_id", "out_name", "in_id", "in_name", "innings", "over", "day", "phase"}
        self.substitutions: list = []
        # players who were substituted out after the match started (their figures stay on the scorecard)
        self.subbed_out: list = []     # [{"id", "name", "side", "member"(runtime only)}]
        # CPU players in this match: {str(cpu_id): name}
        self.cpu_names: dict = {}
        self.score = 0
        self.overs = 0
        self.wickets = 0
        self.crr_day = 1
        self.innings = 1
        self.innings_declared = False
        self.result = None
        self.target = None

        self.teamA_captain: discord.User = None
        self.teamB_captain: discord.User = None
        self.toss_winner: discord.User = None
        self.toss_decision = None      # "bat" / "bowl"
        self.curr_batsman: discord.User = None
        self.nxt_batsman: discord.User = None
        self.curr_bowler: discord.User = None
        self.nxt_bowler: discord.User = None
        self.batting_team = None       # kept for backwards compatibility (team name of batting side)
        self.bowling_team = None
        self.batting_turn = None       # "A" / "B"
        self.bowling_turn = None
        self.teamA_scores = fresh_team_scores()
        self.teamB_scores = fresh_team_scores()
        self.current_batter_stats = fresh_batter_stats()
        self.current_bowler_stats = fresh_bowler_stats()
        self.team_settings = {'Team A name': 'Team A', 'Team B name': 'Team B'}
        self.match_settings = {
            'overs': 0,                 # overs per day (10-90)
            'days': 0,                  # days in the match
            'team_batting_first': "",
            'overs_per_day': 0,         # 0 = same as 'overs'
            'innings_overs': None,      # None = same as 'overs' (spec §5.4); 0 = unlimited
            'ball_timeout': GAME_CFG["ball_timeout"],
            'selection_timeout': GAME_CFG["selection_timeout"],
            'decision_timeout': GAME_CFG["decision_timeout"],
            'afk_max_strikes': GAME_CFG["afk_max_strikes"],
            'min_declare_overs': GAME_CFG["min_declare_overs"],
            'follow_on_pct': GAME_CFG["follow_on_pct"],
            'max_no_balls_per_over': GAME_CFG["max_no_balls_per_over"],
            'last_man_bats': GAME_CFG["last_man_bats"],
            'rep_run_cap': GAME_CFG.get("rep_run_cap", 30),
            'rep_can_bowl': bool(GAME_CFG.get("rep_can_bowl", False)),
            'rep_retire_counts_wicket': bool(GAME_CFG.get("rep_retire_counts_wicket", True)),
            'max_reps_per_team': GAME_CFG.get("max_reps_per_team", 0),
            'max_subs_per_team': GAME_CFG.get("max_subs_per_team", 0),
            'squad_check_seconds': GAME_CFG.get("squad_check_seconds", 60),
        }
        self.lobby_lock = False
        self.game_started = False

        # --- innings-level live state ---
        self.fow = []                  # ["66/2 at 13.2|PlayerName", ...] for the current innings
        self.last_wicket: discord.User = None
        self.balls_this_over = 0
        self.zeros_by_batsman = 0
        self.last_over_bowler: discord.User = None
        self.timeline_logdisplay = [deque(maxlen=12) for _ in range(11)]
        self.afk_players = []          # bowlers removed for AFK this innings
        self.afk_warned_players = []
        self.declared = False
        self.innings_history = {"innings_1": {"team_name": None, "score": None},
                                "innings_2": {"team_name": None, "score": None},
                                "innings_3": {"team_name": None, "score": None},
                                "innings_4": {"team_name": None, "score": None}}
        self.ten_over_history = deque(maxlen=10)   # "runs/wickets" per completed over
        self.overs_in_the_day = 0
        self.match_abandoned = False
        self.lock = asyncio.Lock()

        # --- innings lifecycle (spec v2 §3.1) ---
        self.follow_on_available = False
        self.follow_on_enforced = False
        self.min_declare_overs = self.match_settings['min_declare_overs']
        self.no_balls_this_over = 0
        self.afk_strikes = {}          # {player_id: consecutive misses}
        self.stumps_called = False
        self.extras = 0                # no-ball runs this innings
        self.retired_not_out = 0       # reps retired at the run cap without it counting as a wicket (this innings)

        # --- added for completion / continuation ---
        self.phase = "lobby"           # lobby | innings | break | finished
        self.paused = False
        self.pause_reason = ""
        self.innings_scorecards = {}   # {innings_no: snapshot dict}
        self.innings_batting = {}      # {innings_no: "A"/"B"}
        self.batting_order = []        # ids in order they came to the crease (current innings)
        self.bowling_order = []        # ids in order they first bowled (current innings)
        self.commentary = deque(maxlen=60)
        self.over_runs = 0             # runs conceded in the current over (maidens / over summary)
        self.over_wickets = 0
        self.potm = None               # player of the match id
        self.rewards = {}              # {player_id: coins} paid at the end
        self.started_at = None
        self.ended_at = None
        self.last_activity = time.time()
        # tournament link (None = friendly). Set by TournamentManager.mark_lobby: tournament id/name, fixture,
        # the two team ids and their rosters. Tournament lobbies only admit players from those rosters.
        self.tournament = None

        # runtime only (never serialised)
        self.game = None
        self.task: asyncio.Task = None
        self.interrupt = asyncio.Event()
        self.resume_event = asyncio.Event()
        self.scorecard_message = None
        self.pending_views = {}        # {"batsman": PlayerView, "bowler": PlayerView}
        self.awaiting_ball = False     # True while both players are being asked for a ball (safe moment to sub)
        self.squad_check_pending = False  # set by resume: show the squads before the next ball
        self.squad_check_view = None   # the "squads for today" prompt shown when play resumes (subs allowed)
        self.restored = False

    # ------------------------------------------------------------------ helpers
    @property
    def overs_per_day(self) -> int:
        return self.match_settings.get('overs_per_day') or self.match_settings.get('overs') or 0

    @property
    def innings_overs_cap(self) -> int:
        cap = self.match_settings.get('innings_overs')
        if cap is None:
            return self.match_settings.get('overs') or 0
        return cap

    def team(self, side: str) -> list:
        return self.teamA if side == "A" else self.teamB

    def team_name(self, side: str) -> str:
        return self.team_settings['Team A name'] if side == "A" else self.team_settings['Team B name']

    def captain(self, side: str):
        return self.teamA_captain if side == "A" else self.teamB_captain

    def side_of(self, player) -> str | None:
        if player in self.teamA:
            return "A"
        if player in self.teamB:
            return "B"
        return None

    def member(self, player_id: int):
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def is_rep(self, player) -> bool:
        return player is not None and player in self.reps

    def reps_in(self, side: str) -> list:
        return [p for p in self.team(side) if p in self.reps]

    def bench_side_of(self, player) -> str | None:
        for side in ("A", "B"):
            if player in self.bench.get(side, []):
                return side
        return None

    def side_of_any(self, player) -> str | None:
        """Side of a current player, or of someone who was substituted out of this match."""
        side = self.side_of(player)
        if side is not None:
            return side
        pid = getattr(player, "id", player)
        for s in self.subbed_out:
            if int(s["id"]) == int(pid):
                return s["side"]
        return None

    def featured_players(self) -> list:
        """Everyone who took part: the current XIs plus players substituted out after the start."""
        out = list(self.players)
        for s in self.subbed_out:
            m = s.get("member")
            if m is not None and m not in out:
                out.append(m)
        return out

    def subs_used(self, side: str) -> int:
        return sum(1 for s in self.substitutions if s["side"] == side)

    @staticmethod
    def other(side: str) -> str:
        return "B" if side == "A" else "A"

    def team_totals(self, side: str) -> int:
        s = self.teamA_scores if side == "A" else self.teamB_scores
        return s["inning_one"]["runs"] + s["inning_two"]["runs"]

    def touch(self):
        self.last_activity = time.time()

    # ------------------------------------------------------------- persistence
    def to_state(self, teams: dict | None = None) -> dict:
        """JSON-serialisable snapshot of everything needed to resume this match."""
        def pid(p):
            return p.id if p is not None else None

        def ser_stats(d):
            out = dict(d)
            if "over_timeline" in out:
                out["over_timeline"] = list(out["over_timeline"])
            return out

        ser_teams = None
        if teams:
            ser_teams = {}
            for side, rows in teams.items():
                ser_teams[side] = {}
                for k, row in rows.items():
                    r = dict(row)
                    if "timeline" in r:
                        r["timeline"] = list(r["timeline"])
                    ser_teams[side][str(k)] = r

        return {
            "version": 2,
            "match_id": self.match_id,
            "channel_id": self.channel.id,
            "guild_id": self.guild.id if self.guild else None,
            "host": pid(self.host),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "players": [p.id for p in self.players],
            "teamA": [p.id for p in self.teamA],
            "teamB": [p.id for p in self.teamB],
            "reps": [p.id for p in self.reps],
            "bench": {side: [p.id for p in members] for side, members in self.bench.items()},
            "substitutions": self.substitutions,
            "subbed_out": [{k: v for k, v in s.items() if k != "member"} for s in self.subbed_out],
            "cpu_names": self.cpu_names,
            "retired_not_out": self.retired_not_out,
            "score": self.score, "overs": self.overs, "wickets": self.wickets,
            "crr_day": self.crr_day, "innings": self.innings,
            "innings_declared": self.innings_declared,
            "result": self.result, "target": self.target,
            "teamA_captain": pid(self.teamA_captain), "teamB_captain": pid(self.teamB_captain),
            "toss_winner": pid(self.toss_winner), "toss_decision": self.toss_decision,
            "curr_batsman": pid(self.curr_batsman), "nxt_batsman": pid(self.nxt_batsman),
            "curr_bowler": pid(self.curr_bowler), "nxt_bowler": pid(self.nxt_bowler),
            "batting_turn": self.batting_turn, "bowling_turn": self.bowling_turn,
            "teamA_scores": self.teamA_scores, "teamB_scores": self.teamB_scores,
            "current_batter_stats": ser_stats(self.current_batter_stats),
            "current_bowler_stats": ser_stats(self.current_bowler_stats),
            "team_settings": self.team_settings, "match_settings": self.match_settings,
            "lobby_lock": self.lobby_lock, "game_started": self.game_started,
            "fow": self.fow, "last_wicket": pid(self.last_wicket),
            "balls_this_over": self.balls_this_over, "zeros_by_batsman": self.zeros_by_batsman,
            "last_over_bowler": pid(self.last_over_bowler),
            "timeline_logdisplay": [list(d) for d in self.timeline_logdisplay],
            "afk_players": [p.id for p in self.afk_players],
            "innings_history": self.innings_history,
            "ten_over_history": list(self.ten_over_history),
            "overs_in_the_day": self.overs_in_the_day,
            "follow_on_available": self.follow_on_available, "follow_on_enforced": self.follow_on_enforced,
            "no_balls_this_over": self.no_balls_this_over,
            "afk_strikes": {str(k): v for k, v in self.afk_strikes.items()},
            "stumps_called": self.stumps_called, "extras": self.extras,
            "phase": self.phase, "paused": self.paused, "pause_reason": self.pause_reason,
            "innings_scorecards": {str(k): v for k, v in self.innings_scorecards.items()},
            "innings_batting": {str(k): v for k, v in self.innings_batting.items()},
            "batting_order": self.batting_order, "bowling_order": self.bowling_order,
            "commentary": list(self.commentary),
            "over_runs": self.over_runs, "over_wickets": self.over_wickets,
            "tournament": self.tournament,
            "teams": ser_teams,
        }

    @classmethod
    async def from_state(cls, bot, channel, state: dict):
        """Rebuild a MatchInstance from to_state() output. Members are re-fetched from the guild."""
        guild = channel.guild
        cache = {}

        cpu_names = state.get("cpu_names") or {}

        async def resolve(user_id):
            if user_id is None:
                return None
            user_id = int(user_id)
            if user_id in cache:
                return cache[user_id]
            if is_cpu_id(user_id):
                cache[user_id] = CpuPlayer(user_id, cpu_names.get(str(user_id)))
                return cache[user_id]
            m = guild.get_member(user_id) if guild else None
            if m is None and guild is not None:
                try:
                    m = await guild.fetch_member(user_id)
                except Exception:
                    m = None
            if m is None:
                try:
                    m = bot.get_user(user_id) or await bot.fetch_user(user_id)
                except Exception:
                    m = None
            cache[user_id] = m
            return m

        host = await resolve(state["host"])
        mi = cls(bot, None, channel=channel, host=host)
        mi.match_id = state["match_id"]
        mi.created_at = state.get("created_at", time.time())
        mi.started_at = state.get("started_at")
        mi.players = [m for m in [await resolve(i) for i in state["players"]] if m is not None]
        mi.teamA = [m for m in [await resolve(i) for i in state["teamA"]] if m is not None]
        mi.teamB = [m for m in [await resolve(i) for i in state["teamB"]] if m is not None]
        mi.reps = [m for m in [await resolve(i) for i in state.get("reps", [])] if m is not None]
        mi.cpu_names = dict(cpu_names)
        mi.bench = {side: [m for m in [await resolve(i) for i in (state.get("bench") or {}).get(side, [])] if m is not None]
                    for side in ("A", "B")}
        mi.substitutions = list(state.get("substitutions") or [])
        mi.subbed_out = []
        for s in state.get("subbed_out") or []:
            entry = dict(s)
            entry["member"] = await resolve(s["id"])
            mi.subbed_out.append(entry)
        for key in ("score", "overs", "wickets", "crr_day", "innings", "innings_declared", "result", "target",
                    "toss_decision", "batting_turn", "bowling_turn", "teamA_scores", "teamB_scores",
                    "team_settings", "lobby_lock", "game_started", "fow", "balls_this_over",
                    "zeros_by_batsman", "innings_history", "overs_in_the_day", "follow_on_available",
                    "follow_on_enforced", "no_balls_this_over", "stumps_called", "extras", "phase",
                    "paused", "pause_reason", "batting_order", "bowling_order", "over_runs", "over_wickets",
                    "retired_not_out"):
            if key in state:
                setattr(mi, key, state[key])
        mi.match_settings.update(state.get("match_settings", {}))
        for key in ("teamA_captain", "teamB_captain", "toss_winner", "curr_batsman", "nxt_batsman",
                    "curr_bowler", "nxt_bowler", "last_wicket", "last_over_bowler"):
            setattr(mi, key, await resolve(state.get(key)))
        cb = state.get("current_batter_stats") or {}
        mi.current_batter_stats = fresh_batter_stats()
        mi.current_batter_stats.update({k: v for k, v in cb.items() if k != "over_timeline"})
        mi.current_batter_stats["over_timeline"].extend(cb.get("over_timeline", []))
        cw = state.get("current_bowler_stats") or {}
        mi.current_bowler_stats = fresh_bowler_stats()
        mi.current_bowler_stats.update({k: v for k, v in cw.items() if k != "over_timeline"})
        mi.current_bowler_stats["over_timeline"].extend(cw.get("over_timeline", []))
        mi.timeline_logdisplay = [deque(line, maxlen=12) for line in state.get("timeline_logdisplay", [])] \
            or [deque(maxlen=12) for _ in range(11)]
        while len(mi.timeline_logdisplay) < 11:
            mi.timeline_logdisplay.append(deque(maxlen=12))
        mi.afk_players = [m for m in [await resolve(i) for i in state.get("afk_players", [])] if m is not None]
        mi.ten_over_history = deque(state.get("ten_over_history", []), maxlen=10)
        mi.afk_strikes = {int(k): v for k, v in state.get("afk_strikes", {}).items()}
        mi.innings_scorecards = {int(k): v for k, v in state.get("innings_scorecards", {}).items()}
        mi.innings_batting = {int(k): v for k, v in state.get("innings_batting", {}).items()}
        mi.commentary = deque(state.get("commentary", []), maxlen=60)
        mi.min_declare_overs = mi.match_settings.get('min_declare_overs', GAME_CFG["min_declare_overs"])
        mi.tournament = state.get("tournament") or None
        mi.restored = True
        mi._restored_teams = state.get("teams")
        return mi


def join_segregate_player(match_instance: MatchInstance, player: discord.User):
    if len(match_instance.teamA) <= len(match_instance.teamB):
        match_instance.teamA.append(player)
        if match_instance.teamA_captain is None:
            match_instance.teamA_captain = player
    else:
        match_instance.teamB.append(player)
        if match_instance.teamB_captain is None:
            match_instance.teamB_captain = player


def leave_segregate_player(match_instance: MatchInstance, player: discord.User):
    if player in match_instance.teamA:
        match_instance.teamA.remove(player)
        if match_instance.teamA_captain == player:
            match_instance.teamA_captain = match_instance.teamA[0] if match_instance.teamA else None
    elif player in match_instance.teamB:
        match_instance.teamB.remove(player)
        if match_instance.teamB_captain == player:
            match_instance.teamB_captain = match_instance.teamB[0] if match_instance.teamB else None
    if player in match_instance.reps:
        match_instance.reps.remove(player)
    if is_cpu(player):
        match_instance.cpu_names.pop(str(player.id), None)


def player_busy_elsewhere(bot, player, channel_id: int):
    """Return the channel id of another active match this player is in (DM picks can't be shared)."""
    if is_cpu(player):
        return None   # a CPU can play in any number of matches
    for cid, mi in getattr(bot, "active_matches", {}).items():
        if cid != channel_id and player in mi.players and mi.phase != "finished":
            return cid
    return None
