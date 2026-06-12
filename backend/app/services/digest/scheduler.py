"""Background scheduler — auto-sends the Operator Digest once per day.

Mirrors services/research/scheduler.py (single daemon thread, opt-in via env,
minute-poll sleep loop). Two deliberate differences from research:

  1. NO startup cycle. The digest PUSHES to Telegram, so firing on every daemon
     restart would spam the operator. It only sends at the scheduled hour.
  2. Doubly gated. The thread starts only if KAI_DIGEST_SCHEDULER_ENABLED=1
     (the operator's standing approval for an unattended daily send — the
     manual endpoint's per-run approved=true can't apply to a cron), AND each
     cycle re-checks KAI_SCOPE_DIGEST so toggling the feature scope off also
     stops the auto-send.

Cadence:
  - KAI_DIGEST_HOUR_UTC (default 13 ≈ morning in the US) — wake at that UTC hour
  - one send per calendar day (deduped by YYYYMMDD)
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

from app.services.digest.digest import run_digest_cycle

logger = logging.getLogger(__name__)

# Wake every minute and check whether it's the scheduled hour (avoids 24h-sleep
# drift; same approach as the research/supreme schedulers).
_POLL_INTERVAL_SECONDS = 60

_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _enabled() -> bool:
    return (os.environ.get("KAI_DIGEST_SCHEDULER_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _scheduled_hour() -> int:
    raw = (os.environ.get("KAI_DIGEST_HOUR_UTC") or "13").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 13
    return max(0, min(h, 23))


def _scope_on() -> bool:
    try:
        from app.services.governance import is_scope_enabled
        return bool(is_scope_enabled("digest"))
    except Exception:
        return False


def _loop() -> None:
    """Once per day at the scheduled UTC hour, send the digest — but only while
    KAI_SCOPE_DIGEST is on. Re-reads env each tick so live edits to the hour or
    the scope flag apply without a restart."""
    last_sent_day: str | None = None
    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == _scheduled_hour() and today_key != last_sent_day:
            if _scope_on():
                try:
                    res = run_digest_cycle(deliver=True)
                    last_sent_day = today_key  # mark done even if send failed; retry tomorrow
                    logger.info("digest: scheduled send (sent=%s)", res.get("sent"))
                except Exception as e:
                    logger.exception("digest: scheduled cycle crashed: %s", e)
            else:
                # Scope off — skip this hour but don't mark the day done, so
                # re-enabling the scope later in the same hour still sends.
                logger.info("digest: scheduled hour reached but KAI_SCOPE_DIGEST off — skipping")
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break
    logger.info("digest: scheduler thread exiting")


def start() -> bool:
    """Start the scheduler thread if KAI_DIGEST_SCHEDULER_ENABLED=1. Returns
    True if started, False if disabled or already running."""
    global _thread, _stop_event
    if not _enabled():
        logger.info("digest: scheduler not started (KAI_DIGEST_SCHEDULER_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("digest: scheduler already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-digest", daemon=True)
    _thread.start()
    logger.info("digest: scheduler thread started (hour=%d UTC)", _scheduled_hour())
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
    """For the admin status endpoint — what the operator needs to confirm the
    cron is live without reading logs."""
    return {
        "enabled": _enabled(),
        "running": is_running(),
        "hour_utc": _scheduled_hour(),
        "scope_on": _scope_on(),
    }
