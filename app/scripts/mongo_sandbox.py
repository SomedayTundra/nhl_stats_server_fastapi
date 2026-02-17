from pymongo import MongoClient

# constants for talking to the MongoDB instance
MONGO_URI_LOCALHOST = "mongodb://localhost:27017/"
MONGO_URI = MONGO_URI_LOCALHOST

MONGO_DB_NAME_NHL_STATS = "nhl_stats"
MONGO_COLLECTION_TEAM_DATA = "team_data"
MONGO_COLLECTION_STANDINGS = "standings"

CURRENT_SEASON = "season_20252026"


########################################
# SCRIPT EXECUTION STARTS HERE
########################################
mongo_client = MongoClient(MONGO_URI)
try:
    # connect to MongoDB
    print(f"Attempting to connect to: {MONGO_URI}")
    mongo_client.admin.command("ping")
    print(f"Connected successfully [{mongo_client.address}]")
    database = mongo_client[MONGO_DB_NAME_NHL_STATS]
except Exception as e:
    raise Exception("  The following error occurred: ", e)

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


print("DONE")
