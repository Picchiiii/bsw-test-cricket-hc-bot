# Tournament mode

A server runs **one tournament at a time**. The bot keeps the registrations, teams, pools, fixtures,
points table, knockout bracket and tournament stats, and updates them itself whenever a tournament
match ends. Everything can be done with commands, and organisers can do the same on the website.

Command: **`+tour`** (also `+tournament`, `+tn`). `+t` is the toss, so it could not be used.
`+tour help` shows this guide in Discord.

## 1. The quick version

```
+tour create Summer Cup           (needs Manage Server)
+tour set format groups           league | groups | knockout
+tour set overs 10                match rules for every tournament match
+tour set days 2
+tour channel announce #cup-news  where fixtures, reminders and results are posted
+tour open                        players: +tour register   captains: +tour team create <name>
+tour start                       fixtures are drawn, rosters lock
```

Then, for every match:

```
+create          the bot asks "Is this a tournament match?"  (or type +tm <match number>)
+join            only the two teams' players can join; each lands in their own team
+toss  +start    play as normal
```

When the match ends the fixture, table, bracket and stats update and the result is posted. When the
last match is decided the tournament closes itself and crowns the champion.

## 2. Who can do what

| Role | How you get it | Can |
|---|---|---|
| Organiser | **Manage Server** permission, the tournament host, anyone added with `+tour staff add`, anyone holding an organiser role (`+tour role organizer @role`) | Everything in the tournament |
| Captain | Created the team, or was made captain | Manage their own team while rosters are open; start their own fixtures |
| Vice-captain | `+tour team vice @user` | Invite and kick; start the team's fixtures |
| Player | `+tour register` | Join/leave teams, answer invites |
| Bot owner | — | Everything, plus prize settings |

## 3. Formats

| Format | What happens |
|---|---|
| `league` | Everyone plays everyone (`rounds` 1 or 2). With `qualifiers` ≥ 2 the top teams then play a knockout; with `qualifiers 0` the table decides the champion |
| `groups` | Teams are split into `groups` pools (2–8). Round-robin inside each pool, then the top `qualifiers` of every pool enter a knockout with cross-pool pairings (A1 v B2, B1 v A2 …) |
| `knockout` | Single elimination. Seeds (`+tour team seed`) decide the draw; top seeds get the byes when the number of teams is not 2, 4, 8, 16 … |

**Points** (all configurable): win 4, draw 2, tie 2, loss 0, no result 1, plus optional bonuses for an
innings win and for the first-innings lead in a drawn match. Level on points: most wins, then net run
rate. A walkover gives the points but does not touch net run rate.

**A drawn knockout match**: Tests can be drawn, so `knockout_draw_rule` decides — `first_innings`
(default: the side that led on first innings goes through) or `organiser` (an organiser names the
side with `+tour result <no> <team>`; the scorecard and stats are kept). If first innings were level,
it always falls to the organiser.

## 4. Settings

`+tour settings` shows them all; `+tour set <name> <value>`.

| Group | Settings |
|---|---|
| Format | `format`, `groups`, `rounds`, `qualifiers`, `max_teams` |
| Match rules | `overs`, `days`, `innings_overs` (-1 = same as overs, 0 = no cap), `follow_on_pct`, `min_declare_overs`, `last_man_bats` |
| Teams | `min_players` (needed in the lobby to start), `max_players` (a side), `max_squad` |
| Reps & substitutes | `rep_run_cap` (default 30, 0 = no cap), `rep_can_bowl` (off), `rep_retire_counts_wicket` (on), `max_reps` (per side, 0 = no limit), `allow_subs` (on), `subs_outside_squad` (off — `+tour subs on\|off`), `max_subs` (per side per match, 0 = no limit) |
| Registration | `team_creation` (open / staff), `team_join` (invite / open / staff), `registration_role` |
| Points | `points_win`, `points_tie`, `points_draw`, `points_loss`, `points_no_result`, `bonus_innings_win`, `bonus_first_innings_lead`, `knockout_draw_rule` |
| Automation | `prompt_on_create`, `captain_hosting`, `auto_advance`, `reminder_minutes`, `public` |
| Roles & channels | `organizer_roles`, `player_role`, `captain_role`, `auto_team_roles`, `announce_channel`, `results_channel`, `log_channel` |
| Prizes (bot owner) | `prize_champion`, `prize_runner_up`, `prize_mvp`, `prize_participation` |

