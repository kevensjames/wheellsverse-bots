"""Scan: local git HEAD doesn't match what's deployed in production.

Pattern from session: prod had a hand-set `GIT_SHA=9dc21a3` env var
that lied for 30 days while real deploys happened. Even after that was
fixed, there's a different gap: local commits that haven't been pushed
or deployed yet. This scanner makes the diff visible — "you're 5
commits ahead of production."

Strategy:
  1. Read local git HEAD's short SHA
  2. Fetch the live /api/health JSON, read its build_time + git_sha
  3. If build_time is older than the local HEAD's commit time, OR if
     the SHAs disagree AND we can verify the local SHA isn't reachable
     from the deployed SHA, flag.

Conservative — false positives waste operator attention. Only flags
when BOTH conditions hold: SHA mismatch AND build_time is older than
the local HEAD commit time."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _local_head_info(project: Path) -> tuple[str, str] | None:
    """Return (short_sha, ISO-8601 commit time). None if not a repo."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(project), capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if not sha:
            return None
        commit_time = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=str(project), capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return sha, commit_time
    except Exception:
        return None


def _fetch_health(url: str, timeout: float = 8.0) -> dict | None:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url + "/api/health"), timeout=timeout
        ) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _commits_ahead(project: Path, deployed_sha: str) -> int | None:
    """Count of commits HEAD is ahead of the deployed_sha, if reachable."""
    try:
        r = subprocess.run(
            ["git", "rev-list", "--count", f"{deployed_sha}..HEAD"],
            cwd=str(project), capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return int(r.stdout.strip() or "0")
    except Exception:
        pass
    return None


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    if not live_url:
        return []
    if not (project / ".git").exists():
        return []

    local = _local_head_info(project)
    if not local:
        return []
    local_sha, local_time_iso = local

    health = _fetch_health(live_url)
    if not health:
        return []

    deployed_sha = str(health.get("git_sha", "")).strip()
    deployed_build_time = str(health.get("build_time", "")).strip()

    if not deployed_sha:
        return []

    # If SHAs match, we're in sync
    if deployed_sha == local_sha:
        return []

    # SHAs differ. Count commits ahead.
    ahead = _commits_ahead(project, deployed_sha)

    # Compare timestamps. If local commit predates deployed build, then
    # the deployed version is AHEAD of local — that's fine, don't flag.
    try:
        local_time = datetime.fromisoformat(local_time_iso.replace("Z", "+00:00"))
        if deployed_build_time:
            build_time = datetime.fromisoformat(deployed_build_time.replace("Z", "+00:00"))
            if build_time >= local_time:
                # Deployed is newer than local — operator is behind, not ahead
                return []
    except Exception:
        pass

    # Local is ahead. Surface as informational.
    if ahead is None:
        evidence = (
            f"local HEAD={local_sha} but deployed git_sha={deployed_sha} — "
            f"and the deployed SHA isn't in the local git history"
        )
        severity = "medium"
    elif ahead == 0:
        return []
    else:
        evidence = (
            f"local HEAD is {ahead} commit{'s' if ahead != 1 else ''} ahead "
            f"of deployed (local={local_sha}, deployed={deployed_sha})"
        )
        severity = "medium" if ahead < 5 else "high"

    return [{
        "severity": severity,
        "location": f"{live_url}/api/health",
        "evidence": evidence,
        "fix_payload": {
            "local_sha": local_sha,
            "deployed_sha": deployed_sha,
            "commits_ahead": ahead,
            "build_time": deployed_build_time,
        },
    }]
