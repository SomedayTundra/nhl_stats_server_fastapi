import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.schemas import TeamInfo

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
from app.constants import mongo_db_constants as mongo

############################
# MISC
# resolve relative to this module (app/logos), not the process CWD
LOGOS_DIR = (Path(__file__).resolve().parents[1] / "logos")

############################
# ROUTE:  "/nhl_team_info/logo"
#
@router.get("/logo")
async def get_image(logo_filename: str = "nhl_shield_dark.svg"):
    # logo_filename is attacker-controlled query input; accept only a bare filename that lands
    # inside LOGOS_DIR, never a path that could traverse out of it
    candidate = (LOGOS_DIR / logo_filename).resolve()
    if (
        Path(logo_filename).name != logo_filename
        or LOGOS_DIR not in candidate.parents
        or not candidate.is_file()
    ):
        raise HTTPException(status_code=404, detail=f"logo not found: {logo_filename}")
    return FileResponse(candidate)


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
async def get_nhl_team_info(teams:Optional[str]=None, division:Optional[str]=None, conference:Optional[str]=None, season_id:Optional[int]=None) -> list[TeamInfo]:
    db_nhl_stats = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection_teams_data = db_nhl_stats[mongo.COLLECTION_TEAM_DATA]

    """Retrieve all team info data, either for the teams specified by the comma-separated list of team abbreviations, or for all teams"""
    pipeline = []

    # pick the requested season, or default to the latest season we have data for
    if season_id is not None:
        pipeline.append({"$match": {"seasonId": season_id}})
    else:
        pipeline.append({"$sort": {"seasonId": -1}})
        pipeline.append({"$limit": 1})

    pipeline.append({"$unwind": "$teams"})
    pipeline.append(
        {
            "$replaceRoot": {
                "newRoot": {"$mergeObjects": ["$teams", {"seasonId": "$seasonId"}]}
            }
        }
    )

    if conference is not None:
        conference_abbrevs = conference.split(',')
        capitalized_conference_abbrevs = [a.upper() for a in conference_abbrevs] # in the db, all abbrevs are CAPITALIZED
        pipeline.append(
            {
                "$match": {
                    "conferenceAbbrev": {
                        "$in": capitalized_conference_abbrevs
                    }
                }
            }
        )
    if division is not None:
        division_abbrevs = division.split(',')
        capitalized_division_abbrevs = [a.upper() for a in division_abbrevs] # in the db, all abbrevs are CAPITALIZED
        pipeline.append(
            {
                "$match": {
                    "divisionAbbrev": {
                        "$in": capitalized_division_abbrevs
                    }
                }
            }
        )
    if teams is not None:
        team_abbrevs = teams.split(',')
        capitalized_team_abbrevs = [a.upper() for a in team_abbrevs] # in the db, all abbrevs are CAPITALIZED
        pipeline.append(
            {
                "$match": {
                    "teamAbbrev": {
                        "$in": capitalized_team_abbrevs
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
                "season_id": '$seasonId',
                "team_abbrev": '$teamAbbrev',
                "team_name": '$teamName',
                "team_common_name": '$teamCommonName',
                "logo": '$localLogo',
                "conference_name": {"$ifNull": ["$conferenceName", "NA"]},
                "conference_abbrev": {"$ifNull": ["$conferenceAbbrev", "NA"]},
                "division_name": "$divisionName",
                "division_abbrev": "$divisionAbbrev"
            }
        }
    )

    results = collection_teams_data.aggregate(pipeline)

    team_info_results = []
    for entry in results:
        new_team_info = TeamInfo (
            season_id = entry["season_id"],
            team_abbrev = entry["team_abbrev"],
            team_name = entry["team_name"],
            team_common_name = entry["team_common_name"],
            logo = entry["logo"],
            conference_name = entry.get("conference_name", "NA"),
            conference_abbrev = entry.get("conference_abbrev", "NA"),
            division_name = entry["division_name"],
            division_abbrev = entry["division_abbrev"],
        )
        team_info_results.append(new_team_info)

    return team_info_results
