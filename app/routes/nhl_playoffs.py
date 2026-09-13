import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from nhlpy import NHLClient
from nhlpy.http_client import NHLApiException

############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/playoffs", tags=["nhl_playoffs"])

############################
# MONGO DB CLIENT
#
from app.constants import mongo_db_constants as mongo

############################
# NHL API CLIENT
#
nhl_client = NHLClient()


def _last_game_winner_team_id(season_id: int, series_letter: str) -> Optional[int]:
    # Which team won the most recent completed game of a series. The bracket payload only carries
    # series-level win counts, so the per-series schedule is the only place this lives. Playoff
    # games can't end level, so an equal score means the game hasn't been played yet.
    schedule = nhl_client.schedule.playoff_series_schedule(str(season_id), series_letter.lower())

    winner_id: Optional[int] = None
    latest_game_number = -1
    for game in schedule.get("games", []):
        away = game.get("awayTeam") or {}
        home = game.get("homeTeam") or {}
        away_score, home_score = away.get("score"), home.get("score")
        if away_score is None or home_score is None or away_score == home_score:
            continue

        game_number = game.get("gameNumber") or 0
        if game_number > latest_game_number:
            latest_game_number = game_number
            winner_id = home.get("id") if home_score > away_score else away.get("id")

    return winner_id


def _add_last_game_winners(playoff_data: dict[str, Any], season_id: int) -> None:
    # A series that's level and still being played has no winner to hang its record on, so the
    # client shows it against whoever took the most recent game. Only level, undecided series cost
    # an extra call here, which means a finished postseason costs nothing at all.
    for series in playoff_data.get("series", []):
        if series.get("winningTeamId") is not None:
            continue

        top_wins = series.get("topSeedWins") or 0
        bottom_wins = series.get("bottomSeedWins") or 0
        series_letter = series.get("seriesLetter")
        if top_wins != bottom_wins or top_wins == 0 or series_letter is None:
            continue

        try:
            winner_id = _last_game_winner_team_id(season_id, series_letter)
        except NHLApiException as exc:
            # a tie-break is a nicety - don't fail the whole bracket over one missing schedule
            logging.warning(f"could not read series {series_letter} schedule for {season_id}: {exc.message}")
            continue

        if winner_id is not None:
            series["lastGameWinnerTeamId"] = winner_id


def _season_id_for_playoff_year(year: int) -> int:
    # the NHL API's playoff-bracket endpoint is keyed on the single calendar year the Cup was
    # awarded (e.g. "2024"), while seasonInfo documents are keyed on the two-year seasonId
    # (e.g. 20232024 for the 2023-24 season). Convert so we store/read the same seasonInfo
    # document the rest of the app already uses for that season.
    return (year - 1) * 10000 + year


############################
# ROUTE:  "/api/playoffs/{year}"
#
# year is the single calendar year the playoffs concluded in (e.g. 2024 for the 2023-24 season's
# playoffs), matching the NHL API's own playoff-bracket/{year} endpoint.
#
# Returns the full, unfiltered playoff-bracket payload the NHL API gives us for that year (every
# series, every round, both teams, winner/loser) - see
# https://api-web.nhle.com/v1/playoff-bracket/{year}.
#
# The seasonInfo collection is always checked first; the NHL API is only consulted on a cache
# miss, and the freshly fetched data is then written back to seasonInfo (keyed on the seasonId
# derived from year) as a "playoffs" sub-object.
#
@router.get("/{year}")
async def get_playoffs(year: int) -> dict[str, Any]:
    resolved_season_id = _season_id_for_playoff_year(year)

    db_nhl_stats = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection_season_info = db_nhl_stats[mongo.COLLECTION_SEASON_INFO]

    cached = collection_season_info.find_one({"_id": resolved_season_id})
    if cached is not None and "playoffs" in cached:
        return cached["playoffs"]

    try:
        playoff_data = nhl_client.schedule.playoff_bracket(str(year))
    except NHLApiException as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"NHL API had no playoff data for {year}: {exc.message}",
        )

    # a postseason that hasn't been played yet answers 200 with an empty series list rather than
    # 404, so only cache a bracket that actually has series in it - otherwise we'd pin "no
    # playoffs" onto the season forever and never look again once they're played
    series_list = playoff_data.get("series") or []
    if not series_list:
        logging.info(f"NHL API has no playoff series for {year} yet; returning it uncached")
        return playoff_data

    _add_last_game_winners(playoff_data, resolved_season_id)

    # same reasoning one step further in: a postseason still being played keeps changing, so it's
    # only safe to freeze into Mongo once every series has a winner
    if any(series.get("winningTeamId") is None for series in series_list):
        logging.info(f"{year} playoffs are still in progress; returning the bracket uncached")
        return playoff_data

    # document is named after (its _id) and keyed on the seasonId, same as seasonInfo's
    # startDate/endDate - this just adds a "playoffs" sub-object alongside them
    collection_season_info.update_one(
        {"_id": resolved_season_id},
        {"$set": {"seasonId": resolved_season_id, "playoffs": playoff_data}},
        upsert=True,
    )
    logging.info(f"seasonInfo.playoffs cache miss for {year} (seasonId {resolved_season_id}); stored fresh data")

    return playoff_data
