# Owner guide — whitelist and economy

Everything here is for the **bot owner** only. Owners are the owner of the Discord application plus
any IDs in `owner_ids` (`config.toml`) or `OWNER_IDS` (`.env`). `+owner` shows this list in Discord.
The same controls are on the website at `/#/admin` (see `docs/WEBSITE_SETUP.md`).

## 1. Server whitelist

With `whitelist_enabled = true` (the default) the bot only runs commands in servers you have allowed.
In any other server it answers once (not on every command) with:

> 🔒 This server is **not authorised** to use the bot yet. Please ask @you to enable BSW Test Cricket here.
> Server ID: `1234…`

Set `[access] contact` in `config.toml` to replace the mention with your own text
("DM @name or join discord.gg/…").

| Command | What it does |
|---|---|
| `+server list` | Every server the bot is in, and every listed server, with its access |
| `+server allow` | Allow the server you are in, no end date |
| `+server allow <server id> [days] [note]` | Allow by ID. `days` makes it time-limited, e.g. `+server allow 1234 30 monthly plan` |
| `+server extend <server id> <days>` | Add days (from today if it already ran out) |
| `+server revoke [server id] [reason]` | Turn access off (the row is kept, marked blocked) |
| `+server forget <server id>` | Remove the row completely |
| `+server info [server id]` | Access, expiry, note, member count |
| `+server leave <server id>` | Make the bot leave a server |
| `+server whitelist on\|off` | Enforce the whitelist, or let every server in (remembered across restarts) |

Details that matter when you sell access:

* **Expiry is automatic.** When the date passes, commands stop and the server sees "access has expired".
* **You are told about new servers.** When the bot is added to an unlisted server you get a DM with the
  server name, ID and the exact `+server allow` command. (`notify_owner_on_join`, `leave_unlisted` in `config.toml`.)
* **You are never blocked.** Owner commands and `+ping` work everywhere.
* **DMs:** a user can use commands in the bot's DMs only if they share an allowed server with it.
* **Running matches** in a server whose access ends keep their state, but nobody can issue commands
  until you allow the server again.
* **The website** refuses tournament management for servers that are not allowed.

## 2. Economy control

| Command | What it does |
|---|---|
| `+eco add @user <amount> [reason]` | Add coins |
| `+eco remove @user <amount> [reason]` | Take coins (never below zero) |
| `+eco set @user <amount> [reason]` | Set the exact balance |
| `+eco reset @user` | Back to the starting balance |
| `+eco view @user` | Balance and the last transactions |
| `+eco role @role <amount> [reason]` | Pay everyone who has a role |
| `+eco stats` | Wallet count, coins in circulation, richest players |
| `+eco config` | Show every amount and switch |
| `+eco config <name> <value>` | Change one, e.g. `+eco config daily 500`, `+eco config give_enabled off` |
| `+eco config reset <name>` | Back to the value in `config.toml` |

Users can be given as a mention or an ID. Every change is written to the `transactions` ledger with
your ID and the reason, so the ledger always adds up to the balance.

**Switches** (all on by default): `daily_enabled`, `weekly_enabled`, `give_enabled`, `shop_enabled`,
`match_rewards_enabled`. To make the economy **owner-distributed only**, switch off `daily_enabled`,
`weekly_enabled`, `give_enabled` and `match_rewards_enabled` — then coins exist only where you put them.

**Amounts** you can change live: `start_balance`, `daily`, `daily_streak_bonus`, `daily_streak_cap`,
`weekly`, `participation`, `win`, `draw`, `tie`, `per_run`, `per_wicket`, `fifty`, `hundred`,
`five_wickets`, `hattrick`, `potm`, `min_balls_for_rewards`. Changes are stored in the database, apply
immediately and survive restarts; `config.toml` holds the defaults.

**Tournament prizes** create coins, so only you can set them, per tournament:
`+tour set prize_champion 5000`, `prize_runner_up`, `prize_mvp`, `prize_participation`. They are paid
once, automatically, when the tournament finishes.

## 3. Other owner commands

`+matches` (every active match) • `+dump` (state of the match in this channel) • `+sync` (slash
commands) • `+importprofile @user` (merge a HandCricket profile JSON).

## 4. Reps, substitutes, CPU players and the match sheet (`config.toml` → `[game]`)

These are the defaults for every friendly match. Hosts can change the rep and substitution values for
their own match with `+settings`, and tournaments have their own copies (`docs/TOURNAMENTS.md` §4).

| Key | Default | Meaning |
|---|---|---|
| `rep_run_cap` | `30` | Most runs a representative (R) may score in one innings (0 = no cap) |
| `rep_can_bowl` | `false` | Whether reps may bowl |
| `rep_retire_counts_wicket` | `true` | A rep reaching the cap is *retired out* (wicket); `false` = *retired not out* |
| `max_reps_per_team` | `0` | Most reps per team (0 = no limit) |
| `squad_check_seconds` | `60` | When play resumes (next day / after a pause) the bot shows both squads for this long so captains can `+sub` absent players; **Start play** or `+resume` starts sooner. 0 = off |
| `subs_during_match` | `true` | Allow `+sub` after the start (always allowed in the lobby) |
| `max_subs_per_team` | `0` | Most substitutions per team per match (0 = no limit) |
| `cpu_enabled` | `true` | Allow `+cpu add` in friendly lobbies |
| `cpu_delay` | `1.0` | Seconds a CPU "thinks" before each pick (0 = instant) |
| `cpu_matches_count` | `false` | `false`: a match with a CPU records no stats and pays no coins (no farming). `true`: the humans are recorded and paid |
| `match_sheet_file` | `true` | Post `match_<id>.json` after every finished match |
