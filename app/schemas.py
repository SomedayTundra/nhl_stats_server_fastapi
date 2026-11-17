from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


##########
# CamelModel conveniently aliases all of our snake_case field names to camelCase
# since most of our clients will prefer to digest camelCase names
class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)


##########

class TeamInfo(CamelModel):
    # _id: int,
    season_id: int
    team_abbrev: str
    team_name: str
    team_common_name: str
    logo: str
    # the dark-background crest (for a dark page theme); None when the NHL has no dark version
    # of this crest, or for seasons not yet run through backfill_dark_logos.py - use `logo` then
    logo_dark: Optional[str] = None
    conference_name: str = "NA"
    conference_abbrev: str = "NA"
    division_name: str
    division_abbrev: str
    chart_line_color: Optional[str] = None
    # the dark page theme's line color, only for teams whose light one won't do there (too dark
    # to read, or noticeably different on the dark crest); use chart_line_color when it's None
    chart_line_color_dark: Optional[str] = None


class TeamStanding(CamelModel):
    # _id: int
    season_id: int
    date: str
    team_name: str
    team_common_name: str
    team_abbrev: str
    logo: str
    # see TeamInfo.logo_dark
    logo_dark: Optional[str] = None
    chart_line_color: Optional[str] = None
    # the dark page theme's line color, only for teams whose light one won't do there (too dark
    # to read, or noticeably different on the dark crest); use chart_line_color when it's None
    chart_line_color_dark: Optional[str] = None
    games_played: int
    win_pctg: float
    wins: int
    losses: int
    ot_losses: int
    points: int
    point_pctg: float
    goals_for: int
    goals_against: int
    goal_diff: int
    # the last-10-games tallies. Optional because days farmed before these were captured have no
    # such fields until `backfill_last_ten.py` has run over them; the client renders the gap
    # rather than a misleading zero
    l10_wins: Optional[int] = None
    l10_losses: Optional[int] = None
    l10_ot_losses: Optional[int] = None
    l10_ties: Optional[int] = None
    l10_goals_for: Optional[int] = None
    l10_goals_against: Optional[int] = None
    l10_goal_diff: Optional[int] = None

class UserData(CamelModel):
    # _id: int
    user: str
    start_date: str
    end_date: str

class SeasonInfo(CamelModel):
    # _id: int  (the seasonId, e.g. 19421943)
    season_id: int
    start_date: str
    end_date: str
    # True for a season where some team's last-10 window has hit a non-zero OT loss and a
    # non-zero tie at the same time (only possible 1999-2000 through 2003-04, when both existed)
    # - see app/scripts/tag_l10_overlap_seasons.py. Optional/None for a season that script hasn't
    # tagged yet (a brand-new season fetched straight from the NHL manifest); the client treats
    # that the same as False, which is correct since a season with no games yet can't overlap
    l10_ot_and_tie_overlap: Optional[bool] = None


class FarmRun(CamelModel):
    # one update_mongodb.py run, as served by /api/farm_runs. The stored document also has `host`
    # and `os_user` (the machine and login that ran it), which the route leaves out on purpose:
    # this endpoint is public, and those name a personal machine on manual runs
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_s: Optional[float] = None
    # "success", or "error: <ExceptionType>" - the route drops the exception's message, which can
    # carry hostnames or connection details
    status: Optional[str] = None
    trigger: Optional[str] = None  # "scheduled", "dispatch" or "manual"
    triggered_by: Optional[str] = None
    season_arg: Optional[int] = None  # None means "the current season"
    github_actor: Optional[str] = None
    github_run_id: Optional[str] = None
    github_run_url: Optional[str] = None


class FarmRuns(CamelModel):
    # how many runs farm_runs keeps (mongo.FARM_RUNS_TO_KEEP), and those runs, newest first
    farm_runs_to_keep: int
    runs: list[FarmRun]
