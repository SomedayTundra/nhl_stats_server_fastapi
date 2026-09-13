import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from nhlpy import NHLClient
from nhlpy.http_client import NHLApiException

############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/playoffs", tags=["nhl_playoffs"])

############################
# MONGO DB CLIENT
#
from app.constants import mongo_db_constants as mongo

############################
# NHL API CLIENT
#
nhl_client = NHLClient()


def _season_id_for_playoff_year(year: int) -> int:
    # the NHL API's playoff-bracket endpoint is keyed on the single calendar year the Cup was
    # awarded (e.g. "2024"), while seasonInfo documents are keyed on the two-year seasonId
    # (e.g. 20232024 for the 2023-24 season). Convert so we store/read the same seasonInfo
    # document the rest of the app already uses for that season.
    return (year - 1) * 10000 + year


############################
# ROUTE:  "/api/playoffs/{year}"
#
# year is the single calendar year the playoffs concluded in (e.g. 2024 for the 2023-24 season's
# playoffs), matching the NHL API's own playoff-bracket/{year} endpoint.
#
# Returns the full, unfiltered playoff-bracket payload the NHL API gives us for that year (every
# series, every round, both teams, winner/loser) - see
# https://api-web.nhle.com/v1/playoff-bracket/{year}.
#
# The seasonInfo collection is always checked first; the NHL API is only consulted on a cache
# miss, and the freshly fetched data is then written back to seasonInfo (keyed on the seasonId
# derived from year) as a "playoffs" sub-object.
#
@router.get("/{year}")
async def get_playoffs(year: int) -> dict[str, Any]:
    resolved_season_id = _season_id_for_playoff_year(year)

    db_nhl_stats = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection_season_info = db_nhl_stats[mongo.COLLECTION_SEASON_INFO]

    cached = collection_season_info.find_one({"_id": resolved_season_id})
    if cached is not None and "playoffs" in cached:
        return cached["playoffs"]

    try:
        playoff_data = nhl_client.schedule.playoff_bracket(str(year))
    except NHLApiException as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"NHL API had no playoff data for {year}: {exc.message}",
        )

    # document is named after (its _id) and keyed on the seasonId, same as seasonInfo's
    # startDate/endDate - this just adds a "playoffs" sub-object alongside them
    collection_season_info.update_one(
        {"_id": resolved_season_id},
        {"$set": {"seasonId": resolved_season_id, "playoffs": playoff_data}},
        upsert=True,
    )
    logging.info(f"seasonInfo.playoffs cache miss for {year} (seasonId {resolved_season_id}); stored fresh data")

    return playoff_data
