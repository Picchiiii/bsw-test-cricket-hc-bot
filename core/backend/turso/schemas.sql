
-- Creating table for the ongoing matches, storing the channel_id, team scores, match state, match settings, and the timestamp when the match started.
-- Used to resume matches after a restart (match_state holds the full serialised MatchInstance).
CREATE TABLE IF NOT EXISTS ongoing_matches (
    channel_id INTEGER PRIMARY KEY,
    team_one_score JSONB,
    team_two_score JSONB,
    match_state JSONB,
    match_settings JSONB,
    match_data JSONB,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Every match (live and finished). Read by the website.
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    guild_id TEXT,
    guild_name TEXT,
    channel_id TEXT,
    channel_name TEXT,
    host_id TEXT,
    host_name TEXT,
    team_a TEXT,
    team_b TEXT,
    status TEXT DEFAULT 'live',
    result_text TEXT,
    winner TEXT,
    summary TEXT,
    innings_no INTEGER DEFAULT 1,
    day INTEGER DEFAULT 1,
    overs_per_day INTEGER,
    days INTEGER,
    data TEXT,
    started_at INTEGER,
    updated_at INTEGER,
    ended_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status, updated_at);

-- Player profiles. The first block of columns mirrors the HandCricket bot's profile schema.
CREATE TABLE IF NOT EXISTS profiles (
    userid TEXT PRIMARY KEY,
    name TEXT,
    description TEXT DEFAULT '',
    matches_played INTEGER DEFAULT 0,
    matches_won INTEGER DEFAULT 0,
    matches_lost INTEGER DEFAULT 0,
    runs INTEGER DEFAULT 0,
    balls INTEGER DEFAULT 0,
    wickets INTEGER DEFAULT 0,
    wickets_lost INTEGER DEFAULT 0,
    highest_score INTEGER DEFAULT 0,
    hattricks INTEGER DEFAULT 0,
    ducks INTEGER DEFAULT 0,
    batting_average REAL DEFAULT 0,
    match_log TEXT DEFAULT '[]',
    status TEXT DEFAULT 'ACTIVE',
    created_at INTEGER,
    -- test-format extensions
    matches_drawn INTEGER DEFAULT 0,
    matches_tied INTEGER DEFAULT 0,
    innings_batted INTEGER DEFAULT 0,
    not_outs INTEGER DEFAULT 0,
    fours INTEGER DEFAULT 0,
    sixes INTEGER DEFAULT 0,
    fifties INTEGER DEFAULT 0,
    hundreds INTEGER DEFAULT 0,
    balls_bowled INTEGER DEFAULT 0,
    runs_conceded INTEGER DEFAULT 0,
    no_balls INTEGER DEFAULT 0,
    maidens INTEGER DEFAULT 0,
    five_wickets INTEGER DEFAULT 0,
    best_bowling_wickets INTEGER DEFAULT 0,
    best_bowling_runs INTEGER DEFAULT 0,
    potm INTEGER DEFAULT 0,
    -- economy
    coins INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    daily_last INTEGER DEFAULT 0,
    daily_streak INTEGER DEFAULT 0,
    weekly_last INTEGER DEFAULT 0,
    title TEXT DEFAULT '',
    color TEXT DEFAULT '',
    badges TEXT DEFAULT '[]',
    inventory TEXT DEFAULT '[]',
    updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_profiles_runs ON profiles(runs);
CREATE INDEX IF NOT EXISTS idx_profiles_coins ON profiles(coins);

-- One row per player per finished match (powers player pages and match logs)
CREATE TABLE IF NOT EXISTS player_match_stats (
    match_id TEXT,
    userid TEXT,
    name TEXT,
    team TEXT,
    team_name TEXT,
    result TEXT,
    runs INTEGER DEFAULT 0,
    balls INTEGER DEFAULT 0,
    fours INTEGER DEFAULT 0,
    sixes INTEGER DEFAULT 0,
    outs INTEGER DEFAULT 0,
    innings_batted INTEGER DEFAULT 0,
    highest INTEGER DEFAULT 0,
    wickets INTEGER DEFAULT 0,
    balls_bowled INTEGER DEFAULT 0,
    runs_conceded INTEGER DEFAULT 0,
    no_balls INTEGER DEFAULT 0,
    hattricks INTEGER DEFAULT 0,
    ducks INTEGER DEFAULT 0,
    potm INTEGER DEFAULT 0,
    coins INTEGER DEFAULT 0,
    created_at INTEGER,
    PRIMARY KEY (match_id, userid)
);
CREATE INDEX IF NOT EXISTS idx_pms_user ON player_match_stats(userid, created_at);

-- Coin ledger (audit trail for every balance change)
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    userid TEXT,
    amount INTEGER,
    reason TEXT,
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(userid, created_at);

-- ─────────────────────────────────────────────────────────────── access control
-- Servers the bot owner has allowed to use the bot (whitelist). expires_at = 0 means "never expires".
CREATE TABLE IF NOT EXISTS guild_access (
    guild_id TEXT PRIMARY KEY,
    guild_name TEXT DEFAULT '',
    status TEXT DEFAULT 'allowed',
    note TEXT DEFAULT '',
    added_by TEXT,
    added_at INTEGER,
    expires_at INTEGER DEFAULT 0,
    updated_at INTEGER
);

-- Owner-editable runtime settings (economy amounts and switches). Overrides config.toml.
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER
);