`format`, `groups` and `rounds` are frozen once the tournament starts.

**Reps and substitutes in tournament matches.** Players join a tournament lobby with `+join rep` to play
as a representative (R); the rep settings above replace the host's match settings. The **squad** is
the team's registered roster: the captain (or vice-captain, or the host) brings in any roster player
who isn't already playing with `+sub <out> <in>`, in the lobby or mid-match — for example when the
bot shows the squads as play resumes the next day and someone from day 1 isn't there. Players from
outside the roster are refused **unless** an organiser turns on `+tour subs on` (the setting
`subs_outside_squad`, read live, so it can be switched on mid-match); players registered with the
opponent are always refused. Outside substitutes play only that match — they are not added to the
roster — and their figures appear in the tournament stats without a team. There is no bench
(`+join sub`) in tournament matches. CPU players can't take part. Players substituted out keep their figures, and both players'
runs and wickets count in the tournament stats.

## 5. Every command

### Everyone
| Command | |
|---|---|
| `+tour` | Overview: status, teams, live and next matches |
| `+tour rules` | Format, match rules and points |
| `+tour teams` • `+tour team <name or tag>` | All teams • one team's squad and matches |
| `+tour players` | Free agents (and banned players) |
| `+tour fixtures [team \| pool letter \| live \| todo \| done \| knockout]` • `+tour results` | Fixture list |
| `+tour table [pool]` • `+tour bracket` | Points table • knockout bracket |
| `+tour stats [runs\|wickets\|highest\|average\|strikerate\|economy\|best\|sixes\|fours\|fifties\|potm\|mvp]` | Tournament leaderboards |
| `+tour player [@user]` • `+tour me` | One player's tournament stats • your team, next matches, invites |
| `+tour history` | Past tournaments of this server |

### Players and captains
| Command | |
|---|---|
| `+tour register` / `+tour unregister` | Sign up / leave (registration must be open) |
| `+tour team create <name>` | Create a team; you become captain (a tag is made from the name) |
| `+tour invite @user` | Captain: invite a registered free agent (they get a DM and Accept/Decline buttons) |
| `+tour accept [team]` / `+tour decline [team]` | Answer an invite |
| `+tour team join <team>` | Join directly, when `team_join` is `open` |
| `+tour leave` | Leave your team |
| `+tour team kick @user` | Captain: remove a player |
| `+tour team captain @user` • `+tour team vice @user` | Hand over the captaincy • name a vice-captain |
| `+tour team rename <name>` • `+tour team tag <TAG>` • `+tour team disband` | |
| `+tm [match number]` • `+tm off` | Mark the lobby in this channel as your fixture • undo |

Captains can change their squad only while rosters are open (they lock at `+tour start`; organisers
can reopen a transfer window with `+tour unlock`).

### Organisers — set-up
| Command | |
|---|---|
| `+tour create <name>` • `+tour name <new>` • `+tour desc <text>` | |
| `+tour settings` • `+tour set <name> <value>` • `+tour format <format>` | |
| `+tour open` / `+tour close` | Registration |
| `+tour lock` / `+tour unlock` | Rosters |
| `+tour add @user…` | Register members yourself |
| `+tour team create <name> [@captain]` • `+tour team add <team> @user…` • `+tour move <team> @user` | |
| `+tour team remove @user` • `+tour team captain <team> @user` • `+tour team rename <team> <name>` • `+tour team delete <team>` | |
| `+tour team pool <team> <A–H>` • `+tour draw [seeded]` | Place a team in a pool • draw all pools |
| `+tour team seed <team> <n>` | Seeding (1 = best, 0 = unseeded) |
| `+tour autofill` | Spread the free agents over the teams |
| `+tour ban @user` / `+tour unban @user` | |
| `+tour staff add\|remove @user` • `+tour staff` • `+tour host @user` | |

