# constants for talking to the MongoDB instance
import logging
import os

from pymongo import MongoClient

URI_LOCALHOST = "mongodb://localhost:27017/"
# the deployed server sets MONGO_URI (see .env.example / docker-compose.yml); local dev falls
# back to a localhost mongod
URI = os.getenv("MONGO_URI", URI_LOCALHOST)

DB_NAME_NHL_STATS = "nhl_stats"
COLLECTION_TEAM_DATA = "team_data"
COLLECTION_TEAM_STANDINGS = "team_standings"
COLLECTION_SEASON_INFO = "seasonInfo"

COLLECTION_USER_DATA = "user_data"


# fail fast instead of hanging ~30s on the default server-selection timeout when the URI is wrong
client = MongoClient(URI, serverSelectionTimeoutMS=5000)
try:
    # connect to MongoDB
    logging.info(f"Attempting to connect to: {URI}")
    client.admin.command("ping")
    logging.info(f"Connected successfully [{client.address}]")
except Exception as e:
    raise RuntimeError(f"could not connect to MongoDB at {URI}: {e}") from e

# at most one team_standings document per (seasonId, date). Without this, two farm runs that
# overlap for the same season (a manual backfill racing the server's own on-demand farming, or a
# re-run that starts before an earlier one finishes) can both pass update_mongodb.py's "do we
# already have this day" check before either has inserted, and both write the same day - an exact
# duplicate that then shows up as a duplicate row in the standings table. create_index is a no-op
# if the index already exists, so this is cheap to run on every import.
client[DB_NAME_NHL_STATS][COLLECTION_TEAM_STANDINGS].create_index(
    [("seasonId", 1), ("date", 1)], unique=True, name="unique_season_date"
)
