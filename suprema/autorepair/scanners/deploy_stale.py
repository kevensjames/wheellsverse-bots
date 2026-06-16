"""Scan: production deploy hasn't refreshed recently.

Heuristic: /api/health uptime is much larger than 30 days OR build_time
is missing AND the project has had commits in the last 7 days. Either
case suggests a broken deploy chain (real cause in this workspace's
history: GitHub Actions disabled, Gitea→GitHub mirror dead, etc.)."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

STALE_UPTIME_SECONDS = 30 * 24 * 3600  # 30 days


def _fetch_health(live_url: str, timeout: float = 8.0) -> dict:
    try:
        req = urllib.request.Request(live_url + "/api/health")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _recent_commits(project: Path, days: int = 7) -> int:
    try:
        since = subprocess.run(
            ["git", "rev-list", "--count", f"--since={days}.days.ago", "HEAD"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int(since.stdout.strip() or "0")
    except Exception:
        return 0


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    if not live_url:
        return []
    health = _fetch_health(live_url)
    if not health:
        return []

    uptime = int(health.get("uptime", 0))
    recent = _recent_commits(project, days=7)
    git_sha = str(health.get("git_sha", "")).strip()

    findings: list[dict] = []

    if uptime > STALE_UPTIME_SECONDS and recent > 0:
        findings.append({
            "severity": "high",
            "location": f"{live_url}/api/health",
            "evidence": f"uptime={uptime}s (>{STALE_UPTIME_SECONDS}s) "
                        f"but {recent} commits in last 7 days — deploy chain stalled",
            "fix_payload": {"uptime": uptime, "recent_commits": recent},
        })
    elif recent > 5 and not health.get("build_time"):
        findings.append({
            "severity": "medium",
            "location": f"{live_url}/api/health",
            "evidence": f"{recent} commits in last 7 days, no build_time in "
                        f"/api/health — observability gap",
            "fix_payload": {"git_sha": git_sha, "recent_commits": recent},
        })
    return findings
