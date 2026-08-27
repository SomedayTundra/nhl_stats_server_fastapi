from pydantic import BaseModel
from humps import camelize


##########
# CamelModel conveniently aliases all of our snake_case field names to camelCase
# since most of our clients will prefer to digest camelCase names
def to_camel(string):
    return camelize(string)

class CamelModel(BaseModel):
    class Config:
        alias_generator = to_camel
        validate_by_name = True


##########

class TeamInfo(CamelModel):
    # _id: int,
    season_id: int
    team_abbrev: str
    team_name: str
    team_common_name: str
    logo: str
    conference_name: str = "NA"
    conference_abbrev: str = "NA"
    division_name: str
    division_abbrev: str


class TeamStanding(CamelModel):
    # _id: int
    season_id: int
    date: str
    team_name: str
    team_common_name: str
    team_abbrev: str
    logo: str
    wins: int
    losses: int
    ot_losses: int
    points: int
    goals_for: int
    goals_against: int
    goal_diff: int

class UserData(CamelModel):
    # _id: int
    user: str
    start_date: str
    end_date: str
