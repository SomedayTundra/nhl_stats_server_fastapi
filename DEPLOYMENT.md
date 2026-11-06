# Deployment

Full-system runbook. The client repo (`nhl_stats_client_react`) has a short pointer back here.

## Architecture

| Piece | Where | Deploys on |
|---|---|---|
| React client | **Vercel**, `www.somedaytundra.com` (apex redirects to `www`) | push to client `main` (Vercel GitHub integration); previews per PR |
| FastAPI | **Fly.io** app `nhl-stats-api`, `api.somedaytundra.com` | push to this repo's `main` (`.github/workflows/deploy.yml`) |
| MongoDB | **Atlas M0** (free, AWS us-east-1), database `nhl_stats` | — |
| Farming | GitHub Actions (`.github/workflows/farm.yml`), dispatched daily ~11:00 UTC by a Vercel Cron Job in the client repo (`api/trigger-farm.ts`); GitHub `schedule` at 14:37 UTC as a fallback | Vercel Cron / schedule / manual dispatch |
| DNS | Route 53 zone `somedaytundra.com` (domain registered at AWS) | — |

Cost: Vercel Hobby $0, Atlas M0 $0, Fly ~$3–4/mo (one always-on shared-cpu-1x 512 MB machine),
Route 53 $0.50/mo + domain renewal. The database is ~96 MB uncompressed and grows ~1.3 MB/season,
well under M0's 512 MB.

## What lives in this repo

- `Dockerfile`, `.dockerignore` — API image (Python 3.14, `uvicorn main:app`, single worker, port 8000).
- `fly.toml` — Fly app config: region `iad`, always one machine, `/health` check gating rollouts.
- `.github/workflows/deploy.yml` — `flyctl deploy --remote-only` on push to `main` (gated by `DEPLOY_ENABLED`).
- `.github/workflows/farm.yml` — daily `update_mongodb` against Atlas; opens a PR if new logos appear.
- `.env.example` — every environment variable the app reads.

## Environment variables

| Var | Where it's set | Purpose |
|---|---|---|
| `MONGO_URI` | Fly secret; GitHub secret (farm job) | Atlas `mongodb+srv://` URI. The DB name is always `nhl_stats`, regardless of the URI path. |
| `CORS_ALLOW_ORIGINS` | Fly secret | `https://www.somedaytundra.com,https://somedaytundra.com` |
| `CORS_ALLOW_ORIGIN_REGEX` | Fly secret | Lets the client's Vercel previews call the API: `^https://nhl-stats-client-react-[a-z0-9-]+-<vercel-team-slug>\.vercel\.app$` |
| `ENABLE_ONDEMAND_FARMING` | `fly.toml` `[env]` | `false` — the farm job keeps the DB current instead. |
| `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` | Fly secrets | Read-only proxy behind `/api/jira` for the client's `/jira` page. Use a scoped token (`read:jira-work`, `read:jira-user`) with `https://api.atlassian.com/ex/jira/<cloudId>`. Unset → those routes answer 503. |
| `JIRA_PROJECT_KEY` | `fly.toml` `[env]` (optional) | The one space the proxy exposes; defaults to `NHL`. |
| `HOST` / `PORT` | local only | Used by `python main.py`; the container's CMD pins 8000. |

## First-time setup (in order)

### 1. Route 53 inventory
Note the records in the `somedaytundra.com` hosted zone. Keep MX/TXT (mail, verification); any
existing apex/`www`/`api` records get replaced below. Delete any leftovers from the old AWS plan
(S3 bucket, CloudFront distribution, ACM cert, GitHub OIDC IAM role) if they were ever created.

