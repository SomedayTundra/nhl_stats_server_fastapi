# Deployment

Full-system runbook. The client repo (`nhl_stats_client_react`) has a short pointer back here.

## Architecture

| Piece | Where | Deploys on |
|---|---|---|
| React client | **Vercel**, `www.somedaytundra.com` (apex redirects to `www`) | push to client `main` (Vercel GitHub integration); previews per PR |
| FastAPI | **Fly.io** app `nhl-stats-api`, `api.somedaytundra.com` | push to this repo's `main` (`.github/workflows/deploy.yml`) |
| MongoDB | **Atlas M0** (free, AWS us-east-1), database `nhl_stats` | — |
| Farming | GitHub Actions, daily 11:00 UTC (`.github/workflows/farm.yml`) | schedule / manual dispatch |
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
  CORS_ALLOW_ORIGIN_REGEX='^https://nhl-stats-client-react-[a-z0-9-]+-<vercel-team-slug>\.vercel\.app$'
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

**Farming** runs daily. Run it by hand from Actions → Farm standings → Run workflow (optionally
with a `season_id`), or locally against Atlas:
```bash
MONGO_URI='mongodb+srv://...' python -m app.scripts.update_mongodb 20252026
```
When it sees a new team it downloads the logo SVG into `app/logos/`; the workflow then runs
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
