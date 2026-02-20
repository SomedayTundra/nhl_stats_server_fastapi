import os
from datetime import date

import requests
from nhlpy import NHLClient
from pymongo import MongoClient
from calendar import monthrange

############################################
# DEBUG FLAGS

# if True, we nuke and rebuild the f"{CURRENT_SEASON}" collection
DEBUG_RESET_COLLECTION__CURRENT_SEASON = False

# if True, we nuke and rebuild the 'team_data' collection
DEBUG_RESET_COLLECTION__TEAM_DATA = False

# if True, we only operate on the last four days of any given month
DEBUG_ONLY_FETCH_LAST_FOUR_DAYS_OF_MONTH = False

# if True, more verbose debug output is included
DEBUG_VERBOSE = True

############################################

# constants for talking to the MongoDB instance
MONGO_URI_LOCALHOST = "mongodb://localhost:27017/"
MONGO_URI = MONGO_URI_LOCALHOST

MONGO_DB_NAME_NHL_STATS = "nhl_stats"
MONGO_COLLECTION_TEAM_DATA = "team_data"
MONGO_COLLECTION_STANDINGS = "standings"


LOCAL_IMAGE_FOLDER = "..\\..\\logos"

# constants for talking to the NHL API
#
# current season: 2025/2026
#     start date: 10/07/2025
#       end date: 04/19/2026
nhl_client = NHLClient()

CURRENT_SEASON = "season_20252026"
MONTHS_AND_YEARS = [
    (2025, 10),
    (2025, 11),
    (2025, 12),
    (2026, 1),
    (2026, 2),
    (2026, 3),
    (2026, 4),
]



def get_image_name_from_image_url(remote_image_url):
    # get the image name from the end of the URL
    image_name = remote_image_url.split("/")[-1]

    # some images, like logos, are SVG files, which can be parameterized using internal JS
    # so we'll strip off any trailing URL query parameters
    image_name = image_name.split("?")[0]
    return image_name


def get_local_image_path_for_image_url(remote_image_url, local_save_path=LOCAL_IMAGE_FOLDER):
    image_name = get_image_name_from_image_url(remote_image_url)

    # glue together the given local save path and the stripped down image name
    local_image_path = os.path.join(local_save_path, image_name)

    return local_image_path


def does_local_image_exist(image_url, local_save_folder=LOCAL_IMAGE_FOLDER):
    # get the image name from the URL
    # image_name = image_url.split("/")[-1]
    # local_image_path = os.path.join(local_save_folder, image_name)
    local_image_path = get_local_image_path_for_image_url(image_url, local_save_folder)
    return os.path.exists(local_image_path)


def save_image_file(image_url, local_save_folder=LOCAL_IMAGE_FOLDER):
    image_name = get_image_name_from_image_url(image_url)

    # get the image name from the end of the URL
    # image_name = image_url.split("/")[-1]

    # some images, like logos, are SVG files, which can be parameterized using internal JS
    # so we'll strip off any trailing URL query parameters
    # image_name = image_name.split("?")[0]

    # send a GET request to the image URL
    response = requests.get(image_url, stream=True)

    if response.status_code == 200:
        success = False
        local_image_path = os.path.join(local_save_folder, image_name)
        with open(local_image_path, "wb+") as file:
            for chunk in response.iter_content(1024):
                file.write(chunk)
            print(f"Downloaded: {image_name}, saved to: {local_image_path}")
            success = True

        if not success:
            print(f"Failed to download: {image_url}")


