###################################################
# TAGS EACH seasonInfo DOCUMENT WITH l10OtAndTieOverlap: a season
# where some team's last-10 window has ever had both a non-zero OT
# loss AND a non-zero tie at once (only possible 1999-2000 through
# 2003-04, the seasons where both existed).
#
# The client uses this to decide whether to always show all four L10
# numbers for a season (rather than the normal three, dropping
# whichever of OT losses/ties is zero) - a per-row decision would flip
# a team between three and four numbers as its own last-10 window
# happens to include an OT loss/tie or not, which reads as
# inconsistent within a single season's table.
#
# This is a one-time computation over already-farmed data, not part of
# the regular farm/backfill flow: every season that will ever have
# ties is long over, so the answer for a given seasonId never changes
# once computed. Re-run is still safe (and cheap - a single
# aggregation query) if more historical seasons ever get farmed.
#
# Run from the repo root as a module:
#     python -m app.scripts.tag_l10_overlap_seasons
###################################################

from dotenv import load_dotenv

load_dotenv()

from app.constants import mongo_db_constants as mongo


def main() -> None:
    db = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection_team_standings = db[mongo.COLLECTION_TEAM_STANDINGS]
    collection_season_info = db[mongo.COLLECTION_SEASON_INFO]

    pipeline = [
        {"$unwind": "$team_info"},
        {
            "$match": {
                "team_info.l10_ot_losses": {"$gt": 0},
                "team_info.l10_ties": {"$gt": 0},
            }
        },
        {"$group": {"_id": "$seasonId"}},
    ]
    overlap_season_ids = {doc["_id"] for doc in collection_team_standings.aggregate(pipeline)}
    print(f"Seasons with an L10 OT-loss/tie overlap: {sorted(overlap_season_ids)}")

    farmed_season_ids = set(collection_team_standings.distinct("seasonId"))
    tagged_true = tagged_false = 0
    for season_id in sorted(farmed_season_ids):
        overlaps = season_id in overlap_season_ids
        collection_season_info.update_one(
            {"_id": season_id}, {"$set": {"l10OtAndTieOverlap": overlaps}}
        )
        if overlaps:
            tagged_true += 1
        else:
            tagged_false += 1

    print(f"Tagged {tagged_true + tagged_false} season(s): {tagged_true} True, {tagged_false} False.")


if __name__ == "__main__":
    main()
