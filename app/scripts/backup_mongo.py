###################################################
# DUMPS THE nhl_stats MONGODB DATABASE TO A LOCAL GZIPPED ARCHIVE FILE
# via the mongodump CLI (not a pymongo export) so indexes and BSON types round-trip exactly
# through restore_mongo.py.
#
# Run from the repo root as a module; it dumps whatever MONGO_URI points at (local mongod by
# default, or Atlas when MONGO_URI is set to the production URI):
#     python -m app.scripts.backup_mongo
#     python -m app.scripts.backup_mongo --out-dir some/dir
#     python -m app.scripts.backup_mongo --out backups/manual.archive.gz
#
# Requires the `mongodump` binary from the MongoDB Database Tools (not a pip dependency; the api
# image's Dockerfile also installs it). Writes into ./backups (gitignored) by default. This script
# does not upload anywhere itself - see DEPLOYMENT.md.
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

DEFAULT_OUT_DIR = Path("backups")


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

    print(f"Dumping '{mongo.DB_NAME_NHL_STATS}' from {mongo.URI_DISPLAY} -> {out_path} ...")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"mongodump failed (exit code {result.returncode}); no archive to trust at {out_path}.")
        sys.exit(result.returncode)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Done. Wrote {out_path} ({size_mb:.1f} MB).")


if __name__ == "__main__":
    main()
