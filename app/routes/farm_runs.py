from datetime import timezone

from fastapi import APIRouter

from app.schemas import FarmRun, FarmRuns

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/farm_runs", tags=["farm_runs"])

############################
# MONGO DB CLIENT
#
from app.constants import mongo_db_constants as mongo

# never sent to clients: the machine name and OS login of whoever ran the farm (see FarmRun)
_PRIVATE_FIELDS = {"_id": 0, "host": 0, "os_user": 0}


def _public_status(status):
    # an error status is "error: <ExceptionType>: <message>"; keep only the type, since the message
    # can carry hostnames, URIs or other connection details
    if isinstance(status, str) and status.startswith("error: "):
        return "error: " + status[len("error: "):].split(":", 1)[0]
    return status


def _as_utc(value):
    # pymongo hands back naive datetimes that are UTC; tag them so the JSON carries the offset
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


############################
# ROUTE:  "/api/farm_runs/"
#
@router.get("/", response_model=FarmRuns)
def get_farm_runs() -> FarmRuns:
    """The most recent update_mongodb.py runs (at most FARM_RUNS_TO_KEEP), newest first."""
    collection = mongo.client[mongo.DB_NAME_NHL_STATS][mongo.COLLECTION_FARM_RUNS]
    docs = (
        collection.find({}, _PRIVATE_FIELDS)
        .sort([("started_at", -1), ("_id", -1)])
        .limit(mongo.FARM_RUNS_TO_KEEP)
    )
    runs = []
    for doc in docs:
        doc["started_at"] = _as_utc(doc.get("started_at"))
        doc["ended_at"] = _as_utc(doc.get("ended_at"))
        doc["status"] = _public_status(doc.get("status"))
        runs.append(FarmRun.model_validate(doc))
    return FarmRuns(farm_runs_to_keep=mongo.FARM_RUNS_TO_KEEP, runs=runs)
