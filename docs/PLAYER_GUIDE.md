# BSW Test Cricket — player guide

**BSW Test Cricket** brings the playground game of hand cricket to Discord in its longest, most
tactical form: the **Test match**. Two teams of up to 11 play four innings over several "days", with
declarations, the follow-on, nightly stumps and a full scorecard. Every ball is a blind duel played in
the bot's DMs: the batter and the bowler each pick a number from 0 to 6 at the same time.

The default prefix is **`+`** (it can be changed in `config.toml`). `+help` opens the in-Discord guide.

---

## 1. Quick start

1. `+create` — opens a lobby in the channel. You are the **host** and the first player of Team A.
2. Friends join with `+join` or the **Join Match** button. Players alternate between the teams automatically.
   The first player in each team is its **captain**.
3. Host sets the format: `+so 20` (overs per day, 10–90) and `+sd 3` (days, 1–5).
4. Host: `+toss`. A captain calls **Heads/Tails**; the winner picks **Bat** or **Bowl**.
5. Host: `+start`. Captains choose their opening batter and bowler from dropdowns.
6. **Open your DMs from server members** — every ball is played there.

---

## 2. Playing a ball

When it's your turn the bot DMs you a prompt. **Type a number from 0 to 6** in that DM.
You have **30 seconds** (configurable). Nobody can see the other's pick.

| Batter picks | Bowler picks | Result |
|---|---|---|
| same number as the bowler | same number | **OUT** — the bowler takes the wicket |
| any number | a different number (1–6) | the batter scores **their own number** (0 = dot ball) |
| anything | **0** | **No ball** — +1 run to the batting side, the ball is bowled again, the batter can't be out |

**Five-dot rule:** a batter may play four 0s in an over. A **fifth 0 in the same over is out**
(this is not a wicket for the bowler). A new batter always starts with a fresh count. The prompt
shows your current dot count.

After each ball both players get a DM with what the other picked and the over so far.
Only numbers **0–6 typed in DMs** count; anything else is ignored, and numbers above 6 get a ❌.

---

## 3. Overs, bowlers and batters

