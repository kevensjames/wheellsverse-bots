#!/usr/bin/env python3
"""
core/github_engine.py
─────────────────────────────────────────────────────────────────────────────
GitHub integration using PyGithub.
Requires: PyGithub>=2.1.0 (pip install PyGithub)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from typing import Dict, List

logger = logging.getLogger("github_engine")


def _get_github():
    try:
        from github import Github
    except ImportError:
        raise RuntimeError("PyGithub not installed. Run: pip install PyGithub")
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN not set")
    return Github(token)


def get_user_repos(limit: int = 30) -> List[Dict]:
    gh = _get_github()
    user = gh.get_user()
    repos = []
    for repo in user.get_repos(sort="updated")[:limit]:
        repos.append({
            "name": repo.name,
            "full_name": repo.full_name,
            "description": repo.description or "",
            "stars": repo.stargazers_count,
            "forks": repo.forks_count,
            "language": repo.language or "",
            "private": repo.private,
            "url": repo.html_url,
            "updated_at": str(repo.updated_at),
        })
    return repos


def get_repo_info(full_name: str) -> Dict:
    gh = _get_github()
    repo = gh.get_repo(full_name)
    return {
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description or "",
        "stars": repo.stargazers_count,
        "forks": repo.forks_count,
        "issues": repo.open_issues_count,
        "language": repo.language or "",
        "url": repo.html_url,
        "default_branch": repo.default_branch,
        "updated_at": str(repo.updated_at),
    }


def list_issues(full_name: str, state: str = "open", limit: int = 20) -> List[Dict]:
    gh = _get_github()
    repo = gh.get_repo(full_name)
    issues = []
    for issue in repo.get_issues(state=state)[:limit]:
        issues.append({
            "number": issue.number,
            "title": issue.title,
            "state": issue.state,
            "labels": [line.name for line in issue.labels],
            "url": issue.html_url,
            "created_at": str(issue.created_at),
            "user": issue.user.login,
        })
    return issues


def create_issue(full_name: str, title: str, body: str = "", labels: List[str] = None) -> Dict:
    gh = _get_github()
    repo = gh.get_repo(full_name)
    kwargs = {"title": title, "body": body}
    if labels:
        kwargs["labels"] = labels
    issue = repo.create_issue(**kwargs)
    return {"number": issue.number, "url": issue.html_url, "title": issue.title}


def list_prs(full_name: str, state: str = "open", limit: int = 20) -> List[Dict]:
    gh = _get_github()
    repo = gh.get_repo(full_name)
    prs = []
    for pr in repo.get_pulls(state=state)[:limit]:
        prs.append({
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "url": pr.html_url,
            "created_at": str(pr.created_at),
            "user": pr.user.login,
            "mergeable": pr.mergeable,
        })
    return prs


def get_workflow_runs(full_name: str, limit: int = 10) -> List[Dict]:
    gh = _get_github()
    repo = gh.get_repo(full_name)
    runs = []
    for run in repo.get_workflow_runs()[:limit]:
        runs.append({
            "id": run.id,
            "name": run.name,
            "status": run.status,
            "conclusion": run.conclusion,
            "branch": run.head_branch,
            "url": run.html_url,
            "created_at": str(run.created_at),
        })
    return runs


def commit_file(full_name: str, path: str, content: str, message: str, branch: str = "") -> Dict:
    """Commit a file to a GitHub repo."""
    gh = _get_github()
    repo = gh.get_repo(full_name)
    b = branch or repo.default_branch
    content_bytes = content.encode("utf-8")
    try:
        existing = repo.get_contents(path, ref=b)
        result = repo.update_file(path, message, content_bytes, existing.sha, branch=b)
        action = "updated"
    except Exception:
        result = repo.create_file(path, message, content_bytes, branch=b)
        action = "created"
    return {
        "action": action,
        "path": path,
        "commit_sha": result["commit"].sha,
        "url": result["commit"].html_url,
    }
