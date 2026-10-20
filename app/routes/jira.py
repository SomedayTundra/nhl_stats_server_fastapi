import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

############################
# LOGGING
#
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

############################
# FAST API ROUTER
#
router = APIRouter(prefix="/api/jira", tags=["jira"])

############################
# JIRA CONFIG
#
# A read-only proxy onto one Jira Cloud space. The token never leaves this server: the client only ever sees the
# trimmed-down payloads below, and every Jira query is pinned to JIRA_PROJECT_KEY here rather than built from
# anything the client sends, so a token that can see the whole Atlassian site still only exposes this one space.
#
# JIRA_BASE_URL is either https://<site>.atlassian.net (classic API token) or
# https://api.atlassian.com/ex/jira/<cloudId> (scoped API token - the recommended read:jira-work + read:jira-user one).
#
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "NHL")

# the free plan's rate limits are low, and issues only change when someone edits them by hand, so a few minutes of
# staleness is a fine trade for not hitting Jira on every page view
CACHE_TTL_SECONDS = 300

# Issue type icons, kept on disk for good the same way app/logos keeps team logos. An avatar id's image never changes
# (choosing a new icon for a type gives it a new id), so a file here can't go stale. Resolved relative to this module,
# not the process CWD.
ICONS_DIR = Path(__file__).resolve().parents[1] / "jira_icons"
ICON_EXTENSIONS = {"image/svg+xml": "svg", "image/png": "png"}
ICON_HEADERS = {
    # the id names one image forever, so the browser never needs to ask again either
    "Cache-Control": "public, max-age=31536000, immutable",
    # an SVG opened directly (not via <img>) can run script on our API's origin; this keeps it an inert picture
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}

_LIST_FIELDS = "summary,status,issuetype,priority,assignee,created,updated"
_DETAIL_FIELDS = ",".join([
    "summary", "status", "issuetype", "priority", "assignee", "reporter", "labels", "components",
    "fixVersions", "parent", "subtasks", "issuelinks", "created", "updated", "resolutiondate", "description",
])

_cache: dict[str, tuple[float, Any]] = {}


# typed as plain Any (None on a miss, or once expired) rather than Optional[Any]: every caller checks for None and then
# returns the value as its own declared type, and a type checker can't narrow "Any | None" down to that
def _cached(key: str) -> Any:
    entry = _cache.get(key)
    if entry is None or entry[0] < time.monotonic():
        return None
    return entry[1]


def _store(key: str, value: Any) -> Any:
    _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)
    return value


