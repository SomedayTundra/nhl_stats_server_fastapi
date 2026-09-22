###################################################
# DUMPS THE nhl_stats MONGODB DATABASE TO A LOCAL GZIPPED ARCHIVE FILE
# via the mongodump CLI (not a pymongo export) so indexes and BSON types round-trip exactly
# through restore_mongo.py.
#
# Run from the repo root, inside the api container, as a module:
#     docker compose exec -T api python -m app.scripts.backup_mongo
#     docker compose exec -T api python -m app.scripts.backup_mongo --out-dir /backups
#     docker compose exec -T api python -m app.scripts.backup_mongo --out /backups/manual.archive.gz
#
# Requires the `mongodump` binary (installed in the api image's Dockerfile via the MongoDB
# Database Tools tarball - not a pip dependency). Writes into /backups by default, which
# docker-compose.yml bind-mounts to ./backups on the host, so the archive survives container
# restarts/rebuilds and is reachable for scp/S3 upload from the host afterward. This script does
# not upload anywhere itself - see DEPLOYMENT.md for the manual/cron hand-off.
###################################################

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.constants import mongo_db_constants as mongo

DEFAULT_OUT_DIR = Path("/backups")


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"Dump the {mongo.DB_NAME_NHL_STATS} MongoDB database to a gzipped mongodump archive."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Exact output file path. Defaults to "
        f"{DEFAULT_OUT_DIR}/{mongo.DB_NAME_NHL_STATS}-<UTC date>.archive.gz.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directory for the default-named archive file (default: {DEFAULT_OUT_DIR}). "
        "Ignored if --out is given.",
    )
    return parser.parse_args()


def main() -> None:
    if shutil.which("mongodump") is None:
        print(
            "mongodump not found on PATH. Install the MongoDB Database Tools "
            "(https://www.mongodb.com/try/download/database-tools), or run this inside the api "
            "container, which has it preinstalled."
        )
        sys.exit(1)

    args = parse_args()

    out_path = args.out
    if out_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = args.out_dir / f"{mongo.DB_NAME_NHL_STATS}-{stamp}.archive.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "mongodump",
        f"--uri={mongo.URI}",
        f"--db={mongo.DB_NAME_NHL_STATS}",
        "--gzip",
        f"--archive={out_path}",
    ]

    print(f"Dumping '{mongo.DB_NAME_NHL_STATS}' from {mongo.URI} -> {out_path} ...")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"mongodump failed (exit code {result.returncode}); no archive to trust at {out_path}.")
        sys.exit(result.returncode)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Done. Wrote {out_path} ({size_mb:.1f} MB).")
    print("Copy it off the box, e.g.:")
    print(f"  scp <user>@<host>:~/nhl_stats_server_fastapi/backups/{out_path.name} .")
    print(f"  aws s3 cp backups/{out_path.name} s3://<backup-bucket>/{out_path.name}")


if __name__ == "__main__":
    main()