-- Roles and channels of servers that run tournaments (lets the website show pickers).
CREATE TABLE IF NOT EXISTS guild_meta (
    guild_id TEXT PRIMARY KEY,
    name TEXT,
    icon TEXT,
    roles TEXT DEFAULT '[]',
    channels TEXT DEFAULT '[]',
    member_count INTEGER DEFAULT 0,
    updated_at INTEGER
);

-- ─────────────────────────────────────────────────────────────── tournaments
CREATE TABLE IF NOT EXISTS tournaments (
    tournament_id TEXT PRIMARY KEY,
    guild_id TEXT,
    guild_name TEXT,
    name TEXT,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'setup',
    format TEXT DEFAULT 'league',
    settings TEXT DEFAULT '{}',
    cache TEXT DEFAULT '{}',
    host_id TEXT,
    host_name TEXT,
    rosters_locked INTEGER DEFAULT 0,
    champion_team_id TEXT,
    runner_up_team_id TEXT,
    created_at INTEGER,
    updated_at INTEGER,
    started_at INTEGER,
    ended_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tournaments_guild ON tournaments(guild_id, status);
-- one running tournament per server
CREATE UNIQUE INDEX IF NOT EXISTS idx_tournaments_one_active ON tournaments(guild_id)
    WHERE status IN ('setup', 'registration', 'ongoing');

CREATE TABLE IF NOT EXISTS tournament_staff (
    tournament_id TEXT,
    user_id TEXT,
    name TEXT,
    source TEXT DEFAULT 'manual',
    added_at INTEGER,
    PRIMARY KEY (tournament_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tstaff_user ON tournament_staff(user_id);

CREATE TABLE IF NOT EXISTS tournament_teams (
    team_id TEXT PRIMARY KEY,
    tournament_id TEXT,
    name TEXT,
    tag TEXT DEFAULT '',
    captain_id TEXT,
    vice_captain_id TEXT,
    group_name TEXT DEFAULT '',
    seed INTEGER DEFAULT 0,
    role_id TEXT DEFAULT '',
    role_auto INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tteams_t ON tournament_teams(tournament_id);

CREATE TABLE IF NOT EXISTS tournament_players (
    tournament_id TEXT,
    user_id TEXT,
    name TEXT,
    team_id TEXT,
    status TEXT DEFAULT 'active',
    joined_at INTEGER,
    PRIMARY KEY (tournament_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tplayers_user ON tournament_players(user_id);
CREATE INDEX IF NOT EXISTS idx_tplayers_team ON tournament_players(team_id);

CREATE TABLE IF NOT EXISTS tournament_invites (
    tournament_id TEXT,
    team_id TEXT,
    user_id TEXT,
    invited_by TEXT,
    created_at INTEGER,
    PRIMARY KEY (tournament_id, team_id, user_id)
);

CREATE TABLE IF NOT EXISTS tournament_fixtures (
    fixture_id TEXT PRIMARY KEY,
    tournament_id TEXT,
    number INTEGER,
    stage TEXT DEFAULT 'group',
    round INTEGER DEFAULT 1,
    group_name TEXT DEFAULT '',
    slot INTEGER DEFAULT 0,
    team_a_id TEXT,
    team_b_id TEXT,
    source_a TEXT DEFAULT '',
    source_b TEXT DEFAULT '',
    status TEXT DEFAULT 'scheduled',
    match_id TEXT,
    channel_id TEXT,
    winner_team_id TEXT,
    result_type TEXT,
    result_text TEXT,
    summary TEXT DEFAULT '{}',
    scheduled_at INTEGER DEFAULT 0,
    reminded INTEGER DEFAULT 0,
    created_at INTEGER,
    updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tfix_t ON tournament_fixtures(tournament_id, number);
CREATE INDEX IF NOT EXISTS idx_tfix_match ON tournament_fixtures(match_id);

CREATE TABLE IF NOT EXISTS tournament_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id TEXT,
    actor_id TEXT,
    actor_name TEXT,
    action TEXT,
    detail TEXT,
    source TEXT DEFAULT 'bot',
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_taudit_t ON tournament_audit(tournament_id, id);

-- ─────────────────────────────────────────────────────────────── website <-> bot
-- Actions requested on the website. The bot picks them up, checks permission again and runs them.
CREATE TABLE IF NOT EXISTS web_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT,
    guild_id TEXT,
    tournament_id TEXT,
    actor_id TEXT,
    actor_name TEXT,
    payload TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    result TEXT DEFAULT '',
    created_at INTEGER,
    done_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_wtasks_status ON web_tasks(status, id);

-- Website login sessions (Discord OAuth). Only a hash of the session cookie is stored.
CREATE TABLE IF NOT EXISTS web_sessions (
    sid_hash TEXT PRIMARY KEY,
    user_id TEXT,
    username TEXT,
    avatar TEXT,
    guilds TEXT DEFAULT '[]',
    created_at INTEGER,
    expires_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_wsess_user ON web_sessions(user_id);
