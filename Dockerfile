# matches the Python the project is developed against (see .venv). Drop to 3.13-slim only if a
# dependency is missing a 3.14 wheel.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# mongodump/mongorestore for app/scripts/backup_mongo.py and restore_mongo.py (see
# DEPLOYMENT.md). Not a pip package - MongoDB publishes these as a standalone tarball. Pinned to
# the debian12 build rather than registering MongoDB's apt repo, since that build keeps working
# via glibc compatibility even if this base image later moves off bookworm; bump
# MONGODB_TOOLS_VERSION deliberately, same as the pins in requirements.txt.
ARG MONGODB_TOOLS_VERSION=100.10.0
ARG TARGETARCH
# libgssapi-krb5-2 is a *runtime* dependency of mongodump/mongorestore themselves (confirmed via
# ldd), not just a build-time need of curl - list it explicitly so apt marks it manually installed
# and `apt-get autoremove` below doesn't sweep it away as an orphaned transitive dep of curl once
# curl is purged.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgssapi-krb5-2 \
    && case "${TARGETARCH:-amd64}" in \
         amd64) TOOLS_ARCH=x86_64 ;; \
         arm64) TOOLS_ARCH=arm64 ;; \
         *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /tmp/mongodb-database-tools.tgz \
         "https://fastdl.mongodb.org/tools/db/mongodb-database-tools-debian12-${TOOLS_ARCH}-${MONGODB_TOOLS_VERSION}.tgz" \
    && tar -xzf /tmp/mongodb-database-tools.tgz -C /tmp \
    && mv /tmp/mongodb-database-tools-*/bin/* /usr/local/bin/ \
    && rm -rf /tmp/mongodb-database-tools* \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# single worker: the on-demand-farm dedupe locks in app/routes/nhl_standings.py are per-process,
# and the routes call synchronous pymongo so extra workers buy little at hobby traffic anyway.
# --ws none: the API has no WebSocket routes, so skip uvicorn's ws backend entirely.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--ws", "none"]
