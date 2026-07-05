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
import mongo_db_constants as mongo

# FIXME: SHOULD WE ONLY CONNECT ONCE AND RE-USE THAT CONNECTION FOR ALL ROUTES?
#        YES--SEE [NHL-35]
#
mongo_client = MongoClient(mongo.URI)
try:
    # connect to MongoDB
    logging.info(f"Attempting to connect to: {mongo.URI}")
    mongo_client.admin.command("ping")
    logging.info(f"Connected successfully [{mongo_client.address}]")
except Exception as e:
    raise Exception("  The following error occurred: ", e)

############################
# MISC
LOGOS_DIR = "logos"

############################
# ROUTE:  "/nhl_team_info/logo"
#
@router.get("/logo")
async def get_image(logo_filename: str = "nhl_shield_dark.svg"):
    image_path = Path(LOGOS_DIR, logo_filename)
    if not image_path.is_file():
        return {"error": f"logo not found on the server: {logo_filename}"}
    return FileResponse(image_path)


############################
# ROUTE:  "/nhl_team_info/get_all_abbrevs"
#
@router.get("/get_all_abbrevs", response_model=list[str])
async def get_all_abbrevs():
    all_team_info = await get_nhl_team_info()
    return map(lambda team_info: team_info.team_abbrev , all_team_info)


############################
# ROUTE:  "/nhl_team_info"
#
@router.get("/", response_model=list[TeamInfo])
async def get_nhl_team_info(teams:Optional[str]=None) -> list[TeamInfo]:
    db_nhl_stats = mongo_client[mongo.DB_NAME_NHL_STATS]
    collection_teams_data = db_nhl_stats[mongo.COLLECTION_TEAM_DATA]

    """Retrieve all team info data, either for the teams specified by the comma-separated list of team abbreviations, or for all teams"""
    pipeline = []
    if teams is not None:
        team_abbrevs = teams.split(',')
        pipeline.append(
            {
                "$match": {
                    "teamAbbrev": {
                        "$in": team_abbrevs
                    }
                }
            }
        )

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
