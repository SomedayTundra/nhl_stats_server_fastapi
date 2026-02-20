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
print("START")
mongo_client = MongoClient(MONGO_URI)
try:
    # connect to MongoDB
    print(f"Attempting to connect to: {MONGO_URI}")
    mongo_client.admin.command("ping")
    print(f"Connected successfully [{mongo_client.address}]")
    database = mongo_client[MONGO_DB_NAME_NHL_STATS]
except Exception as e:
    raise Exception("  The following error occurred: ", e)

# nuke the team data db
print(f'!!Dropping db "{MONGO_COLLECTION_TEAM_DATA}" for a fresh start')
database.drop_collection(MONGO_COLLECTION_TEAM_DATA)

# nuke the data for Oct26th, just so have a valid day to fetch, which will trigger a team_data refresh
print(f'--Deleting team standings data for Oct 26, 2025')
collection_team_standings = database[CURRENT_SEASON]
collection_team_standings.delete_one({"date": "2025-10-26"})

print("END")
