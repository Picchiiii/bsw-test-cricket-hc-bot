# Implementation report — what was built, fixed and changed

This document covers everything done to take the bot from "basic setup" to a deliverable product.
The game logic was **kept as designed** (DM blind picks, bowler-0 = no-ball, clash = out, 5th dot in an
over = out, captain-picked opener + on-deck batter/bowler, test format over days). Where the code was
incomplete, it was completed following the two spec documents in `core/assets/docs/`
(*Game-Logic Completion Specification v2* is the main reference; bug IDs below are from it).

---

## 1. Summary

| Area | Before | Now |
|---|---|---|
| Innings | Only innings 1 & 2; match could never finish | All 4 innings, follow-on, targets, innings victories, ties, draws |
| Days | Counters existed, never used | Overs-per-day quota, stumps, "Start next day", draw when days run out |
| Declarations | UI only, checked wrong flags | Batting captain only, not in 4th innings, after N overs; takes effect instantly |
| Follow-on | View existed, never sent, set wrong flag | Offered automatically, enforce/decline/timeout |
| AFK | 2 strikes, bowler AFK dismissed the batter | Configurable strikes, batter out (not a bowler wicket), bowler replaced mid-over |
| Multiple matches | Shared DM listener, cross-talk possible | Fully isolated per channel, one match per player, tested with 60 concurrent matches |
| Continuation | Nothing persisted | Every ball saved; restart restores lobbies, running matches, stumps |
| Stats / economy | None | HandCricket-style profiles, detailed stats, leaderboards, coins, shop |
| Website | None | Vercel site: live scoreboard, results, scorecards, ball-by-ball, leaderboard, player pages |
| Tests | None | 47 automated tests + randomised soak test |

---

## 2. Bugs fixed

### From the spec's audit (B1–B15, v2 numbering)

| ID | Problem | Fix |
|---|---|---|
| B1 | No code path past innings 2; duplicated end conditions | One shared `Game.play_innings()` loop + `run()` state machine; `One/Two/Three/Four` kept as thin wrappers |
| B2 | `teamA_scores`, `teamB_scores`, `innings_history` never written | `snapshot_innings()` writes them at the end of every innings |
| B3 | FollowOnView set `innings_declared`; never shown | Sets `follow_on_enforced`; offered by `offer_follow_on()` |
| B4 | Captain/player checks compared ids to Member objects (always false) | Object-to-object comparisons everywhere |
| B5 | kick/swap removed ids from lists of Members | Fixed; captaincy follows the team on swap/kick |
| B6 | Five-dot dismissal credited the bowler | No bowler wicket; dismissal recorded as `four_zeros` |
| B7 | Dot counter not reset for a new batter mid-over | Reset whenever the batter changes |
| B8 | Invalid numbers still reached `resolve_ball` | Out-of-range DMs are rejected with ❌ and a hint; never resolved |
| B9 | `PlayerView.on_timeout` nested inside `__init__` (dead) | Real method; auto-picks so the match never stalls |
| B10 | Two dropdowns at innings start | Kept by design (opener pick + **on-deck** pick), now labelled clearly; the blind 20 s sleep replaced by waiting for the picks |
| B11 | All-out = half of *all* players | Per batting team: `team size − 1` (configurable `last_man_bats`) |
| B12 | `instance` command crashed (missing attributes) | Shows real per-team scores |
| B13 | AFK bowler dismissed the batter | Bowler replaced, nobody dismissed |
| B14 | `mi.lock` never used | Ball resolution runs under the lock |
| B15 | Two bowler-eligibility implementations | One `get_eligible_bowlers()` |

### From the v1 audit and our own review

