import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.schemas import TeamInfo
from pymongo import MongoClient
from pathlib import Path


############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/nhl_team_info", tags=["nhl_team_info"])

############################
# MONGO DB CLIENT
#
MONGO_URI_LOCALHOST = "mongodb://localhost:27017/"
MONGO_URI = MONGO_URI_LOCALHOST

MONGO_DB_NAME = "nhl_stats"
MONGO_COLLECTION_TEAM_DATA = "team_data"

mongo_client = MongoClient(MONGO_URI)
try:
    # connect to MongoDB
    logging.info(f"Attempting to connect to: {MONGO_URI}")
    mongo_client.admin.command("ping")
    logging.info(f"Connected successfully [{mongo_client.address}]")
except Exception as e:
    raise Exception("  The following error occurred: ", e)

############################
# MISC
LOGOS_DIR = "logos"

############################
# ROUTE:  "/nhl_team_info/logos"
#
# FIXME: MOVE THIS "logos" route INTO ITS OWN FILE
# FIXME: THE DEFAULT LOGO WOULD MORE APPROPRIATELY BE THE NHL LOGO
#
@router.get("/logos")
async def get_image(logo_filename: str = "nhl_shield_dark.svg"):
    image_path = Path(LOGOS_DIR, logo_filename)
    logging.info(f"ROUTE: /nhl_team_info/logos  --  logo_filename={logo_filename}")
    logging.info(f"       image_path={image_path.__str__()}")
    if not image_path.is_file():
        return {"error": f"logo not found on the server: {logo_filename}"}
    return FileResponse(image_path)


############################
# ROUTE:  "/nhl_team_info"
#
@router.get("/", response_model=list[TeamInfo])
async def get_nhl_standings(teams:Optional[str]=None):
    db_nhl_stats = mongo_client[MONGO_DB_NAME]
    collection_teams_data = db_nhl_stats[MONGO_COLLECTION_TEAM_DATA]

    """Retrieve all team standings data from the start date to the end date, inclusive"""
    logging.info(f"ROUTE: /nhl_team_info  --  teams={teams}")

    pipeline = []
    pipeline.append(
        { "$sort": {"conferenceName": 1, "divisionName": 1, "teamAbbrev": 1}}
    )
    pipeline.append(
        {
            "$project": {
                "_id": 1,
                "team_abbrev": '$teamAbbrev',
                "team_name": '$teamName',
                "team_common_name": '$teamCommonName',
                "logo": '$localLogo',
                "conference_name": "$conferenceName",
                "conference_abbrev": "$conferenceAbbrev",
                "division_name": "$divisionName",
                "division_abbrev": "$divisionAbbrev"
            }
        }
    )

    results = collection_teams_data.aggregate(pipeline)

    team_info_results = []
    for entry in results:
        new_team_info = TeamInfo (
            # _id = -1,
            team_abbrev = entry["team_abbrev"],
            team_name = entry["team_name"],
            team_common_name = entry["team_common_name"],
            logo = entry["logo"],
            conference_name = entry["conference_name"],
            conference_abbrev = entry["conference_abbrev"],
            division_name = entry["division_name"],
            division_abbrev = entry["division_abbrev"],
        )
        team_info_results.append(new_team_info)

    return team_info_results
