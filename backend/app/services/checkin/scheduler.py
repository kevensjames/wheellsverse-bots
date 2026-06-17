"""Daily check-in scheduler — a daemon thread that sends one warm check-in/day.

Mirrors the digest/sol scheduler pattern (60s poll, fire once/day at a UTC hour,
dedup by calendar day, scope-gated, graceful stop). The check-in is a PROACTIVE
Telegram message (KAI reaching out), not a prompt layer.

Config (.env):
  KAI_CHECKIN_SCHEDULER_ENABLED=1   start the thread (off by default)
  KAI_CHECKIN_HOUR_UTC=13           hour to send (default 13)
  KAI_SCOPE_CHECKIN=1               scope gate (re-checked each cycle)
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _enabled() -> bool:
    return _truthy("KAI_CHECKIN_SCHEDULER_ENABLED")


def _scheduled_hour() -> int:
    raw = (os.environ.get("KAI_CHECKIN_HOUR_UTC") or "13").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 13
    return max(0, min(h, 23))


def _scope_on() -> bool:
    try:
        from app.services.governance import is_scope_enabled
        return bool(is_scope_enabled("checkin"))
    except Exception:  # pragma: no cover
        return False


def run_checkin(*, force: bool = False, deliver: bool = True) -> dict[str, Any]:
    """Compose + (optionally) send today's check-in. Idempotent per day unless
    force=True. Fail-soft. Returns {sent, already_done, message}."""
    date_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        from app.services.checkin import composer, storage
    except Exception as e:  # pragma: no cover
        logger.warning("checkin: import failed (%s)", e)
        return {"sent": False, "already_done": False, "message": "", "error": str(e)}

    if not force and storage.has_checkin(date_key):
        return {"sent": False, "already_done": True, "message": ""}

    message = composer.compose_checkin()
    # CLAIM the day BEFORE sending (UNIQUE date_key). Only the caller that wins the
    # insert sends — so a manual run-now racing the scheduled tick can't double-send.
    rec = storage.record_checkin(date_key, message, sent=False)
    if rec is None and not force:  # someone else already claimed today
        return {"sent": False, "already_done": True, "message": message}

    sent = False
    if deliver:
        try:
            from app.services import observability
            observability.notify("🌅 <b>KAI check-in</b>\n" + observability._html_escape(message))
            sent = True
            storage.set_sent(date_key, True)
        except Exception as e:  # pragma: no cover
            logger.warning("checkin: send failed (%s)", e)
    return {"sent": sent, "already_done": False, "message": message}


def _loop() -> None:
    last_day: str | None = None
    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == _scheduled_hour() and today_key != last_day:
            if _scope_on():
                try:
                    res = run_checkin()
                    last_day = today_key  # mark done even if send failed
                    logger.info("checkin: scheduled (sent=%s already=%s)",
                                res.get("sent"), res.get("already_done"))
                except Exception as e:  # pragma: no cover
                    logger.exception("checkin: scheduled cycle crashed: %s", e)
            else:
                logger.info("checkin: scheduled hour reached but KAI_SCOPE_CHECKIN off — skipping")
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break


def start() -> bool:
    global _thread, _stop_event
    if not _enabled():
        logger.info("checkin: scheduler not started (KAI_CHECKIN_SCHEDULER_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-checkin", daemon=True)
    _thread.start()
    logger.info("checkin: scheduler thread started (hour=%d UTC)", _scheduled_hour())
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


def status() -> dict[str, Any]:
    return {"enabled": _enabled(), "running": is_running(),
            "hour_utc": _scheduled_hour(), "scope_on": _scope_on()}
