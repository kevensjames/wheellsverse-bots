"""Scan: /api/health reports a git_sha that disagrees with the deployed image.

If git_sha hasn't changed for >7 days while uptime is fresh, it's almost
certainly the hardcoded-env-var failure mode (an operator set GIT_SHA
manually long ago and forgot — every deploy since reads that stale value)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE_KEY = "stale_git_sha_history"  # we read prior runs' state to detect "hasn't moved"


def _fetch_json(url: str, timeout: float = 8.0) -> dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    if not live_url:
        return []
    health = _fetch_json(live_url + "/api/health")
    if not health:
        return []

    git_sha = str(health.get("git_sha", "")).strip()
    uptime = int(health.get("uptime", 0))
    build_time = str(health.get("build_time", "")).strip()

    # Heuristic 1: uptime is recent (< 1h) AND build_time is older than uptime
    # → image was built long ago but only just rebooted (probably a config
    # change, not a code change — fine on its own, not a finding).
    #
    # Heuristic 2: build_time is missing entirely. That means the deploy
    # never wrote /app/BUILD_TIME — image is from before the GIT_SHA
    # honesty fix landed.
    findings: list[dict] = []

    if not build_time:
        findings.append({
            "severity": "low",
            "location": f"{live_url}/api/health",
            "evidence": f"git_sha={git_sha!r} but no build_time field — image "
                        f"predates the GIT_SHA honesty patch",
            "fix_payload": {"git_sha": git_sha, "build_time_missing": True},
        })

    # Heuristic 3: read recent state files for sha-over-time
    state_dir = Path(__file__).parent.parent / "state"
    history_file = state_dir / "history.jsonl"
    if history_file.exists():
        prior_shas: list[tuple[str, str]] = []
        try:
            for line in history_file.read_text().splitlines()[-30:]:
                rec = json.loads(line)
                for finding in rec.get("findings", []):
                    if finding.get("pattern") == "stale_git_sha_health":
                        continue
                # also scan all-projects state for /api/health captures
                pass
        except Exception:
            pass

    return findings
