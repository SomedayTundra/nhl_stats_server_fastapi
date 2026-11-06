###################################################
# BACKFILLS DARK-BACKGROUND LOGO REFERENCES INTO team_data
# DOCUMENTS FARMED BEFORE update_mongodb.py STARTED
# STORING THEM
#
# For every team entry without a `localLogoDark` field, derives the dark crest's URL from its
# light one (BOS_light.svg -> BOS_dark.svg), downloads it into app/logos if it isn't there yet,
# and stores `teamLogoDark` (the NHL's URL) and `localLogoDark` (our filename, or None when the
# NHL has no dark version of that crest - see app/lib/team_logos.py).
#
# Run from the repo root as a module so `from app.constants ...` resolves:
#     python -m app.scripts.backfill_dark_logos              # every season
#     python -m app.scripts.backfill_dark_logos 19891990     # just one season
#     python -m app.scripts.backfill_dark_logos --dry-run    # report, write nothing
#
# Only touches team entries actually missing `localLogoDark`, so an interrupted run can simply be
# re-run. A crest with no dark version is stored as None, not left missing, so it isn't
# re-checked every run.
#
# The run ends by listing every SVG it newly downloaded into app/logos. If it lists any, run
# `npm run build:logos` and commit app/logos, so they get optimized and rasterized like the rest.
# That list is the only thing to go by: don't decide beforehand that "every crest is already in
# app/logos" and skip the build, since this checkout can lag the farm's `farm/new-logos` PRs.
# A skipped build breaks nothing visibly (the /logo route falls back to the raw SVG), which is
# exactly why it goes unnoticed: the crest just renders scratchy and unevenly sized. The script
# writes to whatever MONGO_URI points at: the local mongod by default, or production when
# MONGO_URI is set to the Atlas URI. The SVGs always land in this checkout, though, so a production
# backfill isn't finished until they're built and committed.
###################################################

import argparse
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

from app.constants import mongo_db_constants as mongo
from app.lib.team_logos import LOGOS_DIR, dark_logo_url, ensure_local_logo, logo_filename


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill dark-background logo references into team_data.")
    parser.add_argument(
        "season_id",
        type=int,
        nargs="?",
        default=None,
        help="Restrict the backfill to a single seasonId (e.g. 19891990). Defaults to every season.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    collection = mongo.client[mongo.DB_NAME_NHL_STATS][mongo.COLLECTION_TEAM_DATA]
    print(f"Backfilling dark logos in {mongo.URI_DISPLAY}{' (dry run)' if args.dry_run else ''}")

    query: dict[str, Any] = {"teams": {"$elemMatch": {"localLogoDark": {"$exists": False}}}}
    if args.season_id is not None:
        query["seasonId"] = args.season_id

    # one result per distinct crest, so a logo shared by many seasons is fetched only once
    resolved: dict[str, tuple[str | None, str | None]] = {}
    # dark SVGs that weren't in app/logos before this run (or, in a dry run, would be downloaded)
    downloaded: list[str] = []
    seasons = teams_updated = found = missing = 0

    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "nhl-stats-server-backfill"}) as client:
        for document in collection.find(query, {"seasonId": 1, "teams": 1}).sort("seasonId", 1):
            changed = False
            for team in document["teams"]:
                if "localLogoDark" in team:
                    continue
                light_url = team["teamLogo"]
                if light_url not in resolved:
                    url = dark_logo_url(light_url)
                    local = None
                    if url:
                        already_on_disk = (LOGOS_DIR / logo_filename(url)).is_file()
                        if args.dry_run:
                            if already_on_disk or client.head(url).status_code == 200:
                                local = logo_filename(url)
                        else:
                            local = ensure_local_logo(url, client)
                        if local and not already_on_disk:
                            downloaded.append(local)
                    resolved[light_url] = (url if local else None, local)
                team["teamLogoDark"], team["localLogoDark"] = resolved[light_url]
                teams_updated += 1
                if team["localLogoDark"]:
                    found += 1
                else:
                    missing += 1
                changed = True

            if changed:
                seasons += 1
                if not args.dry_run:
                    collection.update_one({"_id": document["_id"]}, {"$set": {"teams": document["teams"]}})
                print(f"  {document['seasonId']}: done")

    crests_found = sum(1 for _, local in resolved.values() if local)
    print()
    print(
        f"{'Would update' if args.dry_run else 'Updated'} {teams_updated} team entr(ies) across {seasons} season(s): "
        f"{found} with a dark logo, {missing} without (light fallback). "
        f"{len(resolved)} distinct crest(s), {crests_found} with a dark version."
    )
    print()
    if downloaded:
        print(f"{'Would download' if args.dry_run else 'Downloaded'} {len(downloaded)} new SVG(s) into app/logos:")
        for name in sorted(downloaded):
            print(f"  {name}")
        if not args.dry_run:
            print(
                "NEXT STEP: run `npm run build:logos`, then commit app/logos. Until then /logo serves these as raw "
                "SVGs (scratchy, unevenly sized), and production won't have them at all."
            )
    else:
        print(
            f"No new SVGs {'would be ' if args.dry_run else ''}downloaded: every dark crest "
            f"{'this run needs is' if args.dry_run else 'it used was'} already in app/logos, "
            "so there's nothing new for `npm run build:logos`."
        )


if __name__ == "__main__":
    main()
