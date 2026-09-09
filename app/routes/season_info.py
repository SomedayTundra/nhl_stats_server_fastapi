import logging
from datetime import date
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, HTTPException
from nhlpy import NHLClient

from app.schemas import SeasonInfo

############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/season_info", tags=["season_info"])

############################
# MONGO DB CLIENT
#
from app.constants import mongo_db_constants as mongo

############################
# NHL API CLIENT
#
nhl_client = NHLClient()


@lru_cache(maxsize=1)
def _season_standing_manifest():
    # one call to the NHL API returns start/end dates for every season ever; cache it in-process so
    # a run that has to populate many uncached seasons only hits the NHL API once
    return nhl_client.standings.season_standing_manifest()


def _fetch_season_dates_from_nhl(season_id: int) -> tuple[str, str]:
    for season in _season_standing_manifest():
        if season["id"] == season_id:
            return season["standingsStart"], season["standingsEnd"]
    raise HTTPException(
        status_code=404,
        detail=f"seasonId {season_id} not found in the NHL season manifest",
    )


def _current_or_upcoming_season_id(today: Optional[str] = None) -> int:
    # the seasonId to use when the caller doesn't name one: the season currently in progress, or -
    # if we're in the gap between seasons - the next one due to start. ISO date strings compare
    # lexicographically, so plain string comparison is fine here.
    today_str: str = today if today is not None else date.today().isoformat()
    manifest = _season_standing_manifest()

    in_progress_ids: list[int] = []
    soonest_start: Optional[str] = None
    soonest_id: Optional[int] = None

    for season in manifest:
        start = season.get("standingsStart")
        end = season.get("standingsEnd")
        if start is None or end is None:  # narrows start/end to str past this point
            continue
        if start <= today_str <= end:
            in_progress_ids.append(season["id"])
        elif start > today_str and (soonest_start is None or start < soonest_start):
            soonest_start, soonest_id = start, season["id"]

    if in_progress_ids:
        return max(in_progress_ids)
    if soonest_id is not None:
        return soonest_id

    # no season in progress and none scheduled ahead: fall back to the newest season we know of
    return max(manifest, key=lambda s: s["id"])["id"]


############################
# ROUTE:  "/api/season_info?season_id=..."
#
# seasonId is two consecutive years concatenated (e.g. 19421943 == the 1942-43 season).
# season_id is optional; omitted, it resolves to the season currently in progress, or to the
# upcoming season when today's date falls between seasons.
#
# Returns that season's start and end dates, e.g. {"seasonId": 19421943,
# "startDate": "1942-10-31", "endDate": "1943-03-28"}.
#
# The seasonInfo collection is always checked first; the NHL API is only consulted on a cache
# miss, and the freshly fetched dates are then written back to seasonInfo keyed on the seasonId.
#
@router.get("/", response_model=SeasonInfo)
async def get_season_info(season_id: Optional[int] = None):
    # resolve into a plain int up front so everything below works with a non-optional value
    resolved_season_id: int = season_id if season_id is not None else _current_or_upcoming_season_id()

    db_nhl_stats = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection_season_info = db_nhl_stats[mongo.COLLECTION_SEASON_INFO]

    cached = collection_season_info.find_one({"_id": resolved_season_id})
    if cached is not None:
        return SeasonInfo(
            season_id=resolved_season_id,
            start_date=cached["startDate"],
            end_date=cached["endDate"],
        )

    start_date, end_date = _fetch_season_dates_from_nhl(resolved_season_id)

    # document is named after (its _id) and keyed on the seasonId
    collection_season_info.update_one(
        {"_id": resolved_season_id},
        {"$set": {"seasonId": resolved_season_id, "startDate": start_date, "endDate": end_date}},
        upsert=True,
    )
    logging.info(f"seasonInfo cache miss for {resolved_season_id}; stored {start_date} .. {end_date}")

    return SeasonInfo(season_id=resolved_season_id, start_date=start_date, end_date=end_date)
