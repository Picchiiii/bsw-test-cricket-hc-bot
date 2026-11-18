# Match sheet — `match_<id>.json`

When a match finishes, the bot posts the match sheet as a file right after the result card.
`+matchsheet` (in the match channel) or `+matchsheet <match id>` (anywhere, for any match the bot has
saved) downloads it again. During a match the same command gives a live snapshot (`"status": "live"`).

The sheet contains only **public** information: the same data the result card, the scorecards and the
website show. There are no Discord server or channel IDs, no DMs and no secrets. Player IDs are Discord
user IDs (as on the website's player pages). CPU players have IDs 1–99.

Code: `core/backend/match_sheet.py` (`build_match_sheet(mi)` for a match in memory,
`sheet_from_public(data)` for a match loaded from the `matches` table). Switch the automatic file off with
`match_sheet_file = false` in `config.toml`.

## Top level

| Key | Type | Meaning |
|---|---|---|
| `sheet_version` | int | Format version (currently `1`). Fields are only ever added |
| `generated_by` / `generated_at` | str / unix time | Bot name and when the file was made |
| `match_id` | str | The match ID used by `+scorecard <id>`, `+matchsheet <id>` and the website |
| `url` | str \| null | Website page of the match (when `website_url` is set) |
| `status` | `completed` \| `abandoned` \| `live` | |
| `title` | str | "Team A v Team B" |
| `tournament` | object \| null | `{id, name, number, stage, group}` for tournament matches |
| `host` | `{id, name}` | Who created the lobby |
| `rules` | object | `overs_per_day`, `days`, `innings_overs`, `follow_on_pct`, `last_man_bats`, `rep_run_cap`, `rep_can_bowl`, `rep_retire_counts_wicket` |
| `toss` | str | "Lions won the toss and chose to bat" |
| `days_played` | int | Day the match ended on |
| `started_at` / `ended_at` | unix time | |
| `teams` | `{A, B}` | See below |
| `result` | object | `type` (`win`/`draw`/`tie`/`abandoned`), `winner` (`A`/`B`), `margin`, `text`, `potm` (player id), `potm_name` |
| `innings` | list | One card per innings, in order (see below) |
| `substitutions` | list | Every substitution, lobby and mid-match (see below) |
| `players` | list | Match totals for every player (see below) |
| `cpu_match` | bool | A CPU player took part (such matches don't count for stats/coins by default) |
| `rewards` | `{player id: coins}` | Coins paid for the match |
| `commentary` | list | The last 40 balls of commentary, oldest first: `{o: "12.3", i: innings, t: text, b: ball no}` |

## `teams.A` / `teams.B`

```json
{
  "name": "Lions",
  "players": [
    {"id": "1234…", "name": "Asha", "captain": true, "rep": false, "cpu": false, "host": true, "sub_for": null},
    {"id": "5678…", "name": "Rex",  "captain": false, "rep": true, "cpu": false, "host": false, "sub_for": "Sam"}
  ],
  "subbed_out": [{"id": "9012…", "name": "Sam"}],
  "bench": []
}
```

`players` is the XI at the end of the match. `sub_for` names the player a substitute replaced.
`subbed_out` lists players who took part and were then substituted out; their figures stay on the cards.

## `innings[]`

The same card the website and `+scorecard` use:

| Key | Meaning |
|---|---|
| `innings`, `team`, `team_name`, `bowling_team`, `bowling_team_name` | Which innings, who batted and bowled |
| `runs`, `wickets`, `balls`, `overs`, `run_rate`, `extras` (no-balls) | Totals |
| `declared`, `all_out`, `follow_on` | How it ended |
| `batting[]` | `id, name, runs, balls, fours, sixes, dots, sr, is_out, dismissal, status`, plus `rep, cpu, sub_for, subbed_out, sub_by, retired` |
| `bowling[]` | `id, name, balls, overs, maidens, runs, wickets, no_balls, econ, hattricks`, plus the same flags |
| `yet_to_bat` | Names (reps marked "(R)") |
| `fow[]` | `{wicket, runs, overs, player}` |
| `retired_not_out` | Reps retired not out at the cap in this innings |
| `rep_run_cap` | The cap that applied |
| `substitutions` | Substitutions made during this innings |
| `timeline` | The last 60 ball tokens (`0`–`6`, `W`, `NB`, `||` = end of over) |

`dismissal` values: `clash` (same number — bowler's wicket), `four_zeros` (5th dot in an over),
`afk_timeout`, `rep_retired` (rep reached the cap — counts as a wicket, not the bowler's).
`retired` values: `rep_cap` (retired not out at the cap), `substituted` (left the crease for a substitute).

Every card adds up: batting runs + extras = total = bowling runs; balls faced = balls bowled;
dismissals = wickets = fall-of-wicket entries.

## `substitutions[]`

```json
{"side": "A", "out_id": "9012…", "out_name": "Sam", "in_id": "5678…", "in_name": "Rex", "rep": true,
 "innings": 2, "over": "14.3", "day": 2, "phase": "match", "by": "Asha", "bowler_now": "Ben"}
```

`phase` is `lobby` (before the start) or `match`. `bowler_now` appears when the outgoing player was bowling
and says who finished the over.

## `players[]`

One entry per player (current XIs and anyone substituted out), sorted by team then runs:

```json
{
  "id": "5678…", "name": "Rex", "team": "A", "team_name": "Lions",
  "captain": false, "rep": true, "cpu": false, "sub_for": null, "subbed_out": false,
  "batting": {"innings": 2, "runs": 30, "balls": 14, "fours": 2, "sixes": 2, "outs": 1, "highest": 30,
              "scores": [{"innings": 1, "runs": 30, "balls": 14, "not_out": false, "status": "retired out (rep limit)"}]},
  "bowling": {"balls": 0, "overs": "0.0", "runs": 0, "wickets": 0, "maidens": 0, "no_balls": 0}
}
```
