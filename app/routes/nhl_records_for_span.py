import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pymongo import MongoClient
from pathlib import Path

from app.schemas import TeamStanding
from app.routes.nhl_team_info import get_all_abbrevs


############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/nhl_records_for_span", tags=["nhl_records_for_span"])

############################
# MONGO DB CLIENT
#
MONGO_URI_LOCALHOST = "mongodb://localhost:27017/"
MONGO_URI = MONGO_URI_LOCALHOST

MONGO_DB_NAME = "nhl_stats"
MONGO_COLLECTION_STANDINGS = "standings"

TEAM_DATA = "team_data"
TEAM_STANDINGS = "team_standings"

# FIXME: SHOULD WE ONLY CONNECT ONCE AND RE-USE THAT CONNECTION FOR ALL ROUTES?
#        YES--SEE [NHL-35]
#
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
from datetime import datetime, timedelta
def fresh_today(delta=0):
    """Return a current value for "today," optionally subtracting 'delta' number of days to go back in time."""
    return (datetime.today() - timedelta(delta)).strftime('%Y-%m-%d')


############################
# ROUTE:  "/api/nhl_standings"
#
@router.get("/", response_model=list[TeamStanding])
async def get_nhl_records_for_span(start_date: str = (fresh_today(14)), end_date: str = (fresh_today()), teams: list[str] = ["DET", "OTT", "BOS", "COL", "TOR"]):
    """Retrieve all team standings data from the start date to the end date, inclusive"""
    db_nhl_stats = mongo_client[MONGO_DB_NAME]
    collection_team_standings = db_nhl_stats[TEAM_STANDINGS]

    pipeline = []
    pipeline.append(
        {
            "$match": {
                "$or": [
                    {"date": { "$eq": start_date } },
                    {"date": { "$eq": end_date   } }
                ]
            }
        }
    )
    pipeline.append(
        {"$unwind": "$team_info"}
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

    if teams is not None:
        # team_abbrevs = teams.split(',')
        pipeline.append(
            {
                "$match": {
                    "team_info.abbrev.default": {
                        "$in": teams
                    }
                }
            }
        )

    pipeline.append(
        {"$sort": {"team_info.abbrev.default": 1, "date": 1}}
    )

    pipeline.append(
        {
            "$project": {
                "_id": 1,
                "date": 1,
                "team_name": '$team_info.name',
                "team_common_name": '$team_data.teamCommonName',
                "team_abbrev": '$team_data.teamAbbrev',
                "logo": '$team_data.localLogo',
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

    team_standings_start_date: list[TeamStanding] = []
    team_standings_end_date: list[TeamStanding] = []
    team_standing_results: list[TeamStanding] = []

    # build a TeamStanding for every entry
    for entry in results:
        entry_date = entry["date"]

        new_team_standing = TeamStanding(
            date=entry_date,
            team_name=entry["team_name"],
            team_abbrev=entry["team_abbrev"],
            team_common_name=entry["team_common_name"],
            logo=entry["logo"],
            wins=entry["wins"],
            losses=entry["losses"],
            ot_losses=entry["ot_losses"],
            points=entry["points"],
            goals_for=entry["goals_for"],
            goals_against=entry["goals_against"],
            goal_diff=entry["goal_diff"],
        )
        team_standing_results.append(new_team_standing)

        # sort the entries into ones for start_date and ones for end_date
        #
        # FIXME: this is clunky as hell, do better
        #
        if entry_date == start_date:
            team_standings_start_date.append(new_team_standing)
        else:
            team_standings_end_date.append(new_team_standing)

    span_results: list[TeamStanding] = []
    first_data: TeamStanding
    second_data: TeamStanding

    # iterate all the team abbreviations we care about
    for target_abbrev in teams:
        # find the start date standings for this team
        for start_standing in team_standings_start_date:
            if start_standing.team_abbrev == target_abbrev:
                first_data = start_standing

                # find the end date standings for this team
                for end_standing in team_standings_end_date:
                    if end_standing.team_abbrev == target_abbrev:
                        second_data = end_standing

                        second_data.wins -= first_data.wins
                        second_data.losses -= first_data.losses
                        second_data.ot_losses -= first_data.ot_losses
                        second_data.points -= first_data.points
                        second_data.goals_for -= first_data.goals_for
                        second_data.goals_against -= first_data.goals_against
                        second_data.goal_diff -= first_data.goal_diff

                        span_results.append(second_data)

                        break

                break

    return span_results
