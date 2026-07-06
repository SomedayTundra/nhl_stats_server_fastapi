import logging
from typing import Optional

from fastapi import APIRouter

from app.schemas import TeamStanding

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
import mongo_db_constants as mongo

############################
# MISC
from datetime import datetime
def fresh_today():
    return datetime.today().strftime('%Y-%m-%d')


############################
# ROUTE:  "/api/nhl_standings"
#
@router.get("/", response_model=list[TeamStanding])
async def get_nhl_standings(start_date: str = (fresh_today()), end_date: str = (fresh_today()), teams: Optional[str] = None):
    """Retrieve all team standings data from the start date to the end date, inclusive"""
    db_nhl_stats = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection_user_data = db_nhl_stats[mongo.COLLECTION_USER_DATA]

    # store the start_date and end_date, so the user's client can always reset whatever date controls
    # it uses in its UI to the last start and end date that were used (on app refresh, for example)
    collection_user_data.delete_one({"user": "default"})
    collection_user_data.insert_one({"user": "default", "start_date": start_date, "end_date": end_date})

    # fetch the data the user wanted, team standings info from start_date => end_date
    collection_team_standings = db_nhl_stats[mongo.COLLECTION_TEAM_STANDINGS]

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
        {"$unwind": "$team_info"}
    )
    pipeline.append(
        {"$sort": {"date": 1}}
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
        team_abbrevs = teams.split(',')
        pipeline.append(
            {
                "$match": {
                    "team_info.abbrev.default": {
                        "$in": team_abbrevs
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

    team_standing_results = []
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

    return team_standing_results
