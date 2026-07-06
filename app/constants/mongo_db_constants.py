# constants for talking to the MongoDB instance
import logging
from pymongo import MongoClient

URI_LOCALHOST = "mongodb://localhost:27017/"
URI = URI_LOCALHOST

DB_NAME_NHL_STATS = "nhl_stats"
COLLECTION_TEAM_DATA = "team_data"
COLLECTION_TEAM_STANDINGS = "team_standings"

COLLECTION_USER_DATA = "user_data"


client = MongoClient(URI)
try:
    # connect to MongoDB
    logging.info(f"Attempting to connect to: {URI}")
    client.admin.command("ping")
    logging.info(f"Connected successfully [{client.address}]")
except Exception as e:
    raise Exception("  The following error occurred: ", e)