* An over is **6 legal balls** (no-balls don't count).
* **Nobody bowls two overs in a row.** The bowling captain picks the next over's bowler while the
  current over is being bowled.
* The batting captain picks the **on-deck batter** (who comes in at the next wicket).
* If a captain doesn't pick in time, the bot picks for them, so the game never stalls.
* The live **scoreboard** in the channel updates after every ball: score, run rate, lead/target,
  current batter & bowler, this over, timeline, fall of wickets, overs left today.

---

## 4. Innings and the match

A Test has up to **four innings** — each team bats twice.

An innings ends when:
* the batting side is **all out** — when only one batter is left without a partner
  (in a team of 4, the third wicket ends the innings);
* the batting captain **declares**;
* it reaches the **innings over limit** (by default the same as the overs per day; the host can change
  it with `+settings innings_overs <n>`, 0 = no limit);
* the side batting fourth reaches the **target**.

### Declaring
The **batting captain** can close the innings with `+declare` (then press **Yes**). Rules:
* not in the 4th innings;
* at least **5 overs** must have been bowled in the innings (configurable).

The declaration takes effect immediately.

### The follow-on
If the team batting second scores less than **50 %** of the first innings score, the leading captain
gets a button: **Enforce follow-on** (the trailing team bats again straight away) or **Bat again
ourselves**. No answer in 2 minutes = not enforced.

### Days and stumps
`overs per day` sets how many overs are bowled each day. When they're done it's **Stumps**: the match
is saved and play stops. The host or a captain presses **Start next day** (or types `+resume`) whenever
everyone is back — later that day or next week. When the last day ends, the match is a **draw**.

### Results
* **Won by N wickets** — the side batting fourth reaches the target.
* **Won by N runs** — the side batting fourth is all out short of the target.
* **Won by an innings and N runs** — after three innings, the side yet to bat a second time already
  leads on aggregate.
* **Tie** — the side batting fourth is all out with the scores level.
* **Draw** — time runs out (days, or the 4th innings over limit) before a result.

A **Player of the Match** is named and coins are paid out (see §8).

### Scorecard images
At every **stumps** and when the **match ends**, the bot posts an image scorecard: the scoreboard plus
the full batting and bowling card of every innings so far — easy to save or share.

---

## 5. If someone is away

* Miss a ball and the ball is replayed; the channel shows your strike count.
* **3 misses in a row** (configurable): a batter is given **out (AFK)**; a bowler is **replaced** and
  the bowling captain picks someone to finish the over.
* Answering a ball resets your strikes.
* If the bot can't DM you, it tells you in the channel — those balls count as misses.

---

## 5a. Representatives (R)

A **representative** joins with `+join rep` (the host can also mark someone in the lobby with
`+setrep <player> on|off`). Reps are shown as **(R)** in the lobby, on the live scoreboard, on every
scorecard (Discord, image and website) and in the match sheet.

| Rule | Default | Change it with |
|---|---|---|
| Most runs a rep can score in one innings | **30** | `+settings rep_run_cap <0-500>` (0 = no cap) |
| What happens at the cap | **retired out** — it counts as a wicket (not the bowler's) | `+settings rep_retire_counts_wicket 0` → *retired not out* |
| Can reps bowl? | **No** — they are never offered as bowlers | `+settings rep_can_bowl 1` |
| Reps per team | no limit | `+settings max_reps_per_team <n>` |

* Runs past the cap don't count: a rep on 28 who hits a six gets **2** (28 → 30) and walks off.
* The ball that takes a rep to the cap counts normally; the next batter comes in straight away.
* *Retired not out* uses up a batting place without a wicket, so a side can still run out of batters.
* If the winning runs take a rep to the cap, the match simply ends.
* A side needs **at least one non-rep** (someone who can bowl) before the host can `+start`.
* Tournaments have the same rules as tournament settings (`docs/TOURNAMENTS.md` §4).

## 5b. Substitutes

When a player can't carry on, the **host or that team's captain** can bring in a substitute:

```
+sub <player out> <player in>          e.g.  +sub @Sam @Alex      (or by name: +sub Sam Alex)
+sub <player out> <player in> rep      the substitute comes in as a rep (R)
+sub                                   shows the bench and the substitutions made so far
```

**Who can come in:**
* **Friendly (normal match):** **anyone who isn't already in the match.** Players can also wait on a team's
  bench with `+join sub A` / `+join sub B` so captains can see who's available — that's optional.
* **Tournament:** a player from the team's **registered squad** (made when the teams registered) who isn't
  already playing. Players registered with the opponent are always refused. The tournament host or an
  organiser can allow substitutes from **outside the squad** with `+tour subs on` (`+tour subs off` to stop).

**Squads when play resumes.** When the host or a captain resumes the match — the next day after stumps,
or after a pause — the bot first posts **📋 Squads — Day N** with everyone in the match (who's at the
crease, who's bowling, captains, reps, earlier subs). If someone who played before isn't there today,
replace them with `+sub` now. Play starts when the host or a captain presses **Start play** (or types
`+resume` again), or by itself after 60 seconds (`squad_check_seconds` in `config.toml`).

**In the lobby** the substitute simply takes the player's place in the team.

**During the match** (unless switched off) — during the squad check or between deliveries — the substitute
takes over at once (a ball in progress is replayed):
* If the outgoing player was **batting**, the substitute takes over at the crease. The outgoing player is
  shown as *retired — substituted* (not out, no wicket) with their runs kept.
* If they were **bowling**, the substitute finishes the over. A rep can't bowl, so the bot hands the over
  to another bowler and says so.
* Captaincy passes to the substitute if the captain was replaced. The host stays the host.
* The outgoing player can't come back. Their figures stay on the scorecard, and **both** players get
  stats for the match.
* Limit: `+settings max_subs_per_team <n>` (0 = no limit).
* Scorecards show the substitute as **(sub)** and list the substitutions under the innings.

## 5c. CPU players (friendly matches)

Short of players? The host can add computer players in the lobby:

```
+cpu add            one CPU, to the smaller team
+cpu add B 3        three CPUs to Team B
+cpu remove Robo 🤖 / +cpu remove all
```

CPUs play their own numbers (they never bowl no-balls), and a CPU captain picks batters and bowlers,
calls the toss and decides the follow-on instantly. A human always takes over the captaincy from a CPU
on the same team. CPUs can't play in tournament matches. **A match with a CPU in it records no stats
and pays no coins** (so they can't be used to farm). The bot owner can change that with
`cpu_matches_count = true` in `config.toml`, in which case only the human players are recorded.

## 5d. The match sheet (JSON)

When a match finishes, the bot posts **`match_<id>.json`** right after the result card. It holds everything
public about the match: teams and squads (captains, reps, substitutes, CPUs), rules, toss, every innings
(batting, bowling, fall of wickets, extras), substitutions, totals for every player, the result, the Player
of the Match and the commentary. It has no private Discord data. `+matchsheet` (in the channel) or
`+matchsheet <match id>` (anywhere) downloads it again; during a match it gives a live snapshot. The
format is described in `docs/MATCH_SHEET.md`.

---

## 6. Commands

### Lobby & host
| Command | What it does | Who |
|---|---|---|
| `+create` / `+c` | Create a lobby in this channel | anyone |
| `+join` / `+j` | Join (`+join rep` joins as a representative, shown (R)) | anyone |
| `+join sub A\|B` | Wait on a team's bench as an available substitute (optional, friendlies) | anyone |
| `+sub <out> <in> [rep]` | Bring a squad player in for someone — lobby or mid-match (§5b) | host or that team's captain |
| `+setrep [player] [on\|off]` | Show the rep rules, or mark/unmark a rep in the lobby | host |
| `+cpu add [A\|B] [n]` / `+cpu remove <name\|all>` | CPU players (friendlies, lobby) | host |
| `+leave` / `+l` | Leave before the start (host and captains must hand over first) | player |
| `+players` / `+pl` | Lobby card and teams | anyone |
| `+so <10-90>` | Overs per day | host |
| `+sd <1-5>` | Number of days | host |
| `+ctn <A\|B> <name>` | Rename a team | host |
| `+cc <A\|B> @user` | Change a captain (must be in that team) | host or that captain |
| `+swap @a @b` | Swap two players between teams | host |
| `+kick @user` | Remove a player | host, or a captain for their own team |
| `+ll` / `+ul` | Lock / unlock the lobby | host |
| `+ch @user` | Hand over host | host |
| `+settings` | View advanced settings; `+settings <name> <value>` to change | host (before start) |
| `+yeet` / `+abandon` | Delete the lobby, or abandon a match (nothing is recorded) | host |

Advanced settings: `innings_overs`, `follow_on_pct`, `min_declare_overs`, `ball_timeout`,
`selection_timeout`, `afk_max_strikes`, `max_no_balls_per_over`, `last_man_bats`, `rep_run_cap`,
`rep_can_bowl`, `rep_retire_counts_wicket`, `max_reps_per_team`, `max_subs_per_team`.

### During the match
| Command | What it does | Who |
|---|---|---|
| `+toss` / `+t` | Start the toss | host |
| `+start` / `+s` | Start the match | host |
| `+declare` / `+dec` | Declare the innings | batting captain |
| `+pause` | Pause after the current ball | host |
| `+resume` / `+nd` | Start the next day after stumps, or resume a pause | host or captain |
| `+score` | Re-post the live scoreboard | anyone |
| `+scorecard [innings]` / `+sc` | Full batting & bowling card (menu to switch innings); `+sc <match id>` for an old match | anyone |
| `+instance` / `+i` | Match details | anyone |
| `+show <field>` | One detail: teams, captains, overs, days, score, target, settings… | anyone |
| `+sub <out> <in> [rep]` | Substitute a player mid-match (§5b) | host or that team's captain |
| `+matchsheet [match id]` / `+sheet` | Download the public JSON match sheet | anyone |

### Stats
| Command | What it does |
|---|---|
| `+profile [@user]` / `+me` | Profile card: matches, wins, runs, wickets, highest, hat-tricks, ducks, average, coins |
| `+userstats [@user]` / `+us` | Detailed batting, bowling and results |
| `+matchlog [@user]` / `+ml` | Recent matches |
| `+lb <category> [server]` | Leaderboards: runs, wickets, coins, wins, matches, average, highest, hattricks, sixes, potm |
| `+setdesc <text>` | Profile description |
| `+exportprofile` | Download your profile (HandCricket JSON format) |

### Coins
| Command | What it does |
|---|---|
| `+balance` / `+bal` | Your wallet |
| `+daily` | 250 coins, +25 per streak day (up to 7 days) |
| `+weekly` | 1,500 coins |
| `+give @user <amount>` | Send coins |
| `+shop` | Titles, profile colours and badges |
| `+buy <item>` / `+inventory` / `+equip <item>` / `+unequip title\|color` | Manage cosmetics |

### Other
`+help` (menu), `+rules`, `+ping`.

---

## 7. Restarts

Matches are saved after every ball. If the bot restarts:
* lobbies come back with a new Join button;
* matches in play come back **paused** — the host or a captain types `+resume`;
* matches at stumps come back with the **Start next day** button.

---

## 8. Coins and rewards

New players start with 500 coins. Completed matches (at least 30 legal balls) pay every player:

| Reward | Coins |
|---|---|
| Playing | 50 |
| Win / draw / tie bonus | 150 / 60 / 100 |
| Each run / each wicket | 1 / 10 |
| Fifty / hundred | 50 / 150 |
| Five wickets in an innings | 100 |
| Hat-trick | 200 |
| Player of the Match | 100 |

Abandoned matches pay nothing and record no stats. Everything in the shop is cosmetic — coins never
affect a match. All amounts can be changed in `config.toml`.

---

## 9. Website

The website shows every match in play (scoreboard updates every few seconds), all results with full
scorecards and ball-by-ball commentary, leaderboards and a page for every player. The scorecard and
profile embeds in Discord link straight to it once `website_url` is set.

---

## 10. FAQ

**Nothing happens when I type a number.** Type it in the bot's **DMs**, not the server, and only after
the prompt arrives. Make sure server DMs are allowed (Server → Privacy Settings → Direct Messages).

**Can I be in two matches?** No — your DM picks would be ambiguous. Leave or finish the first one.

**Why didn't our last player bat?** An innings ends when one batter is left without a partner
(the "last man" rule). The host can change this in `config.toml` (`last_man_bats`).

**We have to stop.** At stumps just leave it. Mid-day, the host can `+pause`. Everything is saved.

**Someone left the server.** Bring in a substitute from the bench (or the tournament roster) with
`+sub` — or the host can `+yeet` to abandon; nothing is recorded.

**Our rep stopped batting at 30.** That's the rep run cap (§5a). The host can change it before the start
with `+settings rep_run_cap <n>`.

**Why isn't our rep in the bowler list?** Reps can't bowl unless the host turns on `rep_can_bowl`.


---

## Tournaments

When your server runs a tournament, `+tour` shows it. Sign up with `+tour register` while registration
is open, then create a team (`+tour team create <name>`) or accept a captain's invite (`+tour accept`).
`+tour me` shows your team and next match; `+tour table`, `+tour bracket` and `+tour stats` follow the
competition. Tournament matches are played like any other — the captain opens a lobby with `+create`
and marks it with `+tm`, and only the two teams' players can join. Full guide: `docs/TOURNAMENTS.md`.
