###################################################
# RESTORES THE nhl_stats MONGODB DATABASE FROM A GZIPPED mongodump ARCHIVE (as produced by
# backup_mongo.py) via the mongorestore CLI. DESTRUCTIVE: drops and replaces every collection in
# the target database - this is how a fresh prod deployment gets seeded, and how a bad backup
# gets rolled back onto.
#
# Run from the repo root as a module; it restores into whatever MONGO_URI points at (local mongod
# by default - set MONGO_URI to the Atlas URI to seed/roll back production):
#     # interactive - prompts for confirmation before touching anything:
#     python -m app.scripts.restore_mongo --in backups/nhl_stats-2026-09-22.archive.gz
#     # non-interactive (first-time deploy seeding, CI) - must pass --yes explicitly:
#     python -m app.scripts.restore_mongo --in backups/nhl_stats-2026-09-22.archive.gz --yes
#
# Requires the `mongorestore` binary from the MongoDB Database Tools (not a pip dependency; the api
# image's Dockerfile also installs it).
###################################################

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.constants import mongo_db_constants as mongo


def parse_args():
    parser = argparse.ArgumentParser(
        description=f"Restore the {mongo.DB_NAME_NHL_STATS} MongoDB database from a mongodump "
        "archive. DESTRUCTIVE: drops and replaces every collection in the target database."
    )
    parser.add_argument(
        "--in",
        dest="in_file",
        type=Path,
        required=True,
        help="Archive file to restore from (as produced by backup_mongo.py).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt. Required when running non-interactively "
        "(first-time deploy seeding, cron, CI) - the script refuses to guess in that case.",
    )
    return parser.parse_args()


def confirm(in_file: Path, skip: bool) -> None:
    if skip:
        return
    if not sys.stdin.isatty():
        print(
            f"Refusing to restore non-interactively without --yes: this DROPS and replaces "
            f"every collection in '{mongo.DB_NAME_NHL_STATS}' at {mongo.URI_DISPLAY} with the contents "
            f"of {in_file}.\nRe-run with --yes once you're sure."
        )
        sys.exit(1)
    answer = input(
        f"This will DROP and replace every collection in '{mongo.DB_NAME_NHL_STATS}' at "
        f"{mongo.URI_DISPLAY} with the contents of {in_file}.\n"
        f"Type the database name ({mongo.DB_NAME_NHL_STATS}) to continue: "
    )
    if answer.strip() != mongo.DB_NAME_NHL_STATS:
        print("Confirmation did not match - aborting, nothing was touched.")
        sys.exit(1)


def main() -> None:
    if shutil.which("mongorestore") is None:
        print(
            "mongorestore not found on PATH. Install the MongoDB Database Tools "
            "(https://www.mongodb.com/try/download/database-tools), or run this inside the api "
            "container, which has it preinstalled."
        )
        sys.exit(1)

    args = parse_args()

    if not args.in_file.exists():
        print(f"Archive not found: {args.in_file}")
        sys.exit(1)

    confirm(args.in_file, args.yes)

    command = [
        "mongorestore",
        f"--uri={mongo.URI}",
        f"--nsInclude={mongo.DB_NAME_NHL_STATS}.*",
        "--gzip",
        f"--archive={args.in_file}",
        "--drop",
    ]

    print(f"Restoring {args.in_file} -> '{mongo.DB_NAME_NHL_STATS}' at {mongo.URI_DISPLAY} (--drop) ...")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"mongorestore failed (exit code {result.returncode}); database may be partially restored.")
        sys.exit(result.returncode)

    db = mongo.client[mongo.DB_NAME_NHL_STATS]
    print("Done. Collection counts:")
    for name in sorted(db.list_collection_names()):
        print(f"  {name}: {db[name].count_documents({})}")


if __name__ == "__main__":
    main()
