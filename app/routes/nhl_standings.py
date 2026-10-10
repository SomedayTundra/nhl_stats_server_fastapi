import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

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
from app.constants import mongo_db_constants as mongo

############################
# MISC
from datetime import date, timedelta
def get_yesterday():
    today = date.today()
    yesterday = today - timedelta(days=1)
    return yesterday.isoformat()

############################
# ON-DEMAND FARMING
#
# when the client asks for a season we've never cached, shell out to update_mongodb.py to farm it
# from the NHL API before answering. A full season is a few minutes of NHL API calls, so the
# client shows a "loading uncached data" state while this request stays open.
#
# This is opt-in via ENABLE_ONDEMAND_FARMING. Production pre-loads the database and farms new
# data by hand (`python -m app.scripts.update_mongodb <seasonId>`), so a stray request for an
# un-cached season should just return what we have rather than tie up a worker for minutes.
_APP_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_DIR.parent
_FARM_TIMEOUT_SECONDS = 30 * 60
_ONDEMAND_FARMING_ENABLED = os.getenv("ENABLE_ONDEMAND_FARMING", "false").strip().lower() in {"1", "true", "yes"}

# one lock per seasonId so concurrent/retried requests for the same uncached season wait for the
# first farm instead of each launching their own; _farm_attempted remembers seasons we've already
# run the script for this session, so a completed season with a genuine data gap isn't re-farmed
# on every request
_farm_locks: dict[int, asyncio.Lock] = {}
_farm_attempted: set[int] = set()


def _run_update_script_blocking(season_id: int) -> None:
    # run the farm script as a module from the repo root so it resolves `from app.constants ...`
    # without any PYTHONPATH juggling; it inherits MONGO_URI etc. from our environment
    result = subprocess.run(
        [sys.executable, "-m", "app.scripts.update_mongodb", str(season_id)],
        cwd=str(_REPO_ROOT),
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=_FARM_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        logging.error("update_mongodb.py failed for season %s (exit %s):\n%s",
                      season_id, result.returncode, (result.stdout or "")[-2000:])
        raise RuntimeError(f"update_mongodb.py exited {result.returncode}")


async def _ensure_season_cached(season_id: int) -> None:
    db_nhl_stats = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection = db_nhl_stats[mongo.COLLECTION_TEAM_STANDINGS]
    if collection.count_documents({"seasonId": season_id}, limit=1) > 0 or season_id in _farm_attempted:
        return

    if not _ONDEMAND_FARMING_ENABLED:
        logging.info(
            "season %s is not cached and ENABLE_ONDEMAND_FARMING is off; serving what we have",
            season_id,
        )
        return

    # only auto-farm seasons that are already over: their data is final, so "farm once, keep
    # forever" holds. The current/upcoming season is kept fresh by running update_mongodb.py
    # directly instead, and a not-yet-finished season would just have us re-farm on every request.
    season_meta = db_nhl_stats[mongo.COLLECTION_SEASON_INFO].find_one({"_id": season_id})
    if season_meta is None or season_meta.get("endDate", "") >= date.today().isoformat():
        return

    lock = _farm_locks.setdefault(season_id, asyncio.Lock())
    async with lock:
        # another request may have finished farming this season while we waited for the lock
        if collection.count_documents({"seasonId": season_id}, limit=1) > 0 or season_id in _farm_attempted:
            return

        logging.info("no cached standings for season %s; farming via update_mongodb.py", season_id)
        try:
            await run_in_threadpool(_run_update_script_blocking, season_id)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail=f"timed out farming season {season_id} from the NHL API")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"failed to farm season {season_id} from the NHL API: {exc}")
        # succeeded (even if the NHL API had nothing for it) - don't run the script again this session
        _farm_attempted.add(season_id)