def _client() -> httpx.AsyncClient:
    if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
        raise HTTPException(status_code=503, detail="Jira is not configured on this server")
    return httpx.AsyncClient(
        base_url=f"{JIRA_BASE_URL}/rest/api/3",
        auth=httpx.BasicAuth(JIRA_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
        timeout=15.0,
    )


async def _request(client: httpx.AsyncClient, path: str, params: Optional[dict[str, Any]] = None,
                   headers: Optional[dict[str, str]] = None) -> httpx.Response:
    try:
        response = await client.get(path, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logging.warning(f"Jira request {path} failed: {exc}")
        raise HTTPException(status_code=502, detail="Could not reach Jira")

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Issue not found")
    if response.status_code in (401, 403):
        # don't hand Jira's own message to the client - it can describe the account the token belongs to
        logging.warning(f"Jira rejected our credentials for {path}: {response.status_code}")
        raise HTTPException(status_code=502, detail="Jira rejected this server's credentials")
    if response.status_code == 429:
        raise HTTPException(status_code=503, detail="Jira is rate limiting us; try again shortly")
    if not response.is_success:
        logging.warning(f"Jira request {path} answered {response.status_code}: {response.text[:500]}")
        raise HTTPException(status_code=502, detail=f"Jira answered {response.status_code}")
    return response


async def _get(client: httpx.AsyncClient, path: str, params: Optional[dict[str, Any]] = None) -> Any:
    return (await _request(client, path, params)).json()


############################
# PAYLOAD TRIMMING
#
# Jira's payloads are huge and carry things we don't want to republish (account ids, email addresses, self links
# back into the authenticated API), so everything goes through these before it reaches the client.
#
def _user(user: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not user:
        return None
    return {
        "displayName": user.get("displayName"),
        "avatarUrl": (user.get("avatarUrls") or {}).get("48x48"),
    }


def _status(status: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not status:
        return None
    # category key is one of "new" / "indeterminate" / "done"; the client colors and orders statuses by it
    return {"name": status.get("name"), "category": (status.get("statusCategory") or {}).get("key")}


def _named(value: Optional[dict[str, Any]]) -> Optional[str]:
    return value.get("name") if value else None


# An issue type's iconUrl points into the authenticated Jira API, so the browser can't load it; all the client gets is
# the avatar id out of it, which it loads through /api/jira/issuetype-icons/{id} below. Jira writes that URL two ways:
# .../universal_avatar/view/type/issuetype/avatar/10315?size=medium, or (older types) ...?avatarId=10315&avatarType=...
_ICON_ID_PATTERN = re.compile(r"/avatar/(\d+)|[?&]avatarId=(\d+)")


def _issue_type_icon_id(issue_type: Optional[dict[str, Any]]) -> Optional[str]:
    match = _ICON_ID_PATTERN.search((issue_type or {}).get("iconUrl") or "")
    return (match.group(1) or match.group(2)) if match else None


def _issue_ref(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "status": _status(fields.get("status")),
        "issueType": _named(fields.get("issuetype")),
        "issueTypeIconId": _issue_type_icon_id(fields.get("issuetype")),
    }


def _issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    return {
        **_issue_ref(issue),
        "priority": _named(fields.get("priority")),
        "assignee": _user(fields.get("assignee")),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
    }


def _issue_links(links: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    trimmed = []
    for link in links or []:
        link_type = link.get("type") or {}
        if "outwardIssue" in link:
            trimmed.append({"relation": link_type.get("outward"), "issue": _issue_ref(link["outwardIssue"])})
        elif "inwardIssue" in link:
            trimmed.append({"relation": link_type.get("inward"), "issue": _issue_ref(link["inwardIssue"])})
    return trimmed


def _comment(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment.get("id"),
        "author": _user(comment.get("author")),
        "bodyHtml": comment.get("renderedBody") or "",
        "created": comment.get("created"),
        "updated": comment.get("updated"),
    }


############################
# ROUTE:  "/api/jira/issues"
#
# Every issue in the space, most recently updated first, trimmed to what the list view shows. The client filters by
# status itself - the whole space is a few hundred issues at most, and that keeps this one cache entry serving every
# filter rather than one Jira round trip per status.
#
@router.get("/issues")
async def get_issues() -> list[dict[str, Any]]:
    cached = _cached("issues")
    if cached is not None:
        return cached

    issues: list[dict[str, Any]] = []
    next_page_token: Optional[str] = None
    async with _client() as client:
        while True:
            params: dict[str, Any] = {
                "jql": f'project = "{JIRA_PROJECT_KEY}" ORDER BY updated DESC',
                "fields": _LIST_FIELDS,
                "maxResults": 100,
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token
            page = await _get(client, "/search/jql", params)
            issues.extend(_issue_summary(issue) for issue in page.get("issues", []))

            next_page_token = page.get("nextPageToken")
            if page.get("isLast", True) or not next_page_token:
                break

    return _store("issues", issues)


############################
# ROUTE:  "/api/jira/statuses"
#
# Every status the space's workflows define, whether or not any issue is in it right now - the issue list alone can't
# tell the client that "In Progress" exists while it's empty. Jira answers per issue type, so the same status shows up
# once per type that uses it; this flattens that to one entry per status.
#
@router.get("/statuses")
async def get_statuses() -> list[dict[str, Any]]:
    cached = _cached("statuses")
    if cached is not None:
        return cached

    async with _client() as client:
        issue_types = await _get(client, f"/project/{JIRA_PROJECT_KEY}/statuses")

    statuses: dict[str, dict[str, Any]] = {}
    for issue_type in issue_types:
        for status in issue_type.get("statuses", []):
            trimmed = _status(status)
            if trimmed and trimmed["name"] not in statuses:
                statuses[trimmed["name"]] = trimmed

    return _store("statuses", list(statuses.values()))


############################
# ROUTE:  "/api/jira/issuetype-icons/{icon_id}"
#
# One issue type's icon, handed back as the image itself. The first request for an id fetches it from Jira with our
# credentials and saves it to ICONS_DIR; every request after that is served straight off disk without touching Jira.
# Only the icons of issue types this space actually uses are ever fetched - otherwise this would be an open door to
# every avatar the token can see.
#
async def _project_icon_ids(client: httpx.AsyncClient) -> set[str]:
    cached = _cached("icon-ids")
    if cached is not None:
        return cached
    project = await _get(client, f"/project/{JIRA_PROJECT_KEY}")
    icon_ids = {icon_id for issue_type in project.get("issueTypes", []) if (icon_id := _issue_type_icon_id(issue_type))}
    return _store("icon-ids", icon_ids)


@router.get("/issuetype-icons/{icon_id}")
async def get_issue_type_icon(icon_id: str) -> Response:
    # digits only, so the id can't name a path outside ICONS_DIR
    if not icon_id.isdigit():
        raise HTTPException(status_code=404, detail="Icon not found")

    for extension in ICON_EXTENSIONS.values():
        saved = ICONS_DIR / f"{icon_id}.{extension}"
        if saved.is_file():
            return FileResponse(saved, headers=ICON_HEADERS)

    async with _client() as client:
        if icon_id not in await _project_icon_ids(client):
            raise HTTPException(status_code=404, detail="Icon not found")
        response = await _request(
            client,
            f"/universal_avatar/view/type/issuetype/avatar/{icon_id}",
            {"size": "medium"},
            {"Accept": "image/svg+xml,image/png"},
        )

    # Jira says "image/svg+xml;charset=UTF-8"; anything that isn't an SVG or PNG isn't worth keeping
    media_type = response.headers.get("content-type", "").split(";")[0].strip()
    extension = ICON_EXTENSIONS.get(media_type)
    if extension is None:
        logging.warning(f"Jira answered icon {icon_id} with unexpected content type {media_type!r}")
        raise HTTPException(status_code=502, detail="Jira's icon wasn't an SVG or PNG")

    # write-then-rename, so a request racing this one never serves a half-written file
    ICONS_DIR.mkdir(exist_ok=True)
    partial = ICONS_DIR / f"{icon_id}.{extension}.partial"
    partial.write_bytes(response.content)
    partial.replace(ICONS_DIR / f"{icon_id}.{extension}")
    logging.info(f"saved Jira issue type icon {icon_id}.{extension}")

    return Response(content=response.content, media_type=media_type, headers=ICON_HEADERS)


############################
# ROUTE:  "/api/jira/issues/{key}"
#
# One issue's full detail: fields, description and every comment, with the rich text already rendered to HTML by
# Jira (the client sanitizes it before display). The key has to belong to JIRA_PROJECT_KEY, so this can't be used to
# read issues from any other space the token can see.
#
@router.get("/issues/{key}")
async def get_issue(key: str) -> dict[str, Any]:
    key = key.upper()
    if not re.fullmatch(rf"{re.escape(JIRA_PROJECT_KEY)}-\d+", key):
        raise HTTPException(status_code=404, detail="Issue not found")

    cached = _cached(f"issue:{key}")
    if cached is not None:
        return cached

    async with _client() as client:
        issue = await _get(client, f"/issue/{key}", {"fields": _DETAIL_FIELDS, "expand": "renderedFields"})

        # an issue moved to another space keeps answering on its old key (Jira redirects), so check where it lives now
        if not str(issue.get("key", "")).startswith(f"{JIRA_PROJECT_KEY}-"):
            raise HTTPException(status_code=404, detail="Issue not found")

        comments: list[dict[str, Any]] = []
        start_at = 0
        while True:
            page = await _get(client, f"/issue/{key}/comment", {
                "startAt": start_at, "maxResults": 100, "orderBy": "created", "expand": "renderedBody",
            })
            page_comments = page.get("comments", [])
            comments.extend(_comment(comment) for comment in page_comments)
            start_at += len(page_comments)
            if not page_comments or start_at >= page.get("total", 0):
                break

    fields = issue.get("fields") or {}
    rendered = issue.get("renderedFields") or {}
    parent = fields.get("parent")
    detail = {
        **_issue_summary(issue),
        "reporter": _user(fields.get("reporter")),
        "labels": fields.get("labels") or [],
        "components": [_named(c) for c in fields.get("components") or []],
        "fixVersions": [_named(v) for v in fields.get("fixVersions") or []],
        "parent": _issue_ref(parent) if isinstance(parent, dict) else None,
        "subtasks": [_issue_ref(s) for s in fields.get("subtasks") or []],
        "links": _issue_links(fields.get("issuelinks")),
        "resolved": fields.get("resolutiondate"),
        "descriptionHtml": rendered.get("description") or "",
        "comments": comments,
    }
    return _store(f"issue:{key}", detail)
