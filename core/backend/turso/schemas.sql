
-- Creating table for the ongoing matches, storing the channel_id, team scores, match state, match settings, and the timestamp when the match started.
CREATE TABLE IF NOT EXISTS ongoing_matches (
    channel_id INTEGER PRIMARY KEY,
    team_one_score JSONB,
    team_two_score JSONB,
    match_state JSONB,
    match_settings JSONB,
    match_data JSONB,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
