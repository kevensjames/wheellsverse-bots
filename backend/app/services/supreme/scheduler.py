"""Background scheduler for KAI Supreme.

Runs scan cycles every N seconds inside the uvicorn daemon. Implemented
as a single daemon thread because:
  - Scans are I/O-bound (subprocess + sockets) — GIL release is fine
  - We don't need cron-style precision; "every 15min ±10s" is the goal
  - No new deps (apscheduler / celery would be overkill for one job)
  - daemon=True means the thread dies cleanly with the daemon process

The original NarAI Supreme ran as a separate Login Item .app. Bringing
it inside KAI's process eliminates one moving part — when KAI is up,
so is the scanner.

Activation: set KAI_SUPREME_ENABLED=1. Disabled by default so the
scheduler is opt-in (lets operators run KAI without scans if they want).
"""
from __future__ import annotations

import logging
import os
import threading
import time

from app.services.supreme.scanner import load_map, run_full_cycle

logger = logging.getLogger(__name__)

# Fallback when SUPPREMA_MAP.yaml.supreme.scan_interval_seconds is missing.
# 15 minutes matches the original NarAI Supreme default.
_DEFAULT_INTERVAL_SECONDS = 900

# Set on the running thread so external code can introspect / shut down
# cleanly during tests. We never expect more than one supreme thread.
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _loop():
    """Scan cycle loop. Wakes every _DEFAULT_INTERVAL_SECONDS (or whatever
    the map specifies) and re-reads the map each cycle so live edits are
    picked up without a daemon restart."""
    while _stop_event is not None and not _stop_event.is_set():
        try:
            smap = load_map()
            interval = int(
                smap.get("supreme", {}).get(
                    "scan_interval_seconds", _DEFAULT_INTERVAL_SECONDS
                )
            )
            run_full_cycle(smap)
        except Exception as e:
            logger.exception("supreme: cycle crashed: %s", e)
            interval = _DEFAULT_INTERVAL_SECONDS
        # Sleep in small slices so a Ctrl-C / daemon restart isn't blocked
        # by the full interval. Event.wait() returns True when set, letting
        # the loop exit promptly on shutdown.
        if _stop_event is not None and _stop_event.wait(timeout=interval):
            break
    logger.info("supreme: scheduler thread exiting")


def start() -> bool:
    """Start the supreme scheduler thread if KAI_SUPREME_ENABLED=1.

    Returns True if the thread was started, False if disabled or already
    running. Safe to call from FastAPI lifespan startup.
    """
    global _thread, _stop_event
    if (os.environ.get("KAI_SUPREME_ENABLED") or "").strip() not in ("1", "true", "yes"):
        logger.info("supreme: scheduler not started (KAI_SUPREME_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("supreme: scheduler already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-supreme", daemon=True)
    _thread.start()
    logger.info("supreme: scheduler thread started")
    return True


def stop(timeout: float = 5.0) -> None:
    """Signal the scheduler to exit + wait up to `timeout` seconds. Used by
    FastAPI lifespan shutdown and by tests that want a clean teardown."""
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
    _thread = None
    _stop_event = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
