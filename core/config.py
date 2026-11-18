import os
import tomllib
from dataclasses import dataclass, field

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_GAME_DEFAULTS = {
    "ball_timeout": 30,
    "selection_timeout": 30,
    "decision_timeout": 120,
    "afk_max_strikes": 3,
    "min_declare_overs": 5,
    "follow_on_pct": 50,
    "max_no_balls_per_over": 0,
    "max_players": 22,
    "min_overs": 10,
    "max_overs": 90,
    "min_days": 1,
    "max_days": 5,
    "lobby_ttl_minutes": 60,
    "last_man_bats": False,
    "use_custom_emojis": True,
    # representatives (+join rep): most runs a rep may score in one innings (0 = no cap)
    "rep_run_cap": 30,
    # false = reps never bowl
    "rep_can_bowl": False,
    # true = a rep who reaches the cap is "retired out" (counts as a wicket); false = retired not out
    "rep_retire_counts_wicket": True,
    # most reps per team in one match (0 = no limit)
    "max_reps_per_team": 0,
    # seconds the bot shows both squads when play resumes (next day / after a pause) so captains can
    # sub out anyone who isn't there today; "Start play" starts sooner. 0 = no squad check
    "squad_check_seconds": 60,
    # substitutes: allow subs once the match has started
    "subs_during_match": True,
    # most substitutions per team per match (0 = no limit)
    "max_subs_per_team": 0,
    # CPU (computer) players for friendly matches
    "cpu_enabled": True,
    # seconds a CPU "thinks" before each pick (0 = instant)
    "cpu_delay": 1.0,
    # false = matches with a CPU player record no stats and pay no coins (stops farming)
    "cpu_matches_count": False,
    # post the public JSON match sheet as a file when a match ends
    "match_sheet_file": True,
}

_ECONOMY_DEFAULTS = {
    "currency_name": "Coins",
    "currency_emoji": "🪙",
    "start_balance": 500,
    "daily": 250,
    "daily_streak_bonus": 25,
    "daily_streak_cap": 7,
    "weekly": 1500,
    "participation": 50,
    "win": 150,
    "draw": 60,
    "tie": 100,
    "per_run": 1,
    "per_wicket": 10,
    "fifty": 50,
    "hundred": 150,
    "five_wickets": 100,
    "hattrick": 200,
    "potm": 100,
    "min_balls_for_rewards": 30,
    # switches the bot owner can flip at runtime with the eco command
    "daily_enabled": True,
    "weekly_enabled": True,
    "give_enabled": True,
    "shop_enabled": True,
    "match_rewards_enabled": True,
}

_ACCESS_DEFAULTS = {
    # true = only servers the owner has allowed may use the bot
    "whitelist_enabled": True,
    # shown to servers that are not allowed ("" = mention the owner)
    "contact": "",
    # true = the bot leaves a server that is not on the whitelist as soon as it is added
    "leave_unlisted": False,
    # DM the owner when the bot is added to a server
    "notify_owner_on_join": True,
}

_TOURNAMENT_DEFAULTS = {
    # seconds between checks for actions requested on the website (0 = website actions off)
    "web_poll_seconds": 3,
    # seconds between reminder / housekeeping passes
    "housekeeping_seconds": 60,
}


@dataclass(frozen=True)
class Config:
    prefix: str
    bot_name: str = "BSW Test Cricket"
    website_url: str = ""
    support_url: str = ""
    game: dict = field(default_factory=dict)
    economy: dict = field(default_factory=dict)
    access: dict = field(default_factory=dict)
    tournament: dict = field(default_factory=dict)
    owner_ids: tuple = ()


def _load() -> Config:
    path = os.getenv("BSW_CONFIG", os.path.join(ROOT_DIR, "config.toml"))
    raw = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    game = dict(_GAME_DEFAULTS)
    game.update(raw.get("game", {}))
    economy = dict(_ECONOMY_DEFAULTS)
    economy.update(raw.get("economy", {}))

    access = dict(_ACCESS_DEFAULTS)
    access.update(raw.get("access", {}))
    tournament = dict(_TOURNAMENT_DEFAULTS)
    tournament.update(raw.get("tournament", {}))
    owners = []
    for part in str(os.getenv("OWNER_IDS") or "").replace(";", ",").split(","):
        if part.strip().isdigit():
            owners.append(int(part.strip()))
    for value in raw.get("owner_ids", []) or []:
        if str(value).strip().isdigit() and int(value) not in owners:
            owners.append(int(value))

    return Config(
        prefix=raw.get("prefix", "$"),
        bot_name=raw.get("bot_name", "BSW Test Cricket"),
        website_url=(os.getenv("WEBSITE_URL") or raw.get("website_url", "")).rstrip("/"),
        support_url=raw.get("support_url", ""),
        game=game,
        economy=economy,
        access=access,
        tournament=tournament,
        owner_ids=tuple(owners),
    )


config = _load()   # ✅ global instance
