#!/usr/bin/env python3
"""
core/github_router.py
─────────────────────────────────────────────────────────────────────────────
GitHub API endpoints.

GET  /api/github/repos                    — list user repos
GET  /api/github/repo/{owner}/{repo}      — repo info
GET  /api/github/issues/{owner}/{repo}    — open issues
POST /api/github/issues/{owner}/{repo}    — create issue
GET  /api/github/prs/{owner}/{repo}       — open PRs
GET  /api/github/actions/{owner}/{repo}   — workflow runs
─────────────────────────────────────────────────────────────────────────────
"""

from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/github", tags=["github"])


def _engine():
    try:
        import core.github_engine as ge
        return ge
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"GitHub engine error: {e}")


@router.get("/repos")
def github_repos(limit: int = 30):
    try:
        return {"repos": _engine().get_user_repos(limit)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/repo/{owner}/{repo}")
def github_repo(owner: str, repo: str):
    try:
        return _engine().get_repo_info(f"{owner}/{repo}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/issues/{owner}/{repo}")
def github_issues(owner: str, repo: str, state: str = "open"):
    try:
        return {"issues": _engine().list_issues(f"{owner}/{repo}", state)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class IssueCreate(BaseModel):
    title: str
    body: str = ""
    labels: List[str] = []


@router.post("/issues/{owner}/{repo}")
def github_create_issue(owner: str, repo: str, req: IssueCreate):
    try:
        return _engine().create_issue(f"{owner}/{repo}", req.title, req.body, req.labels)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/prs/{owner}/{repo}")
def github_prs(owner: str, repo: str, state: str = "open"):
    try:
        return {"prs": _engine().list_prs(f"{owner}/{repo}", state)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/actions/{owner}/{repo}")
def github_actions(owner: str, repo: str):
    try:
        return {"runs": _engine().get_workflow_runs(f"{owner}/{repo}")}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
