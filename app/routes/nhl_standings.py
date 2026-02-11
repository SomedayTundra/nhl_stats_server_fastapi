from fastapi import APIRouter, HTTPException, status
import uuid
from app.schemas import TeamStanding
from pymongo import MongoClient

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/nhl_standings", tags=["nhl_standings"])

############################
# MONGO DB CLIENT
#
MONGO_URI_LOCALHOST = "mongodb://localhost:27017/"
MONGO_URI = MONGO_URI_LOCALHOST

MONGO_DB_NAME = "nhl_stats"
MONGO_COLLECTION_STANDINGS = "standings"

mongo_client = MongoClient(MONGO_URI)
try:
    # connect to MongoDB
    print(f"Attempting to connect to: {MONGO_URI}")
    mongo_client.admin.command("ping")
    print(f"Connected successfully [{mongo_client.address}]")
except Exception as e:
    raise Exception("  The following error occurred: ", e)

############################
# ROUTE:  "/nhl_standings"
#
@router.get("/", response_model=list[TeamStanding])
async def get_nhl_standings(start_date: str, end_date:str):
    """Retrieve all team standings data from the start date to the end date, inclusive"""
    return []

# // this section will help you get a list of all the stats
# router.get("/", async (req, res) => {
#     let collection = await db.collection("season_20252026");
#
# // use "today" for either date (or both) if they weren't given
# let startDate = req.query.startDate ? req.query.startDate : changeDateToMyPreferredStringFormat(new Date());
# let endDate = req.query.endDate ? req.query.endDate : changeDateToMyPreferredStringFormat(new Date());
#
# // if the start date is greater then the end date, just flip 'em; a range is a range
# if(startDate > endDate) {
# console.warn(`WARNING: startDate of ${startDate} > endDate of ${endDate}; flipping them!`);
# const tempDate = startDate;
# startDate = endDate;
# endDate = tempDate;
# }
# console.info(`INFO   : startDate is ${startDate}, endDate is ${endDate}`);
#
# // use an aggregation to get just the data for two dates, and for only three times, with an unwind and a project
# // thrown in to simplify the results into simple, flat array of data objects
# const targetTeams = ['Detroit Red Wings', 'Toronto Maple Leafs']
# let results = await collection.aggregate()
# .match({date: {$gte: startDate, $lte: endDate}})
# .unwind('$team_info')
#  // .match({'team_info.name': {$in: ['Detroit Red Wings', 'Toronto Maple Leafs']}})
# .sort({date: 1})
# .lookup({from: 'team_data', localField: 'team_info.name', foreignField: 'teamName', as: 'team_data'})
# .unwind("$team_data") \
# .project({
#     _id: 1,
#     date: 1,
#     team_name: '$team_info.name',
#     local_logo: '$team_data.localLogo',
#     wins: '$team_info.wins',
#     losses: '$team_info.losses',
#     ot_losses: '$team_info.ot_losses',
#     points: '$team_info.points',
#     goals_for: '$team_info.goals_for',
#     goals_against: '$team_info.goals_against',
#     goal_diff: '$team_info.goal_diff',
# }) \
# .toArray();
#
# res.send(results).status(200);
# });

############################################################################################
############################################################################################

# @router.get("/{issue_id}", response_model=IssueOut)
# async def get_issue(issue_id: str):
#     """Get a single issue by id"""
#     issues = load_data()
#     for issue in issues:
#         if issue["id"] == issue_id:
#             return issue
#     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue '{issue_id}' not found")
#
# @router.post("/", response_model=IssueOut, status_code=status.HTTP_201_CREATED)
# def create_issue(payload: IssueCreate):
#     """Create a new issue"""
#     issues = load_data()
#     new_issue = {
#         "id": str(uuid.uuid4()),
#         "title": payload.title,
#         "description": payload.description,
#         "priority": payload.priority,
#         "status": IssueStatus.open,
#     }
#     issues.append(new_issue)
#     save_data(issues)
#     return new_issue
#
# @router.put("/", response_model=IssueOut, status_code=status.HTTP_200_OK)
# async def update_issue(issue_id: str, payload: IssueUpdate):
#     """Update a single issue by id"""
#     issues = load_data()
#     for index, issue in enumerate(issues):
#         if issue["id"] == issue_id:
#             updated_issue = issue.copy()
#
#             if payload.title is not None:
#                 updated_issue["title"] = payload.title
#             if payload.description is not None:
#                 updated_issue["description"] = payload.description
#             if payload.priority is not None:
#                 updated_issue["priority"] = payload.priority
#             if payload.status is not None:
#                 updated_issue["status"] = payload.status
#
#             issues[index] = updated_issue
#             save_data(issues)
#             return updated_issue
#
#     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue '{issue_id}' not found")
#
# @router.delete("/", response_model=str, status_code=status.HTTP_200_OK)
# async def delete_issue(issue_id: str):
#     """Delete a single issue by id"""
#     issues = load_data()
#     for issue in issues:
#         if issue["id"] == issue_id:
#             issues.remove(issue)
#             save_data(issues)
#             return f"Removed issue {issue_id}"
#     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue '{issue_id}' not found")
#
# function changeDateToMyPreferredStringFormat(inputDate) {
#     let monthDigits = ('0'+(inputDate.getMonth()+1)).slice(-2);
# let dayDigits = ('0'+inputDate.getDate()).slice(-2);
# return `${inputDate.getFullYear()}-${monthDigits}-${dayDigits}`;
# }
#