### 2. MongoDB Atlas
- Create an **M0** cluster on **AWS us-east-1** (next to Fly's `iad`).
- Database Access: user `nhl_api`, role `readWrite` on `nhl_stats` only, long generated password.
- Network Access: `0.0.0.0/0`. Fly machines and GitHub runners have no fixed egress IPs, so the
  credentials are the control (Fly static egress IPs can tighten this later).
- Connect → Drivers → copy the `mongodb+srv://nhl_api:<password>@...` URI.

### 3. Seed Atlas from the local database
Needs the MongoDB Database Tools (`mongodump`/`mongorestore`) on PATH.
```bash
# dump local Mongo -> backups/nhl_stats-<UTC date>.archive.gz
python -m app.scripts.backup_mongo

# restore into Atlas (DROPS and replaces nhl_stats there)
MONGO_URI='mongodb+srv://nhl_api:...' python -m app.scripts.restore_mongo \
  --in backups/nhl_stats-<date>.archive.gz --yes
```
(PowerShell: `$env:MONGO_URI='...'; python -m app.scripts.restore_mongo ...`, then
`Remove-Item Env:MONGO_URI`.) The restore prints per-collection counts — expect `team_standings`
≈ 14.5k, `seasonInfo` ≈ 85, `team_data` ≈ 83.

### 4. Fly.io
```bash
fly auth signup            # or: fly auth login
fly launch --no-deploy --copy-config   # keep the committed fly.toml; pick a new app name if taken
fly secrets set MONGO_URI='mongodb+srv://...' \
  CORS_ALLOW_ORIGINS='https://www.somedaytundra.com,https://somedaytundra.com' \
  CORS_ALLOW_ORIGIN_REGEX='^https://nhl-stats-client-react-[a-z0-9-]+-<vercel-team-slug>\.vercel\.app$' \
  JIRA_BASE_URL='https://api.atlassian.com/ex/jira/<cloudId>' \
  JIRA_EMAIL='<your Atlassian login email>' \
  JIRA_API_TOKEN='<scoped token: read:jira-work, read:jira-user>'
fly deploy
curl https://nhl-stats-api.fly.dev/health          # -> {"status":"ok"}
```
If the app name changes, update `app =` in `fly.toml` and the `-a` in the token command below.

### 5. API domain
```bash
fly certs add api.somedaytundra.com
```
Route 53: `CNAME api → nhl-stats-api.fly.dev` (plus the `_acme-challenge` CNAME if `fly certs add`
asks for one). `fly certs show api.somedaytundra.com` should reach **Issued** within minutes.

### 6. Vercel (client)
- New Project → import `SomedayTundra/nhl_stats_client_react`. Framework preset Vite; defaults are
  right (`npm run build`, output `dist`). No env vars needed — `.env.production` supplies the API URL.
- Settings → Domains: add `www.somedaytundra.com` (primary) and `somedaytundra.com` (redirect to www).
- Route 53: `CNAME www → cname.vercel-dns.com` and apex `A → 76.76.21.21` — use whatever values the
  Vercel domain screen shows if they differ. Vercel issues the certs.
- Note the preview hostname pattern (Deployments → any preview) and make sure the
  `CORS_ALLOW_ORIGIN_REGEX` secret matches it.

### 7. Turn on CI/CD (this repo's GitHub settings)
- Secret `FLY_API_TOKEN` = `fly tokens create deploy -a nhl-stats-api`
- Secret `MONGO_URI` = the Atlas URI (farm job)
- Variable `DEPLOY_ENABLED` = `true`
- Settings → Actions → General → allow GitHub Actions to create and approve pull requests
- Remove the old `LIGHTSAIL_*` secrets if any were set (and `AWS_ROLE_ARN`, `S3_BUCKET`,
  `CLOUDFRONT_DISTRIBUTION_ID` in the client repo).

## Ongoing

**Deploys** are automatic: merge to `main`. A build that fails the `/health` check never replaces
the running machine. Roll back with `fly releases` + `fly deploy --image <previous image>`.

**Farming** runs daily. The client project's Vercel Cron Job calls `workflow_dispatch` on
`farm.yml` at ~11:00 UTC (GitHub's own `schedule` trigger ran hours late, so it's now only a
14:37 UTC fallback; the second run is a no-op). That needs two Vercel env vars, documented in the
client repo's `DEPLOYMENT.md`. Run it by hand from Actions → Farm standings → Run workflow (optionally
with a `season_id`), or locally against Atlas:
```bash
MONGO_URI='mongodb+srv://...' python -m app.scripts.update_mongodb 20252026 --triggered-by "my laptop"
```
Every run, wherever it ran, inserts a document into the `farm_runs` collection: start/end time,
duration, status (`success` or the error), `trigger` (`scheduled`, `dispatch` or `manual`), the
optional `triggered_by` note (`vercel-cron (...)` for the cron), host, OS user, and in Actions
the actor and run URL. It also appends the same thing as one line to
`app/scripts/update_mongo.log` on the machine that ran it (gitignored; useful for local runs, gone
with the runner in Actions).
When it sees a new team it downloads the logo SVG into `app/logos/`, along with the NHL's
dark-background version of it (`..._dark.svg`, stored as `teamLogoDark`/`localLogoDark` on the
team's `team_data` entry, with `localLogoDark: None` for the few historical crests that have no
dark version; see `app/lib/team_logos.py`). Seasons farmed before that are filled in by
`python -m app.scripts.backfill_dark_logos` (resumable, writes to whatever `MONGO_URI` points at).
The backfill ends by listing the SVGs it newly downloaded. If it lists any, run
`npm run build:logos` and commit `app/logos`. Go by that list, not a guess made beforehand that
"every crest should already be on disk". A skipped build fails silently: `/logo` falls back to the
raw SVG, which renders scratchy and unevenly sized. The SVGs land in your checkout even when
`MONGO_URI` is production, so a production backfill isn't shipped until they're built and
committed.
Adding a team also recolors its season's chart lines, including `chartLineColorDark`, the line
color for the dark page theme. It's stored only for teams whose light color is too dark to read on
that page or looks noticeably different on the dark crest; see `app/lib/chart_line_color.py`. Run
`python -m app.scripts.backfill_chart_line_color` after `backfill_dark_logos` for seasons farmed
before that. It recomputes every season and is safe to re-run.
A dark crest the NHL draws as an outline around a see-through middle needs the middle filled by
hand, as was done for both Tampa Bay crests (an ellipse behind the artwork: white on the light
crest, team navy on the dark one). Otherwise the middle shows whatever is behind the logo, and
`build-logos.mjs`, which sizes crests by how much of them is opaque, blows the crest up.
The workflow then runs
`npm run build:logos` and opens a `farm/new-logos` PR. Merge it to ship the logos. (Run locally,
do the same by hand: `npm install && npm run build:logos`, commit.) GitHub pauses scheduled
workflows after 60 days of repo inactivity — re-enable from the Actions tab if so.

**Backups:** Atlas M0 has no automatic backups. Periodically:
```bash
MONGO_URI='mongodb+srv://...' python -m app.scripts.backup_mongo
```
and keep the archive somewhere off your machine.

**Logs:** `fly logs -a nhl-stats-api`.

## Known follow-ups (not blockers)

- Client JS is one ~1.1 MB bundle; `build.rollupOptions.output.manualChunks` would speed first load.
- Routes call synchronous `pymongo` inside `async def` — fine at hobby traffic with one worker.
- `/api/nhl_standings` rewrites the single `user_data` doc on every call — harmless for one user.