def farm_standings_for_month(year, month):
    print(f"Farming standings data for {month}-{year}:")

    # suss out what the last day of the given month is; monthrange is clever enough to account for leap years
    last_day_in_month = monthrange(year, month)[1]

    # build an appropriately-shaped 'target date' and ask the NHL API for the league standings on that day
    daily_standings_for_the_entire_month = []
    range_start = (
        (last_day_in_month - 4) if DEBUG_ONLY_FETCH_LAST_FOUR_DAYS_OF_MONTH else 1
    )

    today = date.today()
    for day in range(range_start, last_day_in_month):
        target_date_string = f"{year}-{month:02d}-{day:02d}"
        print(f"  ..{target_date_string}", end="")

        # if the day is greater-than today, we can bail
        target_date = date.fromisoformat(target_date_string)
        if target_date > today:
            print(f" ....{target_date} is greater than today ({today}), so we're done!")
            break

        # if we already have data for this day, skip it
        find_one_result = collection_team_standings.find_one({"date": target_date_string})
        if find_one_result:
            print(" ..Data already exists in our database for this day, moving on..")
        else:
            daily_standings = nhl_client.standings.league_standings(date=target_date_string)

            if not daily_standings["standings"]:
                print(" ..(no games on this day)")
            else:
                print(" ..Data acquired!")
                daily_standings_for_the_entire_month.append(daily_standings)

    return daily_standings_for_the_entire_month


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

# DEBUG: nuke the team data collection
if DEBUG_RESET_COLLECTION__TEAM_DATA:
    print(f'!!Dropping db "{MONGO_COLLECTION_TEAM_DATA}" for a fresh start!!')
    database.drop_collection(MONGO_COLLECTION_TEAM_DATA)

# DEBUG: nuke the "stats for the current season" collection
if DEBUG_RESET_COLLECTION__CURRENT_SEASON:
    print(f'!!Dropping db "{CURRENT_SEASON}" for a fresh start!!')
    database.drop_collection(MONGO_COLLECTION_STANDINGS)


print()

# build simplified standings info documents and add them to the database
collection_teams_data = database[MONGO_COLLECTION_TEAM_DATA]
collection_team_standings = database[CURRENT_SEASON]

# grab the standings for all the days in the given month of the given year
print()
for year, month in MONTHS_AND_YEARS:
    standings_for_month = farm_standings_for_month(year, month)
    for standings_for_day in standings_for_month:
        all_team_stats_on_this_day = standings_for_day["standings"]
        # all entries have the same date embedded, but 'standings_for_month' inconveniently doesn't, so we'll use the first one
        standings_date = all_team_stats_on_this_day[0]["date"]

        all_team_data = {}
        all_team_standings_on_this_day = {"date": standings_date, "team_info": []}

        for team in all_team_stats_on_this_day:
            # if we don't have data stored for this team yet, build a team data dictionary for it
            TEAM_NAME = team["teamName"]["default"]
            found_it = collection_teams_data.find_one({"teamName": TEAM_NAME})
            if found_it:
                if DEBUG_VERBOSE:
                    print(f"(team data already exists in db for {TEAM_NAME}, skipping)")
            else:
                collection_teams_data.insert_one(
                    {
                        "conferenceName": team["conferenceName"],
                        "conferenceAbbrev": team["conferenceAbbrev"],
                        "divisionName": team["divisionName"],
                        "divisionAbbrev": team["divisionAbbrev"],
                        "placeName": team["placeName"]["default"],
                        "teamName": TEAM_NAME,
                        "teamCommonName": team["teamCommonName"]["default"],
                        "teamAbbrev": team["teamAbbrev"]["default"],
                        "teamLogo": team["teamLogo"],
                        "localLogo": get_image_name_from_image_url(team["teamLogo"]),
                    }
                )
                print(f"Saved team data for the {TEAM_NAME}")

                image_url = team["teamLogo"]
                if not does_local_image_exist(image_url):
                    save_image_file(image_url)

            team_standings = {
                "name": team["teamName"]["default"],
                "common_name": team["teamCommonName"],
                "abbrev": team["teamAbbrev"],
                "wins": team["wins"],
                "losses": team["losses"],
                "ot_losses": team["otLosses"],
                "points": team["points"],
                "goals_for": team["goalFor"],
                "goals_against": team["goalAgainst"],
                "goal_diff": team["goalDifferential"],
            }
            all_team_standings_on_this_day["team_info"].append(team_standings)

        collection_team_standings.insert_one(all_team_standings_on_this_day)
        print(
            f"\nInserted stats for {all_team_standings_on_this_day['date']} into our database"
        )

    # all done; how about a blank line?
    print()

# all done; close the connection to the database
try:
    # close the connection to MongoDB
    print(f"Closing connection to: {MONGO_URI}")
    mongo_client.close()
except Exception as e:
    raise Exception("  The following error occurred: ", e)