############################
# ROUTE:  "/api/nhl_standings"
#
@router.get("/", response_model=list[TeamStanding])
async def get_nhl_standings(start_date: str = get_yesterday(), end_date: str = get_yesterday(), teams: Optional[str] = None, season_id: Optional[int] = None):
    """Retrieve all team standings data from the start date to the end date, inclusive"""
    db_nhl_stats = mongo.client[mongo.DB_NAME_NHL_STATS]
    collection_user_data = db_nhl_stats[mongo.COLLECTION_USER_DATA]

    # store the start_date and end_date, so the user's client can always reset whatever date controls
    # it uses in its UI to the last start and end date that were used (on app refresh, for example)
    collection_user_data.delete_one({"user": "default"})
    collection_user_data.insert_one({"user": "default", "start_date": start_date, "end_date": end_date})

    # fetch the data the user wanted, team standings info from start_date => end_date
    collection_team_standings = db_nhl_stats[mongo.COLLECTION_TEAM_STANDINGS]

    # if the client named a season we have nothing for, farm it from the NHL API before answering
    if season_id is not None:
        await _ensure_season_cached(season_id)

    # a Mongo query document is genuinely heterogeneous (str, int, nested dicts, ...) - annotate it
    # as such up front, otherwise the checker infers dict[str, str] from the literal below and
    # balks at assigning the int seasonId to it further down
    date_match: dict[str, Any] = {
        "date": {
            "$gte": start_date,
            "$lte": end_date,
        }
    }
    if season_id is not None:
        date_match["seasonId"] = season_id

    pipeline: list[dict[str, Any]] = []
    pipeline.append({"$match": date_match})
    pipeline.append(
        {"$unwind": "$team_info"}
    )

    if teams is not None:
        team_abbrevs = teams.split(',')
        capitalized_abbrevs = [a.upper() for a in team_abbrevs] # in the db, all abbrevs are CAPITALIZED
        pipeline.append(
            {
                "$match": {
                    "team_info.abbrev.default": {
                        "$in": capitalized_abbrevs
                    }
                }
            }
        )

    pipeline.append(
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "season_id": '$seasonId',
                "team_name": '$team_info.name',
                "games_played": '$team_info.games_played',
                "win_pctg": '$team_info.win_pctg',
                "wins": '$team_info.wins',
                "losses": '$team_info.losses',
                "ot_losses": '$team_info.ot_losses',
                "points": '$team_info.points',
                "point_pctg": '$team_info.point_pctg',
                "goals_for": '$team_info.goals_for',
                "goals_against": '$team_info.goals_against',
                "goal_diff": '$team_info.goal_diff',
                "l10_wins": '$team_info.l10_wins',
                "l10_losses": '$team_info.l10_losses',
                "l10_ot_losses": '$team_info.l10_ot_losses',
                "l10_ties": '$team_info.l10_ties',
                "l10_goals_for": '$team_info.l10_goals_for',
                "l10_goals_against": '$team_info.l10_goals_against',
                "l10_goal_diff": '$team_info.l10_goal_diff',
            }
        }
    )

    rows = list(collection_team_standings.aggregate(pipeline))

    # team abbrev / common name / logo are constant for a team across a whole season, but they live
    # in a separate `team_data` collection (one document per season, holding all ~32 teams). Joining
    # them in per row with a correlated `$lookup` used to dominate this endpoint's runtime (~5.5s for
    # a full season). Instead we pull the one `team_data` doc per season referenced by the result set
    # and enrich in Python - the same output, ~50x faster.
    season_ids = {row["season_id"] for row in rows}
    collection_team_data = db_nhl_stats[mongo.COLLECTION_TEAM_DATA]
    team_meta: dict[tuple[int, str], dict[str, Any]] = {}
    for team_data_doc in collection_team_data.find({"seasonId": {"$in": list(season_ids)}}):
        for team in team_data_doc.get("teams", []):
            team_meta[(team_data_doc["seasonId"], team["teamName"])] = team

    team_standing_results = []
    for entry in rows:
        # mirrors the old `$unwind: $team_data`: a standings row whose team has no team_data match
        # (name mismatch, un-farmed season) is dropped rather than returned half-populated
        meta = team_meta.get((entry["season_id"], entry["team_name"]))
        if meta is None:
            continue

        new_team_standing = TeamStanding(
            season_id=entry["season_id"],
            date=entry["date"],
            team_name=entry["team_name"],
            team_abbrev=meta["teamAbbrev"],
            team_common_name=meta["teamCommonName"],
            logo=meta["localLogo"],
            chart_line_color=meta.get("chartLineColor"),
            games_played=entry["games_played"],
            win_pctg=entry["win_pctg"],
            wins=entry["wins"],
            losses=entry["losses"],
            ot_losses=entry["ot_losses"],
            points=entry["points"],
            point_pctg=entry["point_pctg"],
            goals_for=entry["goals_for"],
            goals_against=entry["goals_against"],
            goal_diff=entry["goal_diff"],
            l10_wins=entry.get("l10_wins"),
            l10_losses=entry.get("l10_losses"),
            l10_ot_losses=entry.get("l10_ot_losses"),
            l10_ties=entry.get("l10_ties"),
            l10_goals_for=entry.get("l10_goals_for"),
            l10_goals_against=entry.get("l10_goals_against"),
            l10_goal_diff=entry.get("l10_goal_diff"),
        )
        team_standing_results.append(new_team_standing)

    # keep the old response ordering (by team, then chronological) so any client relying on it is unaffected
    team_standing_results.sort(key=lambda r: (r.team_abbrev, r.date))

    return team_standing_results
