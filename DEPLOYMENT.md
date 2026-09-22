# Deployment

Full-system runbook. The client repo (`nhl_stats_client_react`) has a short pointer back here.

## Architecture

| Piece | Where | Notes |
|---|---|---|
| React client | S3 (private) + CloudFront + ACM, `somedaytundra.com` + `www` | static build, no server |
| FastAPI + MongoDB + Caddy | one Lightsail 2 GB instance, `api.somedaytundra.com` | `docker compose` stack in this repo |
| DNS / TLS | Route 53 hosted zone (already exists); Caddy gets the API cert, ACM the client cert | |

Incremental cost is essentially the Lightsail instance (~$12/mo).

## What lives in this repo now

- `Dockerfile`, `.dockerignore` — API image (Python 3.14, `uvicorn main:app`, single worker).
- `docker-compose.yml` — `mongo` (private, named volume) + `api` + `caddy` (80/443, auto-HTTPS).
  `api` bind-mounts `./backups` on the host (gitignored) for `app/scripts/backup_mongo.py` /
  `restore_mongo.py` archives.
- `Caddyfile` — reverse proxy for `api.somedaytundra.com`.
- `requirements.txt` — pinned runtime deps.
- `.env.example` — every environment variable the app reads.
- `.github/workflows/deploy.yml` — SSH redeploy on push to `main` (gated by the `DEPLOY_ENABLED` repo variable).

## Environment variables (see `.env.example`)

| Var | Purpose |
|---|---|
| `MONGO_URI` | Mongo connection string. Compose sets `mongodb://mongo:27017/`. |
| `CORS_ALLOW_ORIGINS` | Comma-separated allowed browser origins. Prod: `https://somedaytundra.com,https://www.somedaytundra.com`. |
| `ENABLE_ONDEMAND_FARMING` | `false` in prod. When `true`, an uncached finished-season request shells out to the farm script. |
| `HOST` / `PORT` | Only used by `python main.py`; the container overrides on the CMD line. |

## First-time setup

### 1. Lightsail instance
- Ubuntu 22.04, 2 GB plan, attach a **static IP**.
- Firewall: allow TCP 22, 80, 443 only (never expose 27017).
- Install Docker Engine + compose plugin. Create a deploy user with an SSH key for CI.

### 2. DNS
- Route 53 → `somedaytundra.com` zone → **A record `api.somedaytundra.com` → static IP**.
- Client records (apex + `www`) are added in step 5.

### 3. Bring up the API
```bash
git clone https://github.com/SomedayTundra/nhl_stats_server_fastapi.git ~/nhl_stats_server_fastapi
cd ~/nhl_stats_server_fastapi
cp .env.example .env          # set CORS_ALLOW_ORIGINS; MONGO_URI stays mongodb://mongo:27017/
docker compose up -d --build
docker compose logs -f caddy  # wait for the Let's Encrypt cert
curl https://api.somedaytundra.com/health   # -> {"status":"ok"}
```

### 4. Load the database
`update_mongodb.py` is run by hand to farm historical data; the DB is pre-loaded so the live
site never needs to farm. Seed it from a local dump using `app/scripts/backup_mongo.py` /
`restore_mongo.py` (wrap `mongodump`/`mongorestore`, installed in the api image alongside each
other via the MongoDB Database Tools - see the Dockerfile).

```bash
# on your dev machine, against local Mongo:
docker compose exec -T api python -m app.scripts.backup_mongo --out-dir /backups
scp ./backups/nhl_stats-<date>.archive.gz <user>@<ip>:~/nhl_stats_server_fastapi/backups/

# on the box, once `docker compose up -d --build` has brought up the api container:
docker compose exec -T api python -m app.scripts.restore_mongo \
  --in /backups/nhl_stats-<date>.archive.gz --yes
```

`--yes` is required here because this step runs non-interactively; drop it (and run without `-T`)
to get an interactive confirmation prompt instead. Either way `restore_mongo.py` prints
per-collection document counts once it's done, as the sanity check.

### 5. Client hosting (in AWS console / CLI)
- **S3 bucket** `somedaytundra.com`, Block Public Access ON (served only via CloudFront OAC).
- **ACM cert** in **us-east-1** for `somedaytundra.com` + `www.somedaytundra.com`, DNS-validated via Route 53.
- **CloudFront distribution**: S3 origin via OAC; default root object `index.html`; HTTP→HTTPS;
  compress; **custom error responses** `403 → /index.html (200)` and `404 → /index.html (200)`
  (SPA fallback for the TanStack Router clean URLs); alternate domain names + the ACM cert.
- **Route 53**: A + AAAA alias records for apex and `www` → the distribution.

### 6. First client publish
From the client repo: `npm ci && npm run build` (bakes in `.env.production`), then
`aws s3 sync dist/ s3://somedaytundra.com --delete` and a CloudFront `/*` invalidation.

### 7. Turn on CI
- Client repo: OIDC IAM role + repo variables `DEPLOY_ENABLED`, `S3_BUCKET`,
  `CLOUDFRONT_DISTRIBUTION_ID`, `VITE_API_BASE_URL`; secret `AWS_ROLE_ARN`.
- Server repo: repo variable `DEPLOY_ENABLED`; secrets `LIGHTSAIL_HOST`, `LIGHTSAIL_USER`,
  `LIGHTSAIL_SSH_KEY`.
- Each workflow's header comment lists these too.

## Ongoing tasks

**Farm new data (by hand):**
```bash
cd ~/nhl_stats_server_fastapi
docker compose exec api python -m app.scripts.update_mongodb            # current season
docker compose exec api python -m app.scripts.update_mongodb 20242025   # a specific season
```
Newly downloaded logo SVGs land in `app/logos/` on the host (bind-mounted) — commit them.

**Backups:**
```bash
docker compose exec -T api python -m app.scripts.backup_mongo --out-dir /backups
```
Writes `/backups/nhl_stats-<UTC date>.archive.gz` inside the api container, which
docker-compose.yml bind-mounts to `./backups/` on the host. Wire this into a cron on the box, and
add an upload step if the archive needs to leave the host too, e.g.:
```bash
cd ~/nhl_stats_server_fastapi && \
  docker compose exec -T api python -m app.scripts.backup_mongo --out-dir /backups && \
  aws s3 cp "backups/nhl_stats-$(date -u +%F).archive.gz" s3://<backup-bucket>/
```

## Known follow-ups (not blockers)

- Client JS is one ~1.1 MB bundle; `build.rollupOptions.output.manualChunks` would speed first load.
- Routes call synchronous `pymongo` inside `async def` — fine at hobby traffic with one worker.
- `/api/nhl_standings` rewrites the single `user_data` doc on every call — harmless for one user.
