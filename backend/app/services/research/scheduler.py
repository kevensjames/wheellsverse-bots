"""Background scheduler — runs research cycle once per day at ~08:00.

Implementation mirrors KAI Supreme's scheduler (services/supreme/
scheduler.py): single daemon thread, opt-in via env, simple sleep loop.

Why not apscheduler / celery: we're running one job per day. Adding a
job framework for one entry would be 90% setup, 10% feature. A 30-line
sleep loop is the right tool.

Activation: KAI_RESEARCH_ENABLED=1 in .env. Default off so the daemon
starts fast and operators who don't want the network polling can run
KAI without it.

Cadence:
  - KAI_RESEARCH_HOUR_UTC=8 (default) — wake at 08:00 UTC each day
  - First cycle runs ~30s after daemon start (so the operator can
    verify immediately by hitting /admin/research/run-now or seeing
    a digest appear)
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from app.services.research.digest import run_research_cycle

logger = logging.getLogger(__name__)

# Initial delay after start before the first cycle runs.
_INITIAL_DELAY_SECONDS = 30

# Polling interval — wake every minute and check whether it's the
# scheduled hour. Avoids drift from a 24h sleep + simpler than cron math.
_POLL_INTERVAL_SECONDS = 60

_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _scheduled_hour() -> int:
    raw = (os.environ.get("KAI_RESEARCH_HOUR_UTC") or "8").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 8
    return max(0, min(h, 23))


def _loop():
    """Cycle loop. Runs first cycle after initial delay, then once per
    day at the scheduled UTC hour. Re-reads env each cycle so live
    edits to KAI_RESEARCH_INTERESTS are picked up without restart."""
    target_hour = _scheduled_hour()
    last_cycle_day: str | None = None

    # Initial delay so the daemon's startup isn't blocked on network calls
    if _stop_event is not None and _stop_event.wait(timeout=_INITIAL_DELAY_SECONDS):
        return

    # First-run cycle — gives operators immediate feedback
    try:
        d = run_research_cycle()
        last_cycle_day = d.id[:8]  # YYYYMMDD
    except Exception as e:
        logger.exception("research: first cycle crashed: %s", e)

    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == target_hour and today_key != last_cycle_day:
            try:
                d = run_research_cycle()
                last_cycle_day = d.id[:8]
            except Exception as e:
                logger.exception("research: cycle crashed: %s", e)
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break
    logger.info("research: scheduler thread exiting")


def start() -> bool:
    """Start the scheduler thread if KAI_RESEARCH_ENABLED=1. Returns
    True if the thread was started, False if disabled or already running."""
    global _thread, _stop_event
    if (os.environ.get("KAI_RESEARCH_ENABLED") or "").strip() not in ("1", "true", "yes"):
        logger.info("research: scheduler not started (KAI_RESEARCH_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("research: scheduler already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-research", daemon=True)
    _thread.start()
    logger.info(
        "research: scheduler thread started (target_hour=%d UTC)",
        _scheduled_hour(),
    )
    return True


def stop(timeout: float = 5.0) -> None:
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
    _thread = None
    _stop_event = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
