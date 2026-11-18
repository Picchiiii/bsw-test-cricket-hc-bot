# Website set-up (Vercel + Discord login)

The site is static pages plus eleven small serverless functions in `website/api` (Vercel's free plan
allows twelve). It reads the same Turso database the bot writes.

## 1. Tokens

Create two Turso tokens for the bot's database:

```bash
turso db tokens create <db-name> --read-only     # → TURSO_AUTH_TOKEN  (public pages)
turso db tokens create <db-name>                 # → TURSO_WRITE_TOKEN (logins + queued actions)
```

The write token is used for two things only: storing login sessions, and adding rows to the
`web_tasks` queue that the bot reads. The website never changes matches, tournaments or coins itself.

## 2. Discord application

Discord Developer Portal → your bot's application → **OAuth2**:

1. Copy the **Client ID** and **Client Secret**.
2. Under **Redirects** add exactly: `https://<your-site>/api/auth`
   (for local testing also `http://localhost:3000/api/auth`).

The site asks for the `identify` and `guilds` scopes: who you are, and which servers you are in (to
show "my servers" and whether you have Manage Server). It never sees messages and keeps no Discord token.

## 3. Vercel

1. **Add New → Project**, import the repo, **Root Directory** = `website`, framework *Other*, no build command.
2. **Settings → Environment Variables** (Production):

| Variable | Value |
|---|---|
| `TURSO_DATABASE_URL` | `libsql://<db>-<org>.turso.io` (same as the bot) |
| `TURSO_AUTH_TOKEN` | the read-only token |
| `TURSO_WRITE_TOKEN` | the read-write token |
| `DISCORD_CLIENT_ID` | from step 2 |
| `DISCORD_CLIENT_SECRET` | from step 2 |
| `OWNER_IDS` | optional — your Discord user ID(s), comma-separated; enables `/#/admin` |
| `SITE_URL` | optional — e.g. `https://cricket.example.com` if you use a custom domain |

3. Deploy, then set `website_url` in the bot's `config.toml` (or `WEBSITE_URL` in `.env`) and restart the bot.
4. In the bot's `config.toml`, `[tournament] web_poll_seconds = 3` is how often the bot looks for website
   requests (0 switches website control off).

`website/.env.example` lists the same variables.

## 4. Check it

Open `https://<your-site>/api/health`:

| It says | Fix |
|---|---|
| `TURSO_… MISSING` | Add the variable, **redeploy** |
| `tables_missing: [...]` | Start the updated bot once with the same database — it creates the tables |
| `database_writes: FAILED` | `TURSO_WRITE_TOKEN` is missing, read-only, or for another database |
| `DISCORD_CLIENT_… MISSING` | Add them; login stays hidden until both are set |
| `bot: last seen … ago` | The bot is not running; website changes wait until it is |
| `login_ready: true`, `bot: online` | Everything works |

Login problems: "Login didn't finish" almost always means the redirect URI in the Developer Portal
does not match `https://<your-site>/api/auth` exactly (check `SITE_URL` if you use several domains).

## 5. Pages

| Address | Who | What |
|---|---|---|
| `/#/` `/#/results` `/#/leaderboard` `/#/match/<id>` `/#/player/<id>` | everyone | Live scores and stats (unchanged) |
| `/#/tournaments` | everyone | Running tournaments, honours board |
| `/#/tournament/<id>` | everyone (members only if `public` is off) | Overview, table, fixtures, bracket, teams, stats |
| `/#/tournament/<id>/manage` | organisers | Run the tournament |
| `/#/dashboard` | logged in | My tournaments, my servers, create |
| `/#/admin` | bot owner (`OWNER_IDS`) | Server whitelist, wallets, economy settings |

The tournament section uses a dark-wood header and its own colours so it is never mistaken for the
live-match pages.

Match pages mark representatives **(R)** and substitutes **(sub for …)**, list the substitutions under each
innings and the players substituted out under the squads, and show CPU players without a profile link.
The tournament **Manage → Settings** form shows the new "Reps & substitutes" settings automatically (the
bot publishes its settings schema). Redeploy the `website` folder to get the new tags; no new environment variable is needed.

## 6. Security notes

* The session cookie is `HttpOnly`, `SameSite=Lax`, `Secure`; only a SHA-256 hash of it is stored. Sessions last 7 days.
* Changes are accepted only from the site's own origin, and every one is re-authorised by the bot
  against the member's real Discord roles and permissions. The owner panel is checked twice: `OWNER_IDS`
  on the site and the bot's own owner list.
* Requests older than 15 minutes are discarded instead of run.

## 7. Local preview

```bash
cd website
TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=... TURSO_WRITE_TOKEN=... \
DISCORD_CLIENT_ID=... DISCORD_CLIENT_SECRET=... node dev-server.js
```
