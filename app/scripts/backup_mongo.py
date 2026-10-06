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
# image's Dockerfile also installs it). Writes into ./backups (gitignored) by default, and refuses
# to overwrite an existing archive - a second backup on the same UTC day needs its own --out. This
# script does not upload anywhere itself - see DEPLOYMENT.md.
###################################################

import argparse
import os
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

    # never overwrite an existing backup: mongodump would silently truncate it
    if out_path.exists():
        print(f"{out_path} already exists; refusing to overwrite it. Pass --out to pick another name.")
        sys.exit(1)

    # mongodump writes to a .partial file that is renamed into place only once it succeeds, so a
    # crashed or failed dump never leaves a plausible-looking archive behind. Creating it with
    # O_EXCL also makes it a lock: two runs that land on the same name at once (which interleaved
    # both dumps into one corrupt archive on 2026-10-06) can't both get it, so the second bails.
    partial_path = out_path.with_name(out_path.name + ".partial")
    try:
        os.close(os.open(partial_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        print(
            f"{partial_path} already exists: another backup to this file is running, or one crashed "
            f"partway. If nothing else is running, delete it and try again."
        )
        sys.exit(1)

    command = [
        "mongodump",
        f"--uri={mongo.URI}",
        f"--db={mongo.DB_NAME_NHL_STATS}",
        "--gzip",
        f"--archive={partial_path}",
    ]

    print(f"Dumping '{mongo.DB_NAME_NHL_STATS}' from {mongo.URI_DISPLAY} -> {out_path} ...")
    try:
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f"mongodump failed (exit code {result.returncode}); no archive written.")
            sys.exit(result.returncode)
        # unlike os.replace, rename refuses to clobber a file that appeared at out_path meanwhile
        # (on Windows; POSIX rename would overwrite, but the .partial lock already rules that out)
        partial_path.rename(out_path)
    finally:
        partial_path.unlink(missing_ok=True)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Done. Wrote {out_path} ({size_mb:.1f} MB).")


if __name__ == "__main__":
    main()
