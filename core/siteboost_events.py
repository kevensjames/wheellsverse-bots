"""Lightweight event log for SiteBoost operator activity.

File-backed (JSON Lines append) so it survives container redeploys when pointed
at the Railway volume via SITEBOOST_EVENTS_PATH. Each entry is one JSON object
on its own line — append-only, never rewritten, so concurrent writes are safe.

Fields per event:
    ts       — ISO-8601 UTC timestamp
    type     — e.g. "scan.started", "send.dispatched", "unsubscribe.click"
    run_id   — the relevant run (or "" when not run-specific)
    detail   — free-form dict of context fields (business, email, slug, etc.)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("siteboost_events")

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_EVENTS = ROOT / "data" / "launches" / "siteboost" / "events.jsonl"
EVENTS_PATH = Path(os.getenv("SITEBOOST_EVENTS_PATH", str(_DEFAULT_EVENTS)))


def log_event(event_type: str, run_id: str = "", **detail) -> None:
    """Append one event to the log. Non-blocking, never raises on disk errors —
    operator-activity logging must NEVER break the actual feature it tracks.
    """
    try:
        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": event_type,
            "run_id": run_id,
            "detail": detail,
        }
        with EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"event log write failed for {event_type!r}: {e}")


def get_recent_events(limit: int = 100) -> list[dict]:
    """Return the most-recent N events (newest first). Empty list if no log yet."""
    if not EVENTS_PATH.exists():
        return []
    try:
        with EVENTS_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning(f"event log read failed: {e}")
        return []
    out: list[dict] = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