Team names with spaces work, but the **tag** (e.g. `MI`) is quickest: `+tour team add MI @user`.

### Organisers — running it
| Command | |
|---|---|
| `+tour generate` | Build/preview the fixture list before starting |
| `+tour start` | Checks every team has `min_players`, draws fixtures, locks rosters |
| `+tm <number>` | Mark the lobby in this channel as that match (organisers can start any fixture) |
| `+tour schedule <number> <time>` | `2025-07-01 18:30` (UTC), `+2h`, `+1d12h`, a Discord timestamp, or `none`. Both teams are pinged `reminder_minutes` before |
| `+tour result <number> <team\|draw\|tie\|nr> [force]` | Enter a result by hand, or correct one (the bracket follows; `force` overrules a match in progress) |
| `+tour walkover <number> <team>` | Award the match |
| `+tour fixture reset <number>` | Wipe a result so the match is replayed (its scorecard stops counting) |
| `+tour fixture add <team> v <team> [extra] [time]` | Extra match; `extra` = does not count for the table |
| `+tour fixture remove <number>` • `+tour fixture teams <number> <team> v <team>` | |
| `+tour team withdraw <team>` | Team pulls out; opponents get walkovers |
| `+tour advance [force]` | Build the knockout now (automatic by default) |
| `+tour end [champion]` • `+tour cancel` • `+tour reopen` • `+tour delete` | Asked to confirm (or add `confirm`) |
| `+tour announce <text>` | Post in the announcements channel, pinging the player role |
| `+tour log` | Who changed what, and whether from Discord or the website |

### Roles and channels
| Command | |
|---|---|
| `+tour role organizer @role…` | Members with these roles can run the tournament |
| `+tour role player @role` • `+tour role captain @role` | Given automatically to players on a team • to captains |
| `+tour role auto on\|off` | The bot creates, renames and assigns one role per team |
| `+tour role team <team> @role` | Use an existing role for a team |
| `+tour role register @role` | Only this role may register |
| `+tour role sync` • `+tour role clear` | Repair roles • remove them all (and delete created team roles) afterwards |
| `+tour channel announce\|results\|log #channel` | Use `none` to clear |

The bot needs **Manage Roles** and its own role above the roles it hands out. If it can't, it says so
and carries on — nothing else is affected.

## 6. How tournament matches work

* `+create` in a server with a running tournament shows **"Is this a tournament match?"** to the match
  host. *Yes* marks it (with one eligible fixture) or offers a menu; *No* leaves it a friendly.
  `prompt_on_create off` removes the question; `+tm` always works.
* Captains can mark **their own team's fixtures** (`captain_hosting`); organisers can mark any, and can
  host without playing.
* A marked lobby takes the tournament's team names and rules (`+so`, `+sd`, `+ctn`, `+swap`,
  `+settings` are locked), removes anyone not on the two rosters, seats each player in their team and
  makes the tournament captain the match captain.
* A fixture can have only one lobby; a finished fixture can't be played again unless it is reset.
* On `+start` the fixture goes **live**; if the match is abandoned (`+yeet`) it returns to "to be played".
* Friendly matches can still be played in the server at any time — they never touch the tournament.
* Career stats and normal match coins are recorded exactly as for any match; tournament stats are the
  same scorecards, counted only for fixtures that currently have a result.

## 7. On the website

`<site>/#/tournaments` lists running tournaments and an honours board of past champions.
Each tournament has Overview, Table, Fixtures, Bracket, Teams and Stats pages.

After **Log in with Discord**:

* **My tournaments** — the ones you play in, the ones you run, and your servers (with *Create* for
  servers you manage).
* On a tournament page, players can register, create/join/leave a team and answer invites.
* Organisers get a **Manage** tab: lifecycle buttons, every setting (roles and channels as pick-lists),
  teams and rosters, schedule and results, organisers, announcements and the log.

The website never edits a tournament itself. It queues the request; the bot checks the person's
permission again in Discord and runs it within a few seconds, so commands and website can never
disagree. If the bot is offline the request waits (up to 15 minutes).
