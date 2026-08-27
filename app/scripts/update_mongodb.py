###################################################
# CALLS THE "NHL STATS API" TO FARM DATA THAT WE
# STORE IN OUR MONGODB INSTANCE, WHICH CAN THEN
# ACCESSED VIA OUR FASTAPI REST INTERFACE TO
# FUEL OUR WEB CLIENTS
#
###################################################


import argparse
import os
from datetime import date
from typing import Any

import requests
from nhlpy import NHLClient
from pymongo import MongoClient
from calendar import monthrange

import mongo_db_constants as mongo

############################################
# DEBUG FLAGS

# if True, we nuke and rebuild the f"{MONGO_COLLECTION_TEAM_STANDINGS}" collection
DEBUG_RESET_COLLECTION__TEAM_STANDINGS = False

# if True, we nuke and rebuild the 'team_data' collection
DEBUG_RESET_COLLECTION__TEAM_DATA = False

# if True, we only operate on the last four days of any given month
DEBUG_ONLY_FETCH_LAST_FOUR_DAYS_OF_MONTH = False

# if True, more verbose debug output is included
DEBUG_VERBOSE = False

############################################

# which seasons to farm on this run: "current_only" farms just the latest season (self-updating,
# no manual month-list maintenance needed); "all_since_1942" walks every season back to 1942-43.
# NOTE: "all_since_1942" is a long-running, many-thousand-call operation against the live NHL API.
# overridden entirely if a seasonId is passed on the command line (see parse_args/season_by_id).
SEASONS_TO_PROCESS = "current_only"

# the earliest seasonId we care about: the 1942-43 season, the start of the "Original Six" era
EARLIEST_SEASON_ID = 19421943

############################################

LOCAL_IMAGE_FOLDER = "..\\logos"

nhl_client = NHLClient()


def get_season_manifest(earliest_season_id=EARLIEST_SEASON_ID):
    all_seasons = nhl_client.standings.season_standing_manifest()
    seasons_in_range = [s for s in all_seasons if s["id"] >= earliest_season_id]
    seasons_in_range.sort(key=lambda s: s["id"])
    return seasons_in_range


def season_by_id(season_manifest, season_id):
    for season in season_manifest:
        if season["id"] == season_id:
            return season
    raise ValueError(f"seasonId {season_id} not found in the season manifest")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Farm NHL standings/team data into MongoDB."
    )
    parser.add_argument(
        "season_id",
        type=int,
        nargs="?",
        default=None,
        help="Restrict the run to a single seasonId (e.g. 19891990 for the 1989-90 "
        "season). If omitted, falls back to SEASONS_TO_PROCESS.",
    )
    return parser.parse_args()


def most_recently_started_season(season_manifest, today=None):
    # the manifest includes seasons scheduled to start in the future, so "current" means the
    # most recently *started* season as of today, whether it's in progress or already finished
    today = today or date.today()
    already_started = [
        s for s in season_manifest if date.fromisoformat(s["standingsStart"]) <= today
    ]
    return max(already_started, key=lambda s: s["id"])


