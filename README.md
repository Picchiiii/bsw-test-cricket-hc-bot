# BSW Test Cricket — Discord bot + website

Test-match hand cricket for Discord: two teams of up to 11, four innings, multiple days, declarations,
the follow-on, live scorecards, career stats and a coin economy — plus **tournament mode**
(teams, pools, fixtures, points tables, knockout brackets, tournament stats), a **server whitelist**
and **owner-controlled economy**, and a website with live scores, tournament pages and Discord login.

## What's in the box

| Area | What it does | Read more |
|---|---|---|
| Matches | Lobby → toss → four innings over several days, saved after every ball | `docs/PLAYER_GUIDE.md` |
| **Reps, subs & CPUs** | Representatives (R) with a run cap (default 30) who can't bowl; substitutes from the squad (bench / tournament roster), even mid-match; CPU players for friendlies | `docs/PLAYER_GUIDE.md` §5a–5c |
| **Match sheet** | `match_<id>.json` with all public match data, posted after every result (`+matchsheet`) | `docs/MATCH_SHEET.md` |
| **Tournaments** | One tournament per server: registration, teams, pools, fixtures, table, bracket, roles, stats | `docs/TOURNAMENTS.md` |
| **Server whitelist** | Only servers you allow can use the bot; optional expiry dates | `docs/OWNER_GUIDE.md` |
| **Owner economy** | Add / remove / set anyone's coins, pay a role, change every amount, switch features off | `docs/OWNER_GUIDE.md` |
| Website | Live scoreboard, results, player pages, **tournament section, Discord login, manage + owner panels** | `docs/WEBSITE_SETUP.md` |
| What changed in the code | Every module, table and design decision | `docs/IMPLEMENTATION.md` |

```
bsw/
├─ main.py                 entry point
├─ config.toml             prefix, game rules, economy amounts, owner IDs, whitelist, tournament loops
├─ .env.example            secrets template (copy to .env)
├─ core/
│  ├─ init.py              bot creation, DB init, whitelist, tournament manager, restore saved matches
│  ├─ load.py              registers all command groups
│  ├─ backend/             match engine + access.py (whitelist) + resolve.py (mentions → members)
│  │                       + cpu.py (CPU players) + match_sheet.py (JSON match sheet)
│  ├─ commands/            host, players, match, squad (sub/setrep/cpu), economy, tournament, help, owner, error
│  ├─ economy/             profiles, match recording, shop, settings.py (owner-editable amounts)
│  ├─ tournament/          schema (settings) • logic (fixtures/tables) • store (SQL) • actions (rules)
│  │                       manager (Discord side, website queue) • render (embeds) • views (buttons)
│  └─ ui/                  theme, scorecard cards, paginator
├─ website/                Vercel site: static pages + /api serverless functions
├─ tests/                  simulated-Discord test suite (89 tests)
└─ docs/                   guides (see the table above)
```

## 1. Run the bot

Requirements: Python 3.11+.

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in BOT_TOKEN and the Turso variables
python main.py
```

Discord Developer Portal → your application → **Bot**: enable **Message Content Intent** and
**Server Members Intent**. Invite the bot with: View Channels, Send Messages, Embed Links, Attach
Files, Read Message History, Add Reactions, Use External Emojis, and **Manage Roles** (only needed if
tournaments should hand out roles — put the bot's role above the roles it assigns).

**First start checklist**

1. The **whitelist is on by default**. In your own server type `+server allow` — until you do, nobody
   except you can use the bot there. (`whitelist_enabled = false` in `config.toml` turns this off.)
2. If the bot is owned by a team, or you want more owners, put the user IDs in `owner_ids`
   (`config.toml`) or `OWNER_IDS` (`.env`).
3. `+owner` lists the owner commands, `+help` the player commands, `+tour help` the tournament ones.

The custom number emojis in `core/ui/theme.py` are the bot's own application emojis. For a different
bot application, upload `core/assets/images/emojis/*.png` as application emojis and paste the new
IDs, or set `use_custom_emojis = false`.

### Database

* **Turso (production, needed for the website):** set `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`
  (read-write) in `.env`. Tables and new columns are created automatically on start-up — updating
  from the previous version needs no manual migration.
* **Local SQLite (development):** leave the Turso variables empty — the bot uses `bsw.sqlite3`.

## 2. Deploy the website

Full steps, including Discord login: **`docs/WEBSITE_SETUP.md`**. Short version:

1. Vercel → **Add New → Project**, root directory `website`, framework *Other*, no build command.
2. Environment variables: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` (read-only), `TURSO_WRITE_TOKEN`
   (read-write), `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, optional `OWNER_IDS`.
3. Discord Developer Portal → OAuth2 → add the redirect `https://<your-site>/api/auth`.
4. Put the site address in `config.toml` → `website_url`.
5. Open `https://<your-site>/api/health` — it reports anything that is still missing.

Without the Discord variables the site still works exactly as before (live scores, stats and public
tournament pages); only login, management and the owner panel are hidden.

## 3. Run the tests

discord.py is not needed — the tests use a fake Discord layer (`tests/fakediscord`) with simulated
players, captains, roles and permissions, a fake Turso server, and (for the website) Node.

```bash
pip install pytest python-dotenv
cd tests && python -m pytest -q
```

## 4. Commands at a glance

| Who | Commands |
|---|---|
| Everyone | `+help` • `+create` `+join` `+toss` `+start` … • `+profile` `+lb` `+daily` `+shop` • `+matchsheet` |
| Reps & subs | `+join rep` • `+sub <out> <in> [rep]` (host/captain; anyone outside the match in friendlies, the squad in tournaments) • `+tour subs on\|off` • `+setrep` • `+settings rep_run_cap 30` |
| CPU players | `+cpu add [A\|B] [n]` • `+cpu remove <name\|all>` (host, friendly lobbies) |
| Tournaments | `+tour` (overview) • `+tour help` • `+tm <match number>` marks a lobby as a tournament match |
| Organisers | `+tour create` `set` `open` `start` `schedule` `result` `walkover` `end` … |
| Bot owner | `+owner` • `+server allow/revoke/extend/list` • `+eco add/remove/set/role/config` |

`+t` was already the toss, so the tournament command is `+tour` (also `+tournament`, `+tn`).
