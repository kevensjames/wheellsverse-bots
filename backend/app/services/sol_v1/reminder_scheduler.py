"""Sol v1 reminder scheduler — daily overdue-sweep + operator digest.

Mirrors services/digest/scheduler.py: a single opt-in daemon thread that wakes
every minute and fires ONCE per day at a UTC hour. Deliberately:

  - NO startup send, plus a per-day run-marker persisted to the temp dir so a
    restart WITHIN the scheduled hour doesn't re-send the same day's digest
    (the in-memory dedup alone resets on restart).
  - Opt-in via SOL_V1_REMINDERS_ENABLED=1 (the operator's standing approval for
    an unattended daily job). Distinct from the legacy custodial sol scheduler
    (KAI_SOL_SCHEDULER_ENABLED) — different product, different flag.

Each cycle: flip overdue 'pending' payments → 'late', summarize open
obligations, and push a digest to Telegram. NON-CUSTODIAL: it only labels rows
and notifies; no money moves.
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
    """A tiny file holding the last day (YYYYMMDD) a cycle ran. Lives in the temp
    dir so it survives launchd/watchdog process restarts within the send hour."""
    return Path(tempfile.gettempdir()) / "sol_v1_reminders_last_run"


def _read_marker() -> str | None:
    try:
        return _marker_path().read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def _write_marker(day_key: str) -> None:
    try:
        _marker_path().write_text(day_key, encoding="utf-8")
    except Exception as e:  # never let a marker write kill the loop
        logger.warning("sol_v1 reminders: could not persist run marker: %s", e)


def _enabled() -> bool:
    return (os.environ.get("SOL_V1_REMINDERS_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _scheduled_hour() -> int:
    raw = (os.environ.get("SOL_V1_REMINDERS_HOUR_UTC") or "14").strip()
    try:
        return max(0, min(int(raw), 23))
    except ValueError:
        return 14


def run_once() -> dict:
    """Open a session, run one reminder cycle, deliver the digest. Fail-soft."""
    from app.database import SessionLocal
    from app.services import observability
    from app.services.sol_v1 import reminders

    # date.today() at the daemon's local tz is fine for a due-date sweep; dates
    # are date-only (no tz) in the ledger.
    today = datetime.now(timezone.utc).date()
    session = SessionLocal()
    try:
        result = reminders.run_reminder_cycle(session, today)
    finally:
        session.close()
    # Only ping the operator when there's something to say — including an
    # outstanding dispute (which strands a cycle until it's resolved).
    s = result["summary"]
    if result["marked_late"] or s.get("disputed") or any(
        s.get(k) for k in ("overdue", "due_today", "upcoming")
    ):
        observability.notify(result["digest"])
    logger.info(
        "sol_v1 reminders: marked_late=%s summary=%s",
        result["marked_late"], result["summary"],
    )
    return result


def _loop() -> None:
    # Seed from the durable marker so a restart inside the send hour, after the
    # day already ran, does NOT re-fire.
    last_run_day = _read_marker()
    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == _scheduled_hour() and today_key != last_run_day:
            try:
                run_once()
            except Exception as e:  # never let the thread die
                logger.exception("sol_v1 reminders: cycle crashed: %s", e)
            last_run_day = today_key  # mark done even on failure; retry tomorrow
            _write_marker(today_key)  # survive restarts within the send hour
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break
    logger.info("sol_v1 reminders: scheduler thread exiting")


def start() -> bool:
    """Start the thread iff SOL_V1_REMINDERS_ENABLED=1 (and not already running)."""
    global _thread, _stop_event
    if not _enabled():
        logger.info("sol_v1 reminders: not started (SOL_V1_REMINDERS_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("sol_v1 reminders: already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="sol-v1-reminders", daemon=True)
    _thread.start()
    logger.info("sol_v1 reminders: scheduler started (hour=%d UTC)", _scheduled_hour())
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
