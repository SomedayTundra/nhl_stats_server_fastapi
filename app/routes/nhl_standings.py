import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from app.schemas import TeamStanding
from pymongo import MongoClient, typings
from pathlib import Path


############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/nhl_standings", tags=["nhl_standings"])

############################
# MONGO DB CLIENT
#
MONGO_URI_LOCALHOST = "mongodb://localhost:27017/"
MONGO_URI = MONGO_URI_LOCALHOST

MONGO_DB_NAME = "nhl_stats"
MONGO_COLLECTION_STANDINGS = "standings"

TEAM_DATA = "team_data"
CURRENT_SEASON = "season_20252026"

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

from datetime import datetime
today = datetime.today().strftime('%Y-%m-%d')


############################
# ROUTE:  "/nhl_standings/logos"
#
@router.get("/logos")
async def get_image(logo_filename: str = "DET_light.svg"):
    image_path = Path(LOGOS_DIR, logo_filename)
    logging.info(f"ROUTE: /nhl_standings/logos  --  logo_filename={logo_filename}")
    logging.info(f"       image_path={image_path.__str__()}")
    if not image_path.is_file():
        return {"error": f"logo not found on the server: {logo_filename}"}
    return FileResponse(image_path)


############################
# ROUTE:  "/nhl_standings"
#
@router.get("/", response_model=list[TeamStanding])
async def get_nhl_standings(start_date: str = today, end_date:str = today):
    """Retrieve all team standings data from the start date to the end date, inclusive"""

    logging.info(f"ROUTE: /nhl_standings  --  start_date={start_date}, end_date={end_date}")

    db_nhl_stats = mongo_client[MONGO_DB_NAME]
    db_teams_data = db_nhl_stats[TEAM_DATA]
    collection_team_standings = db_nhl_stats[CURRENT_SEASON]
    target_teams = ['Detroit Red Wings', 'Toronto Maple Leafs']

    pipeline = []
    pipeline.append(
        {
            "$match": {
                "date": {
                    "$gte": start_date,
                    "$lte": end_date,
                }
            }
        }
    )
    pipeline.append(
        {
            "$unwind": "$team_info"
        }
    )
    pipeline.append(
        {
            "$sort": { "date": 1 }
        }
    )
    pipeline.append(
        {
            "$lookup": {
                "from": "team_data",
                "localField": 'team_info.name',
                "foreignField": "teamName",
                "as": "team_data"
            }
        }
    )
    pipeline.append(
        {
            "$unwind": "$team_data"
        }
    )
    pipeline.append(
        {
            "$project": {
                "_id": 1,
                "date": 1,
                "team_name": '$team_info.name',
                "logo": '$team_data.teamLogo',
                "wins": '$team_info.wins',
                "losses": '$team_info.losses',
                "ot_losses": '$team_info.ot_losses',
                "points": '$team_info.points',
                "goals_for": '$team_info.goals_for',
                "goals_against": '$team_info.goals_against',
                "goal_diff": '$team_info.goal_diff',
            }
        }
    )

    results = collection_team_standings.aggregate(pipeline)

    team_standing_results = []
    for entry in results:
        entry_date = entry["date"]

        new_team_standing = TeamStanding(
            # _id = -1,
            date = entry_date,
            team_name = entry["team_name"],
            logo = entry["logo"],
            wins = entry["wins"],
            losses = entry["losses"],
            ot_losses = entry["ot_losses"],
            points = entry["points"],
            goals_for = entry["goals_for"],
            goals_against = entry["goals_against"],
            goal_diff = entry["goal_diff"],
        )
        team_standing_results.append(new_team_standing)

    return team_standing_results

    # .match({date: {$gte: startDate, $lte: endDate}})
    # .unwind('$team_info')
    #  // .match({'team_info.name': {$in: ['Detroit Red Wings', 'Toronto Maple Leafs']}})
    # .sort({date: 1})
    # .lookup({from: 'team_data', localField: 'team_info.name', foreignField: 'teamName', as: 'team_data'})
    # .unwind("$team_data") \
    # .project({
    #     _id: 1,
    #     date: 1,
    #     team_name: '$team_info.name',
    #     local_logo: '$team_data.localLogo',
    #     wins: '$team_info.wins',
    #     losses: '$team_info.losses',
    #     ot_losses: '$team_info.ot_losses',
    #     points: '$team_info.points',
    #     goals_for: '$team_info.goals_for',
    #     goals_against: '$team_info.goals_against',
    #     goal_diff: '$team_info.goal_diff',
    # }) \
    # .toArray();

    return results
