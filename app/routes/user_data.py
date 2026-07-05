import logging
from typing import Optional

from fastapi import APIRouter
from pymongo import MongoClient

from app.schemas import TeamInfo, UserData

############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/user_data", tags=["user_data"])

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
# ROUTE:  "/api/user_data/"
#
@router.get("/", response_model=list[UserData])
async def get_user_data(users:Optional[str]=None) -> list[UserData]:
    """Retrieve all user data, either for the users specified by the comma-separated list of user names, or for all teams"""
    db_nhl_stats = mongo_client[mongo.DB_NAME_NHL_STATS]
    collection_user_data = db_nhl_stats[mongo.COLLECTION_USER_DATA]

    pipeline = []
    if users is not None:
        user_names = users.split(',')
        pipeline.append(
            {
                "$match": {
                    "user": {
                        "$in": user_names
                    }
                }
            }
        )

    results = collection_user_data.aggregate(pipeline)

    user_data_results = []
    for entry in results:
        new_user_data = UserData (
            user = entry["user"],
            start_date = entry["start_date"],
            end_date = entry["end_date"],
        )
        user_data_results.append(new_user_data)

    for user in user_data_results:
        logging.info(user)

    return user_data_results