* `batball_view` used `config.BOT_PREFIX` (crash on every Bat/Bowl choice) → `config.prefix`.
* `change_host` compared id to Members → never worked. Fixed.
* `show` exposed any attribute (bot, lock…) → whitelist of safe fields.
* Join **button** ignored the lobby lock / started match → same rules as `join` (shared `try_join`).
* `TossView.on_timeout` edited once per button → once.
* `rep` join added the player twice (id + Member) → joins once, tagged **(R)**.
* `players` command showed a wrong "created ago" time (mixed clocks).
* Error handler had a stray `self` parameter and was disabled → fixed, enabled, posts to `ERROR_WEBHOOK_URL`.
* `turso/db.py`: `init_match` was a stub with broken SQL; arguments were sent untyped (Turso rejects them);
  results returned raw. Rewritten with typed args, decoded rows, atomic batches. `httpx` was missing from
  `requirements.txt` (and there's now a standard-library fallback).
* `send_next_batsman` could pick the aggregate keys (`'name'`, `'runs'`) as a "player".
* `complete_over` overwrote the chosen next bowler with a random one, and crashed if none was chosen.
* Wicket messages crashed when no next batter was picked yet (`nxt_batsman.mention` on None).
* Dot balls were added to the timeline twice; dot balls sent no DM feedback.
* DM timelines iterated characters ("NB" showed as "N", "B").
* FOW and "Last wicket" read characters of strings → always empty/wrong; overs at 6th ball shown as `x.6`.
* Timeline field grew without limit → would break Discord's 1024-character embed limit after ~33 balls.
* Scorecard always printed Team A's name for the batting side; `batting_team` was never set.
* Per-player rows (dropdown performance lines) were never updated — now updated every ball, per innings.
* `current_batter_stats` reset wrote to the Game instead of the MatchInstance.
* Any digit typed **anywhere** (even in the server channel) counted as a pick → DMs only, only after the prompt.
* A player could be in two matches at once (DM picks would be shared) → blocked.
* Bat/Bowl view never timed out; double clicks could fire twice → timeouts + single-use guards.
* `start` didn't check overs/days/toss were set → clear message listing what's missing.
* Kick/swap/settings allowed after the match started → lobby only.
* Real secrets were committed in `.env` → removed from the delivery (**rotate them**, see §7).

---

## 3. New features

### Match engine
* **Four innings** with correct routing, follow-on (enforce/decline/timeout = decline),
  **target** = opponent aggregate − own aggregate + 1, **innings victory** detected after innings 3.
* **Results:** won by N wickets / by N runs / by an innings and N runs / tie / draw / abandoned.
* **Days & stumps:** `overs` = overs per day. When the day's overs are done → Stumps embed with a
  "Start next day" button (or `+resume`). Running out of days → **draw**.
* **Innings over cap** (`settings innings_overs`, default = overs per day as in the spec; 0 = unlimited).
* **Declaration** — instant (interrupts the pending ball), guarded by the spec's rules.
* **Pause / resume** for the host, and crash-safe: any unexpected error pauses and saves the match
  instead of killing it; `+resume` continues.
* **Hat-tricks, fifties, hundreds, ducks, maidens** detected and announced.
* **Player of the Match** chosen from runs and wickets across the match.
* **AFK:** `afk_max_strikes` consecutive misses (resets when the player answers). Closed DMs are detected,
  the player is told in the channel, and it counts as a miss.
* Optional house rule: bowler changed after N no-balls in an over (`max_no_balls_per_over`).
* `last_man_bats` option (last batter bats alone).

### Multiple matches & continuation
* Each channel has its own `MatchInstance` and its own background task (`bot.active_matches` keeps its
  `{channel_id: MatchInstance}` shape, as the spec required).
* DM picks are matched by player **and** DM channel **and** time, so matches can't steal each other's picks.
* **Persistence:** after every ball a coalescing writer saves (a) the full match state to the existing
  `ongoing_matches` table and (b) a public snapshot to `matches` for the website. One write in flight per
  match, never blocks play; a failed write is logged and retried with the next ball.
* **Restart:** on start-up every saved lobby and match is restored. Lobbies reappear with a fresh Join
  button; running matches come back paused (`+resume`); stumps come back with the "Start next day" button.
* Idle lobbies auto-close after `lobby_ttl_minutes`.

### Stats & economy (HandCricket-compatible)
* Profile columns use the HandCricket bot's names and formulas: `matches_played, matches_won,
  matches_lost, runs, balls, wickets, wickets_lost, highest_score, hattricks, ducks, batting_average
  (runs / wickets_lost), match_log, description, status`.
* Commands mirror HandCricket: `profile`/`me`, `userstats`, `leaderboard`/`lb`, `matchlog`.
* Extended test stats: innings, not outs, 4s/6s, 50s/100s, overs, maidens, best bowling, 5-wicket
  hauls, no-balls, draws/ties, Player of the Match awards.
* `exportprofile` downloads your profile in HandCricket JSON; owner `importprofile` merges a HandCricket
  JSON file into a profile.
* **Coins:** start balance, `daily` (with streak bonus), `weekly`, `give`, match rewards (participation,
  win/draw/tie, per run, per wicket, 50/100, 5-for, hat-trick, POTM). Matches shorter than
  `min_balls_for_rewards` legal balls pay nothing (anti-farming). Abandoned matches pay nothing.
* **Shop:** cosmetic titles, profile colours and badges; `buy`, `inventory`, `equip`, `unequip`.
* Every coin change is recorded in a `transactions` ledger. Match recording is atomic and idempotent
  (a restart can never pay twice).
* Owner tools: `addcoins`, `removecoins`, `matches` (list active), `sync`.

### Look & feel
* Consistent theme from the logo (cream, ball gold, pitch green) in `core/ui/theme.py`.
* Lobby is a live card with Join/Leave buttons that updates as players join.
* DM prompts are embeds (players type their number, no buttons) showing the score, opponent and the
  batter's dot count; countdown edits cut from 12 per ball to 2.
* **Image scorecard** (PNG, same style as the website) posted at every stumps and with the result:
  scoreboard header plus the batting and bowling card of every innings. Rendered with Pillow off the main
  thread; if Pillow is missing the embeds are posted without the image.
* Wicket, over, milestone, hat-trick, stumps, innings-summary and result cards.
* `scorecard` shows full batting & bowling tables with an innings switcher.
* `help` is a menu with pages: quick start, lobby, playing, rules, stats, coins.

### Website (`website/`)
* Static single-page app + Vercel serverless functions reading Turso (read-only token).
* Pages: live scoreboard (updates every 3–5 s), results, match scorecards with innings tabs,
  ball-by-ball commentary and squads, leaderboard (9 categories), player pages with batting/bowling/
  results figures, form chart and recent matches, player search.
* The live match is drawn as a manual Test scoreboard; numerals flip when the score changes
  (disabled when the visitor prefers reduced motion). Responsive to mobile.

---

## 4. Files

| File | Status |
|---|---|
| `core/backend/game.py` | Rewritten around the original methods (all original method names kept) |
| `core/backend/instance.py` | All original fields kept; spec fields added; save/restore |
| `core/backend/innings.py` | `One`/`Two` kept, `Three`/`Four` added, `MatchDecisions` fixed |
| `core/backend/checks.py` | Fixed checks; single `game_continue_check`; all-out rule |
| `core/backend/persistence.py` | **New** — saving, website snapshot, restart restore |
| `core/backend/lobby.py`, `permissions.py` | **New** — shared lobby rules |
| `core/backend/views/*` | Fixed; new `pick_view.py` (DM buttons), `stumps_view.py` |
| `core/backend/dropdown/player_select.py` | Fixed timeout + auto-pick |
| `core/backend/turso/db.py`, `schemas.sql` | Rewritten client; new tables (existing table untouched) |
| `core/commands/*` | Fixed; new `economy.py`, `help.py` |
| `core/economy/*`, `core/ui/*` | **New** |
| `website/*`, `tests/*`, `docs/*`, `README.md` | **New** |
| `core/commands/user_i.py`, `core/backend/conditions.py`, `core/backend/turso/tests.py` | Removed (dead/empty) |

Database: the existing `ongoing_matches` table is reused unchanged (resume state). New tables:
`matches`, `profiles`, `player_match_stats`, `transactions`. All are created automatically.

---

## 5. Where I made a judgement call (please confirm with the client)

1. **Overs = overs per day** (10–90; 90 is a real Test day). Each innings is capped at the same number
   by default, exactly as spec §5.4 reads; the host can lift the cap with `+settings innings_overs 0`.
2. **Follow-on threshold** defaults to **50 %** of the first-innings score (from the original
   `follow_on_check` code) rather than the spec's 40 %. Configurable (`follow_on_pct`).
3. **All out** = one batter left (spec §5.5), so the last player in a team never bats. `last_man_bats`
   in `config.toml` switches to "every batter bats".
4. **Invalid DM numbers** are rejected inline and the ball keeps waiting, instead of re-prompting both
   players (same outcome as spec §4.1, fewer messages).
5. **On-deck picks** at the start of each innings were kept (the second dropdown is intentional in the
   original flow — it chooses who comes in next), rather than removed as the spec suggested.
6. **Saving every ball** instead of only at over ends, so the website is truly live and a crash loses at
   most one ball. Writes are coalesced so this is cheap (about 1 request per ball).
7. **"Compatible with the HandCricket bot":** that bot has no public API, so compatibility means the same
   profile fields/formulas, the same command names, and import/export in its JSON shape. Its exact live
   economy isn't publicly documented, so the coin system follows common Discord bot conventions.
8. **Representatives (`join rep`)** — the original code had a placeholder. **Now defined** (see the last
   update below): reps bat with a run cap (default 30), can't bowl, and are tagged (R) everywhere.

---

## 6. Testing

Because discord.py can't be installed in this build environment, the suite runs against
`tests/fakediscord`, a stand-in that implements the discord.py API used here **and enforces Discord's real
limits** (embed sizes, 25 options, button rows, empty messages, interaction acknowledgement). Simulated
players answer DM prompts by typing their number; captains use dropdowns or ignore them.

Covered (47 tests, ~100 s):
* every ball rule (no-ball, clash, 5 dots, fresh dot count, hat-trick, no consecutive overs, fifty)
* AFK batter/bowler, strike resets, closed DMs, invalid numbers, picks typed in the server, stale
  messages, other people pressing your buttons
* declaration rules, follow-on enforced and declined, stumps → next day → draw, manual resume
  permissions, pause/resume, abandon (in play and at stumps)
* result maths: chase by wickets, defend by runs, tie, draw, innings victory, chase completed by a no-ball
* 1v1, uneven teams, all-out limits
* restart after pause, restart after a hard crash, lobby + stumps restored, 4 simultaneous matches,
  one-match-per-player
* every lobby/host command and permission, toss/bat-bowl guards and timeouts, DM-only refusal
* scorecard/help/score rendering within Discord limits
* profiles vs scorecards, coin ledger, idempotent recording, daily streaks, give, shop, leaderboards,
  HandCricket export/import
* the Turso client against a protocol-faithful fake Turso server (typed values, 64-bit IDs, atomic rollback, auth)
* a full match on the Turso backend, then every website API function against it (Node)
* randomised soak: up to 60 concurrent chaotic matches (AFKs, no-balls, ignored dropdowns, odd team
  sizes) — all completed with consistent scorecards.

Every innings card in every test is checked like a real scorecard: batting runs + extras = total,
bowling runs = total, balls add up, wickets = dismissals, FOW count = wickets.

---

## 7. Left to do / known limits

* **Rotate the secrets.** The uploaded archive contained a real bot token, Turso token and webhook URL
  in `.env`. They were removed from this delivery, but anyone who saw the archive has them — regenerate
  all three.
* **Live Discord smoke test.** All logic was tested against the simulated Discord layer, not the live
  Discord API. Run one real match with 4 people before handing over (create → toss → start → a wicket →
  declare → stumps → resume) to confirm permissions, emojis and DMs behave on a real server.
* **Custom emojis** only render for the bot application that owns them (see README).
* **Slash commands:** the bot uses prefix commands (as the original did); only the existing `/say` is a
  slash command.
* ~~Bot players~~ — **done**: CPU players (`+cpu add`), see the last update below.
* ~~Representative rules~~ — **done**: run cap, no bowling, (R) tags, see the last update below.
* Website fonts load from Google Fonts; if blocked, system fonts are used.


---

# Update — tournament mode, server whitelist, owner economy, website login

## What was added

| Area | Summary |
|---|---|
| Tournament mode | One tournament per server (enforced by a unique index). League, pools + knockout, and knockout formats; registration, teams, invites, rosters, pools, seeding, fixtures, scheduling with reminders, points table with net run rate, knockout bracket with byes, manual results / walkovers / resets, withdrawals, awards, optional prizes |
| Tournament matches | `+create` asks "tournament match?" while a tournament is being played; `+tm [number]` marks a lobby at any time. Marked lobbies use the tournament's teams and rules and admit roster players only. Results are recorded automatically |
| Roles | Organiser roles, player role, captain role, per-team roles (existing or created by the bot), registration role, role sync and clean-up |
| Server whitelist | Global command check; `+server` owner commands; optional expiry; DM notice to the owner when the bot joins a server |
| Owner economy | `+eco` add / remove / set / reset / view / role / stats; every amount and five switches editable at runtime and stored in the database |
| Website | Discord OAuth login, tournament directory and pages, "My tournaments", organiser Manage tab, owner panel |

## How it fits together

```
Discord command ─┐
                 ├─► TournamentManager.run() ─► actions.perform() ─► database
website request ─┘        (permission)            (all the rules)       │
   (web_tasks queue,                                                    ▼
    polled by the bot)     Discord effects ◄── Result.effects      cache (table + stats)
                           (announce, roles, DMs, prizes)           read by the website
```

* `core/tournament/actions.py` is the only place tournament rules live. Commands and the website both
  call it, so they cannot drift apart.
* `core/tournament/logic.py` is pure maths (round-robin, bracket seeding, standings, player tables,
  time parsing) with direct unit tests.
* The website **reads** the database directly and **writes** only login sessions and `web_tasks` rows.
  The bot runs each task after re-checking the member's permission in Discord.
* The bot publishes what the website needs: the settings schema (`bot_settings`), each server's roles
  and channels (`guild_meta`), its server list and a heartbeat.

## New tables

`guild_access`, `bot_settings`, `guild_meta`, `tournaments`, `tournament_staff`, `tournament_teams`,
`tournament_players`, `tournament_invites`, `tournament_fixtures`, `tournament_audit`, `web_tasks`,
`web_sessions`. New columns (added automatically by the migration list in `turso/db.py`):
`matches.tournament_id`, `matches.fixture_id`, and seven per-match figures on `player_match_stats`.

## Changes to existing code

* `MatchInstance.tournament` (saved and restored with the match); `lobby.try_join` seats roster players.
* `host.py`: prompt after `create`; overs/days/team names/swap/settings locked in tournament lobbies.
* `match.py`: tournament pre-start checks. `game.py`: result and abandon hooks.
* `persistence.py`: tournament info in the public match snapshot and on the `matches` row.
* `economy.py` / `profiles.py`: switches honoured; owner balance helpers; richer per-match stats.
* `owner.py`: rewritten (`+owner`, `+server`, `+eco`); `error.py`: whitelist notice.
* `init.py`: owner IDs from config, whitelist, tournament manager and its background loops.
* Tests: the fake Discord layer gained roles, permissions, global checks and gateway listeners.

## Design decisions worth knowing

* **`+tour`, not `+t`** — `+t` was already the toss.
* **A match host does not have to play** in a tournament match, so organisers can host.
* **Drawn knockout matches** use the first-innings lead by default; otherwise an organiser decides.
* **Prizes are owner-only settings** because they create coins; everything else is the organiser's.
* **The player role is given to players on a team**, and roles are only ever removed from people the
  tournament knows about — pointing a setting at a big existing role cannot strip it from the server.
* **Website edits are queued, not applied directly**: slightly slower (a few seconds), but one rule set
  and real Discord permission checks.

## Tests

76 automated tests (51 before): tournament maths, full league and pools-to-knockout tournaments played
ball by ball, registration/roster rules, roles, the whitelist, owner economy, the website queue, and a
Node test of Discord login and the tournament API against a fake Turso server with the bot running.

## Not included

* Double elimination, Swiss, and third-place play-offs.
* Picking any server member by name on the website (the site has no member list — it offers registered
  players, and Discord user IDs for everyone else).
* Payments: the whitelist has expiry dates and notes ready for a billing system, but nothing charges money.


---

# Update — representatives, substitutes, CPU players, JSON match sheet

## What was added

| Area | Summary |
|---|---|
| **Representatives (R)** | `join rep` (or host `setrep`). A rep's runs are capped per innings (`rep_run_cap`, default **30**; runs past the cap don't count). At the cap the rep is **retired out** (a wicket, not the bowler's) or, with `rep_retire_counts_wicket` off, **retired not out**. Reps **can't bowl** unless `rep_can_bowl` is on. Optional `max_reps_per_team`. Host settings per match; tournament settings per tournament. (R) on the lobby, scoreboard, DM prompt, scorecard embeds, PNG card, website and match sheet |
| **Substitutes** | `sub <out> <in> [rep]` by the host or that team's captain, in the lobby or mid-match. **Squad rule:** the incoming player must be in the team's squad — the bench (`join sub A\|B`) in a friendly, the registered roster in a tournament. Mid-match the substitute takes over at the crease (outgoing batter *retired — substituted*, not out), in the over (a rep can't bowl, so another bowler finishes it) and as captain. Figures of both players are kept and recorded. Limits: `max_subs_per_team`, `subs_during_match` |
| **CPU players** | `cpu add [A\|B] [n]` / `cpu remove <name\|all>` in friendly lobbies. They pick numbers (no no-balls, avoid the 5th dot), captain instantly (toss call, bat/bowl, batter/bowler picks, follow-on), survive restarts, are never "busy elsewhere" and never take a human's captaincy. By default a match with a CPU records no stats and pays no coins (`cpu_matches_count`) |
| **JSON match sheet** | `match_<id>.json` posted right after the result card; `matchsheet [id]` downloads it again (live snapshot during a match, from the database for old matches). Public data only. Format: `docs/MATCH_SHEET.md` |
| Bug fix | A closed innings card showed the not-out batter as "batting"; it now says "not out" |

## Design decisions (please confirm)

1. **Rep cap = runs per innings**, counted on the rep's own score (no-ball extras never count towards it).
   The ball that reaches the cap is truncated (28 + a six = 30) so the team total and bowler figures
   match the batter's.
2. **Reaching the cap = retired out (a wicket)** by default, because otherwise a side of reps could bat
   for ever. `rep_retire_counts_wicket = false` gives *retired not out*: no wicket, but the batting place is
   used up, so "all out" still happens when nobody is left (`retired_not_out` is counted in the all-out check).
3. **Squad** (changed after review, see "Follow-up" below): in friendlies anyone not already in the match;
   in tournaments the registered roster, or anyone but the opponent's players when `subs_outside_squad` is on.
   A substitute replaces exactly one player; that player can't return.
4. **Mid-match substitutions happen between deliveries**: the command is accepted while the bot is
   waiting for a ball (or the match is paused / at stumps); the pending ball is replayed with the new player.
   During an innings break or a dropdown pick the bot asks to try again a moment later.
5. **A substitute who was a rep's replacement is not automatically a rep** — add `rep` to the command.
6. **The host stays the host** after being substituted out (so someone can still pause/resume).
7. **CPU matches don't count** by default (anti-farming); the owner can switch it.
8. **The match sheet is a separate message** after the result card, so the result card (and its image)
   is exactly as before.

## Files

| File | Status |
|---|---|
| `core/backend/cpu.py` | **New** — `CpuPlayer`, CPU picks and captain choices |
| `core/backend/match_sheet.py` | **New** — builds the JSON match sheet |
| `core/commands/squad.py` | **New** — `sub`, `setrep`, `cpu` |
| `core/backend/game.py` | Rep cap/retirement, bowler eligibility, `apply_substitution`, CPU picks, sheet posting, row flags |
| `core/backend/instance.py` | `bench`, `substitutions`, `subbed_out`, `cpu_names`, `retired_not_out`, rep/sub settings; saved and restored |
| `core/backend/checks.py` | All-out counts reps retired not out |
| `core/backend/lobby.py` | Rep limit, bench join/leave, CPU captaincy hand-over, (CPU)/(sub) tags, bench + rep rules on the lobby card |
| `core/backend/persistence.py` | Public snapshot: rep/CPU/sub flags, substitutions, rep rules |
| `core/backend/views/toss_view.py`, `batball_view.py` | CPU auto toss call / bat-bowl choice (button handlers unchanged) |
| `core/commands/players.py` | `join rep` / `join sub A\|B` parsing |
| `core/commands/host.py` | New `settings` keys |
| `core/commands/match.py` | Start checks (a side of only reps can't bowl), CPU toss, `matchsheet` |
| `core/commands/help.py` | New "Reps, subs & CPUs" page |
| `core/economy/profiles.py` | Records substituted-out players, skips CPUs / CPU matches |
| `core/tournament/schema.py`, `manager.py` | "Reps & substitutes" settings applied to tournament lobbies; roster = squad |
| `core/ui/cards.py`, `scorecard_image.py`, `website/assets/app.js` | (R) / (sub) / CPU tags, substitutions list |
| `config.py`, `config.toml` | New `[game]` keys (see `docs/OWNER_GUIDE.md` §4) |
| `tests/test_reps_subs_cpu.py` | **New** — 12 tests |

No database migration is needed: the new state lives in the saved match JSON and the public snapshot.

## Tests

88 automated tests (76 before), all passing (89 after the follow-up below). The new ones cover: the rep cap with retirement as a
wicket and as not out (and the all-out rule), reps never bowling, rep settings/limits/start checks,
lobby substitutes and the bench, a mid-match substitute at the crease (both players' stats recorded),
a rep substitute for the bowler (another bowler finishes the over), substitution limits/switches,
the tournament squad rule and tournament rep settings, a full match against CPU players (no stats
recorded), CPU players surviving a restart, the match sheet (attached, complete, adds up, no private
IDs, downloadable again from memory and from the database), and a soak of 6 concurrent random matches
mixing reps, CPUs and a mid-match CPU substitute. Every innings card still passes the scorecard
consistency check.


## Follow-up — squads on resume, who can be a substitute

| Change | Detail |
|---|---|
| **Squads shown when play resumes** | Whenever play restarts — the next day after stumps (button or `resume`) or after a pause — the bot posts **📋 Squads — Day N** before the next ball: both XIs with captain/rep/sub tags, who is batting and bowling, and who was subbed out. Captains replace anyone who isn't there today with `sub`. Play starts when the host or a captain presses **Start play** (or types `resume` again), or after `squad_check_seconds` (default 60; 0 = off). Nothing is bowled meanwhile |
| **Friendly substitutes** | Anyone who isn't already in the match (the bench is now optional — it only shows who's available) |
| **Tournament substitutes** | The team's registered squad only. New setting `subs_outside_squad` (Reps & substitutes group, default off) and the shortcut `tour subs on\|off` for organisers (the tournament host included) allow players from outside the squad. It is read live. Players registered with the opponent are always refused. Outside substitutes are kept in the lobby when rosters are re-checked (`tournament.guests`), play only that match and are not added to the roster |

Files: new `core/backend/views/squad_view.py` (Start play button); `game.py` (`squads_embed`, `squad_check`,
triggered by a flag that `resume_play` sets, so it also works when resume is pressed the instant stumps
are called); `instance.py` (`squad_check_pending`, `squad_check_view`, `squad_check_seconds`);
`match.py` (`resume` during the squad check starts play); `squad.py` (new eligibility rules);
`tournament/manager.py` (`outside_subs_allowed`, guests kept by `refresh_rosters`); `tournament/schema.py`;
`commands/tournament.py` (`tour subs`); config keys. Tests: the friendly-sub test was rewritten for the
new rule; new test for the resume squad check (squads shown, no balls bowled, absent player subbed,
Start play permissions, `resume` twice); the tournament test now covers `tour subs on/off`
(organisers only, outsider accepted, opponent still refused, outsider kept on roster refresh).
