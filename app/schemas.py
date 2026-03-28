from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


class TeamInfo(BaseModel):
    # _id: int,
    team_abbrev: str
    team_name: str
    team_common_name: str
    logo: str
    conference_name: str
    conference_abbrev: str
    division_name: str
    division_abbrev: str


class TeamStanding(BaseModel):
    # _id: int
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


#################################################################
# ..examples from the original travershy fastapi tutorial..
#
# class IssueStatus(str, Enum):
#     open = "open"
#     in_progress = "in_progress"
#     closed = "closed"
#
# class IssuePriority(str, Enum):
#     low = "low"
#     medium = "medium"
#     high = "high"
#
# class IssueCreate(BaseModel):
#     title: str = Field(min_length=3, max_length=100)
#     description: str = Field(min_length=5, max_length=1000)
#     priority: IssuePriority = IssuePriority.medium
#
# class IssueUpdate(BaseModel):
#     title: Optional[str] = Field(default=None, max_length=100)
#     description: Optional[str] = Field(default=None, max_length=1000)
#     priority: Optional[IssuePriority] = None
#     status: Optional[IssueStatus] = None
#
# class IssueOut(BaseModel):
#     id: str
#     title: str
#     description: str
#     priority: IssuePriority
#     status: IssueStatus
