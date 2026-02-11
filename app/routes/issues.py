from fastapi import APIRouter, HTTPException, status
import uuid
from app.schemas import IssueCreate, IssueOut, IssueUpdate, IssueStatus
from app.storage import load_data, save_data

router = APIRouter(prefix="/api/v1/issues", tags=["issues"])

@router.get("/", response_model=list[IssueOut])
async def get_issues():
    """Retrieve all issues"""
    issues = load_data()
    return issues

@router.get("/{issue_id}", response_model=IssueOut)
async def get_issue(issue_id: str):
    """Get a single issue by id"""
    issues = load_data()
    for issue in issues:
        if issue["id"] == issue_id:
            return issue
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue '{issue_id}' not found")

@router.post("/", response_model=IssueOut, status_code=status.HTTP_201_CREATED)
def create_issue(payload: IssueCreate):
    """Create a new issue"""
    issues = load_data()
    new_issue = {
        "id": str(uuid.uuid4()),
        "title": payload.title,
        "description": payload.description,
        "priority": payload.priority,
        "status": IssueStatus.open,
    }
    issues.append(new_issue)
    save_data(issues)
    return new_issue

@router.put("/", response_model=IssueOut, status_code=status.HTTP_200_OK)
async def update_issue(issue_id: str, payload: IssueUpdate):
    """Update a single issue by id"""
    issues = load_data()
    for index, issue in enumerate(issues):
        if issue["id"] == issue_id:
            updated_issue = issue.copy()

            if payload.title is not None:
                updated_issue["title"] = payload.title
            if payload.description is not None:
                updated_issue["description"] = payload.description
            if payload.priority is not None:
                updated_issue["priority"] = payload.priority
            if payload.status is not None:
                updated_issue["status"] = payload.status

            issues[index] = updated_issue
            save_data(issues)
            return updated_issue

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue '{issue_id}' not found")

@router.delete("/", response_model=str, status_code=status.HTTP_200_OK)
async def delete_issue(issue_id: str):
    """Delete a single issue by id"""
    issues = load_data()
    for issue in issues:
        if issue["id"] == issue_id:
            issues.remove(issue)
            save_data(issues)
            return f"Removed issue {issue_id}"
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Issue '{issue_id}' not found")
