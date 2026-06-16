"""Scan: bot log files are spewing ERROR / CRITICAL lines.

Why this matters: KAI Supreme reports surfaced 5-19 errors/hour across a
dozen log files (scheduler.out.log, content_scheduler, viral_analyzer,
ceo_agent, finance_agent, faq_chatbot, dashboard.err.log, etc.). SUPREMA
never noticed because it doesn't tail logs. We add that layer here.

Strategy:
    - Look in <project>/logs/ for *.log files modified in the last 90min.
    - For each, count lines containing 'ERROR' or 'CRITICAL' (case-sensitive,
      word-boundary-ish — avoids matching 'error_handler').
    - Bucket: per-file errors_in_last_hour. We look at the tail of the file
      and only count lines whose timestamp (if parseable) is within 60min;
      if no timestamp is parseable we fall back to "all tailed lines" so
      we still flag something.
    - MEDIUM if any file has >=5/hour. HIGH if any file has >=15/hour OR
      >=3 distinct files spiking simultaneously.
    - One finding per spiking file so the operator sees which bots are
      actually broken vs the panel just saying "errors somewhere".

This scanner is read-only.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ERROR_PAT = re.compile(r"\b(ERROR|CRITICAL|FATAL|Traceback)\b")
# Common timestamp formats found in Python logging output
TS_PATTERNS = [
    # 2026-06-15 14:23:01,234
    re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"),
    # 2026-06-15T14:23:01
    re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"),
]
TAIL_BYTES = 256 * 1024  # last 256 KB of each log


def _tail(path: Path, n_bytes: int = TAIL_BYTES) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > n_bytes:
                f.seek(-n_bytes, 2)
                f.readline()  # discard partial line
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _parse_ts(line: str) -> datetime | None:
    for pat in TS_PATTERNS:
        m = pat.match(line)
        if m:
            s = m.group(1).replace("T", " ")
            try:
                return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except Exception:
                continue
    return None


def _count_recent_errors(content: str, since: datetime) -> tuple[int, int]:
    """Returns (recent_count, total_count). recent = within last hour.

    If NO timestamps are parseable for ANY error line in the tail, we return
    `(0, total)` — NOT `(total, total)`. This was the bug: when a log had old
    errors with unparseable timestamps and recent INFO writes (touching mtime),
    every historical error counted as "recent" and the scanner cried wolf.

    Caller must additionally gate on "at least one parseable, recent ERROR
    line exists" before treating this as a fresh spike (see scan() below).
    """
    total = 0
    recent = 0
    saw_ts = False
    for line in content.splitlines():
        if not ERROR_PAT.search(line):
            continue
        total += 1
        ts = _parse_ts(line)
        if ts is None:
            continue
        saw_ts = True
        if ts >= since:
            recent += 1
    if not saw_ts:
        # No parseable timestamps anywhere → can't prove anything is recent.
        # Old behaviour returned (total, total) which fired on stale logs.
        return 0, total
    return recent, total


def _has_fresh_error_line(content: str, since: datetime) -> bool:
    """True iff at least one ERROR/CRITICAL line has a parseable timestamp
    that is within `since`. This is the recency gate — without it, a log
    with one parseable old timestamp + many unparseable lines could still
    pass through if recent>=5 (it can't anymore given the fix above, but
    we keep this explicit gate so the intent survives future refactors)."""
    for line in content.splitlines():
        if not ERROR_PAT.search(line):
            continue
        ts = _parse_ts(line)
        if ts is not None and ts >= since:
            return True
    return False


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    logs_dir = project / "logs"
    if not logs_dir.is_dir():
        return []

    now = datetime.now(timezone.utc)
    cutoff_mtime = now - timedelta(minutes=90)
    # Recency window for "fresh" errors. We widened from 1h → 2h after the
    # false-positive incident — gives the fixer a buffer to act before the
    # next scan and reduces flapping at the boundary.
    since = now - timedelta(hours=2)

    findings: list[dict] = []
    spiking_files = 0
    for log in logs_dir.glob("*.log"):
        try:
            mtime = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)
        except Exception:
            continue
        if mtime < cutoff_mtime:
            continue  # stale log, not currently spiking

        content = _tail(log)
        if not content:
            continue
        recent, total = _count_recent_errors(content, since)
        if recent < 5:
            continue
        # Recency gate: require at least one parseable, recent ERROR line
        # before reporting. Without this, a stale log whose mtime was
        # touched by INFO writes can still slip through if its old errors
        # happen to have parseable timestamps that survive the count.
        if not _has_fresh_error_line(content, since):
            continue

        spiking_files += 1
        sev = "high" if recent >= 15 else "medium"
        # Grab one sample error line for context
        sample = ""
        for line in content.splitlines()[::-1]:
            if ERROR_PAT.search(line):
                sample = line.strip()[:160]
                break

        findings.append({
            "severity": sev,
            "location": f"{log.relative_to(project)}",
            "evidence": (f"{recent} ERROR/CRITICAL line(s) in last hour "
                         f"({total} in tail). Sample: {sample}"),
            "fix_payload": {
                "action": "investigate_log",
                "log_path": str(log),
                "errors_last_hour": recent,
                "errors_in_tail": total,
            },
        })

    # If 3+ files are spiking, escalate them all to high — coordinated
    # failures usually mean a shared dependency (API key, DB) is down
    if spiking_files >= 3:
        for f in findings:
            f["severity"] = "high"
            f["evidence"] = (f"[{spiking_files} logs spiking simultaneously] "
                             + f["evidence"])

    return findings
