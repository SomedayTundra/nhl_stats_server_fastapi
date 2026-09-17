###################################################
# BACKFILLS THE LAST-10 TALLIES INTO team_standings DOCUMENTS
# THAT WERE FARMED BEFORE update_mongodb.py STARTED
# CAPTURING THEM
#
# Run from the repo root as a module so `from app.constants ...` resolves:
#     python -m app.scripts.backfill_last_ten              # every day missing any l10 field
#     python -m app.scripts.backfill_last_ten 19891990     # just one season
#
# Only touches documents actually missing one of the fields, so an interrupted run can simply be
# re-run and picks up where it left off. Adding an entry to L10_FIELDS below is all it takes to
# backfill a newly-captured tally: days that already have the others are selected again because
# they're missing the new one.
###################################################


import argparse
import asyncio
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

from app.constants import mongo_db_constants as mongo

NHL_STANDINGS_URL = "https://api-web.nhle.com/v1/standings/{date}"

# our team_info field name -> the NHL API's own key for it. Keep this in step with the l10_* keys
# update_mongodb.py writes, so a day farmed fresh and a day backfilled end up the same shape
L10_FIELDS = {
    "l10_wins": "l10Wins",
    "l10_losses": "l10Losses",
    "l10_ot_losses": "l10OtLosses",
    "l10_ties": "l10Ties",
    "l10_goals_for": "l10GoalsFor",
    "l10_goals_against": "l10GoalsAgainst",
    "l10_goal_diff": "l10GoalDifferential",
}

# the NHL API is the only rate limit that matters here; a handful of connections keeps a full
# 14k-day backfill to a few minutes without hammering it
CONCURRENCY = 6


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill last-10 records into already-farmed team_standings days."
    )
    parser.add_argument(
        "season_id",
        type=int,
        nargs="?",
        default=None,
        help="Restrict the backfill to a single seasonId (e.g. 19891990). Defaults to every "
        "season with days still missing the fields.",
    )
    return parser.parse_args()


def days_needing_backfill(collection, season_id: int | None) -> list[dict[str, Any]]:
    # `team_info.<field>: {$exists: False}` matches a document where *no* element of the array has
    # that field, which is exactly the pre-backfill shape - a day we've already done has it on
    # every team, so it drops out of the query and a re-run skips it. The $or means a day that
    # predates a newly-added field is picked up again even though it has all the older ones
    query: dict[str, Any] = {
        "$or": [{f"team_info.{field}": {"$exists": False}} for field in L10_FIELDS]
    }
    if season_id is not None:
        query["seasonId"] = season_id
    return list(collection.find(query, {"_id": 1, "date": 1, "seasonId": 1}).sort("date", 1))


async def fetch_last_ten_by_abbrev(client: httpx.AsyncClient, target_date: str) -> dict[str, dict[str, int]]:
    response = await client.get(NHL_STANDINGS_URL.format(date=target_date))
    response.raise_for_status()
    standings = response.json().get("standings", [])
    return {
        team["teamAbbrev"]["default"]: {
            field: team[api_key] for field, api_key in L10_FIELDS.items()
        }
        for team in standings
    }


async def backfill_day(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    collection,
    day: dict[str, Any],
) -> tuple[str, str]:
    target_date = day["date"]
    async with semaphore:
        try:
            last_ten = await fetch_last_ten_by_abbrev(client, target_date)
        except Exception as exc:
            return target_date, f"FAILED ({exc})"

    if not last_ten:
        return target_date, "skipped (NHL API has no standings for this day)"

    # re-read the full document now rather than in days_needing_backfill: holding 14k complete
    # documents in memory while the fetches run is pointless when we only need one at a time
    document = collection.find_one({"_id": day["_id"]}, {"team_info": 1})
    if document is None:
        return target_date, "skipped (document vanished mid-run)"

    team_info = document["team_info"]
    missing_teams = []
    for entry in team_info:
        abbrev = entry["abbrev"]["default"]
        stats = last_ten.get(abbrev)
        if stats is None:
            missing_teams.append(abbrev)
            continue
        entry.update(stats)

    if missing_teams:
        # a stored team the NHL API's own payload for that same day doesn't list means the two
        # disagree about who played that season - worth seeing rather than silently half-filling
        return target_date, f"FAILED (no NHL API entry for {', '.join(missing_teams)})"

    collection.update_one({"_id": day["_id"]}, {"$set": {"team_info": team_info}})
    return target_date, f"done ({len(team_info)} teams)"


async def main() -> None:
    args = parse_args()
    collection = mongo.client[mongo.DB_NAME_NHL_STATS][mongo.COLLECTION_TEAM_STANDINGS]

    days = days_needing_backfill(collection, args.season_id)
    if not days:
        print("Nothing to backfill - every cached day already has its last-10 record.")
        return

    print(f"Backfilling last-10 records for {len(days)} day(s)...")

    semaphore = asyncio.Semaphore(CONCURRENCY)
    failures = []
    completed = 0
    async with httpx.AsyncClient(
        timeout=30, headers={"User-Agent": "nhl-stats-server-backfill"}
    ) as client:
        tasks = [
            asyncio.create_task(backfill_day(client, semaphore, collection, day))
            for day in days
        ]
        for task in asyncio.as_completed(tasks):
            target_date, outcome = await task
            completed += 1
            if outcome.startswith("FAILED"):
                failures.append((target_date, outcome))
                print(f"  [{completed}/{len(days)}] {target_date} {outcome}")
            elif completed % 250 == 0 or completed == len(days):
                print(f"  [{completed}/{len(days)}] ...{target_date} {outcome}")

    print()
    print(f"Backfilled {completed - len(failures)} day(s); {len(failures)} failure(s).")
    if failures:
        print("Re-run the script to retry the failures - completed days are skipped automatically.")


if __name__ == "__main__":
    asyncio.run(main())