def months_spanning(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


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
    # send a GET request to the image URL
    image_name = get_image_name_from_image_url(image_url)
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

    if DEBUG_VERBOSE:
        print(f"..last_day_in_month: {last_day_in_month}")

    # build an appropriately-shaped 'target date' and ask the NHL API for the league standings on that day
    daily_standings_for_the_entire_month = []
    range_start = (
        (last_day_in_month - 4) if DEBUG_ONLY_FETCH_LAST_FOUR_DAYS_OF_MONTH else 1
    )

    today = date.today()
    for day in range(range_start, last_day_in_month + 1):
        target_date_string = f"{year}-{month:02d}-{day:02d}"
        print(f"  ..{target_date_string}", end="")

        # if the day is greater-than today, we can bail
        target_date = date.fromisoformat(target_date_string)
        if target_date > today:
            print(f" ....{target_date} is greater than today ({today}), so we're done!")
            break

        farm_standings_for_day(daily_standings_for_the_entire_month, target_date_string)

    return daily_standings_for_the_entire_month


def farm_standings_for_day(standings_list: list[Any], target_date_string: str):
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
            standings_list.append(daily_standings)


def store_standings_in_mongo(standings_list: list[Any]):
    for standings_for_day in standings_list:
        # all entries have the same date embedded, but 'standings_for_month' inconveniently doesn't have a date field,
        # so we'll use the date in the first entry
        all_team_stats_on_this_day = standings_for_day["standings"]
        standings_date = all_team_stats_on_this_day[0]["date"]
        season_id = all_team_stats_on_this_day[0]["seasonId"]
        all_team_standings_on_this_day = {
            "date": standings_date,
            "seasonId": season_id,
            "team_info": [],
        }

        for team in all_team_stats_on_this_day:
            # if we don't have data stored for this team in this season yet, add it to that
            # season's team_data document
            TEAM_NAME = team["teamName"]["default"]
            TEAM_ABBREV = team["teamAbbrev"]["default"]
            found_it = collection_teams_data.find_one(
                {"seasonId": season_id, "teams.teamAbbrev": TEAM_ABBREV}
            )
            if found_it:
                if DEBUG_VERBOSE:
                    print(f"(team data already exists in db for {TEAM_NAME} in season {season_id}, skipping)")
            else:
                collection_teams_data.update_one(
                    {"seasonId": season_id},
                    {
                        "$push": {
                            "teams": {
                                "conferenceName": team["conferenceName"],
                                "conferenceAbbrev": team["conferenceAbbrev"],
                                "divisionName": team["divisionName"],
                                "divisionAbbrev": team["divisionAbbrev"],
                                "placeName": team["placeName"]["default"],
                                "teamName": TEAM_NAME,
                                "teamCommonName": team["teamCommonName"]["default"],
                                "teamAbbrev": TEAM_ABBREV,
                                "teamLogo": team["teamLogo"],
                                "localLogo": get_image_name_from_image_url(team["teamLogo"]),
                            }
                        }
                    },
                    upsert=True,
                )
                print(f"Saved team data for the {TEAM_NAME} (season {season_id})")

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
            f"  Inserted stats for {all_team_standings_on_this_day['date']} into our database"
        )


########################################
# SCRIPT EXECUTION STARTS HERE
########################################
args = parse_args()

mongo_client = MongoClient(mongo.URI)
try:
    # connect to MongoDB
    print(f"Attempting to connect to: {mongo.URI}")
    mongo_client.admin.command("ping")
    print(f"Connected successfully [{mongo_client.address}]")
    database = mongo_client[mongo.DB_NAME_NHL_STATS]
except Exception as e:
    raise Exception("  The following error occurred: ", e)

########################################
# DEBUG: possibly nuke the team data collection
if DEBUG_RESET_COLLECTION__TEAM_DATA:
    print(f'!!Dropping collection "{mongo.COLLECTION_TEAM_DATA}" for a fresh start!!')
    database.drop_collection(mongo.COLLECTION_TEAM_DATA)

# DEBUG: possibly nuke the "stats for the current season" collection
if DEBUG_RESET_COLLECTION__TEAM_STANDINGS:
    print(f'!!Dropping collection "{mongo.COLLECTION_TEAM_STANDINGS}" for a fresh start!!')
    database.drop_collection(mongo.COLLECTION_TEAM_STANDINGS)
#
########################################

# create simplified teams_data and team_standings documents
collection_teams_data = database[mongo.COLLECTION_TEAM_DATA]
collection_team_standings = database[mongo.COLLECTION_TEAM_STANDINGS]

# grab the standings for all the days in every month of every season we're processing this run
print()

season_manifest = get_season_manifest()
if args.season_id is not None:
    seasons_to_run = [season_by_id(season_manifest, args.season_id)]
elif SEASONS_TO_PROCESS == "current_only":
    seasons_to_run = [most_recently_started_season(season_manifest)]
else:
    seasons_to_run = season_manifest

for season in seasons_to_run:
    season_start = date.fromisoformat(season["standingsStart"])
    season_end = date.fromisoformat(season["standingsEnd"])
    print(f"Farming season {season['id']} ({season_start} to {season_end}):")

    for year, month in months_spanning(season_start, season_end):
        standings_for_month = farm_standings_for_month(year, month)
        store_standings_in_mongo(standings_for_month)

        # all done; how about a blank line?
        print()

# all done; close the connection to the database
try:
    # close the connection to MongoDB
    print(f"Closing connection to: {mongo.URI}")
    mongo_client.close()
except Exception as e:
    raise Exception("  The following error occurred: ", e)
