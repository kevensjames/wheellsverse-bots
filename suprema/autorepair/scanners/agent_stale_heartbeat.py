"""Scan: launchd / cron agents have stopped writing output ("never reported"
or "stale heartbeat").

Why this matters: the Compliance Agent reported 5/19 agents healthy —
12 had "NEVER REPORTED", 2 were stale >60min. That means most of the bot
fleet is silently dead. SUPREMA didn't catch this because it doesn't know
which agents are *supposed* to be running.

Strategy:
    - Treat each <project>/logs/*.log as one expected heartbeat source.
      A healthy agent writes SOMETHING to its log every cycle.
    - For each, look at file mtime:
        * < 60 min → healthy, no finding
        * 60min..6h → MEDIUM (stale)
        * > 6h → HIGH (likely dead or never started)
    - We deliberately do NOT need a registry of agent names; the logs
      directory IS the registry. If an agent's log doesn't exist that
      tells us nothing — but if it exists and hasn't been updated, that's
      a strong signal.
    - Skip files smaller than 200 bytes — they might be log-rotation
      stubs the agent will overwrite next run.

Read-only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

STALE_THRESHOLD_MIN = 60          # past this → MEDIUM
DEAD_THRESHOLD_MIN = 6 * 60       # past this → HIGH
MIN_SIZE_BYTES = 200


def _humanize(td: timedelta) -> str:
    s = int(td.total_seconds())
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    logs_dir = project / "logs"
    if not logs_dir.is_dir():
        return []

    now = datetime.now(timezone.utc)
    findings: list[dict] = []

    for log in logs_dir.glob("*.log"):
        try:
            st = log.stat()
        except Exception:
            continue
        if st.st_size < MIN_SIZE_BYTES:
            continue
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        age = now - mtime
        age_min = age.total_seconds() / 60

        if age_min < STALE_THRESHOLD_MIN:
            continue

        if age_min >= DEAD_THRESHOLD_MIN:
            sev = "high"
            verdict = "appears dead (no output >6h)"
        else:
            sev = "medium"
            verdict = "stale heartbeat"

        findings.append({
            "severity": sev,
            "location": str(log.relative_to(project)),
            "evidence": (f"Agent {log.stem!r} {verdict} — "
                         f"last write {_humanize(age)} ago "
                         f"({mtime.isoformat(timespec='seconds')})"),
            "fix_payload": {
                "action": "check_agent_process",
                "agent": log.stem,
                "last_mtime": mtime.isoformat(),
                "age_minutes": int(age_min),
            },
        })

    # Cap to top-15 to avoid swamping the panel — sort by severity then age
    findings.sort(
        key=lambda f: (
            0 if f["severity"] == "high" else 1,
            -f["fix_payload"].get("age_minutes", 0),
        )
    )
    return findings[:15]
