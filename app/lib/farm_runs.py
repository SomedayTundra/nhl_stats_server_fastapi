###################################################
# THE farm_runs COLLECTION'S SIZE CAP
#
# update_mongodb.py inserts one farm_runs document per run, so without a cap the collection only
# ever grows. prune_farm_runs() keeps the newest `keep` runs (by started_at) and deletes the rest;
# update_mongodb.py calls it right after recording each run.
###################################################

from pymongo.collection import Collection


def prune_farm_runs(collection: Collection, keep: int) -> int:
    """Delete all but the `keep` most recently started runs; returns how many were deleted."""
    stale_ids = [
        doc["_id"]
        for doc in collection.find({}, {"_id": 1}).sort([("started_at", -1), ("_id", -1)]).skip(keep)
    ]
    if not stale_ids:
        return 0
    return collection.delete_many({"_id": {"$in": stale_ids}}).deleted_count
