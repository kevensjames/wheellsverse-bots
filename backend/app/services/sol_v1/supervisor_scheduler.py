"""Sol v1 supervisor scheduler — daily read-only integrity + health sweep.

Mirrors reminder_scheduler: one opt-in daemon thread, fires ONCE per day at a UTC
hour, with a durable per-day run-marker so a restart within the hour doesn't
re-alert. Opt-in via SOL_V1_SUPERVISOR_ENABLED=1.

Each pass runs supervisor.run_checks (READ-ONLY — no writes, no money) and, only
when there's something worth saying (an integrity violation, or non-zero
overdue/unconfirmed/stuck-dispute counts), pushes a summary to the operator's
Telegram. It NEVER auto-fixes; the operator investigates.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _marker_path() -> Path:
    return Path(tempfile.gettempdir()) / "sol_v1_supervisor_last_run"


def _read_marker() -> str | None:
    try:
        return _marker_path().read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def _write_marker(day_key: str) -> None:
    try:
        _marker_path().write_text(day_key, encoding="utf-8")
    except Exception as e:
        logger.warning("sol_v1 supervisor: could not persist run marker: %s", e)


def _enabled() -> bool:
    return (os.environ.get("SOL_V1_SUPERVISOR_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _scheduled_hour() -> int:
    raw = (os.environ.get("SOL_V1_SUPERVISOR_HOUR_UTC") or "15").strip()
    try:
        return max(0, min(int(raw), 23))
    except ValueError:
        return 15


def run_once() -> dict:
    """Open a session, run the supervisor, alert if noteworthy. Fail-soft."""
    from app.database import SessionLocal
    from app.services import observability
    from app.services.sol_v1 import supervisor

    today = datetime.now(timezone.utc).date()
    session = SessionLocal()
    try:
        report = supervisor.run_checks(session, today)
    finally:
        session.close()
    if supervisor.is_noteworthy(report):
        observability.notify(supervisor.build_alert(report))
    logger.info(
        "sol_v1 supervisor: ok=%s violations=%d health=%s",
        report["ok"], len(report["integrity_violations"]), report["health"],
    )
    return report


def _loop() -> None:
    last_run_day = _read_marker()
    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == _scheduled_hour() and today_key != last_run_day:
            try:
                run_once()
            except Exception as e:
                logger.exception("sol_v1 supervisor: cycle crashed: %s", e)
            last_run_day = today_key
            _write_marker(today_key)
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break
    logger.info("sol_v1 supervisor: scheduler thread exiting")


def start() -> bool:
    """Start the thread iff SOL_V1_SUPERVISOR_ENABLED=1 (and not already running)."""
    global _thread, _stop_event
    if not _enabled():
        logger.info("sol_v1 supervisor: not started (SOL_V1_SUPERVISOR_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("sol_v1 supervisor: already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="sol-v1-supervisor", daemon=True)
    _thread.start()
    logger.info("sol_v1 supervisor: scheduler started (hour=%d UTC)", _scheduled_hour())
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


def status() -> dict[str, object]:
    return {
        "enabled": _enabled(),
        "running": is_running(),
        "hour_utc": _scheduled_hour(),
    }
