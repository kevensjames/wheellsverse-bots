"""Background scheduler — the persistent goal-loop heartbeat (KAI v1 build #4b).

Once per day at KAI_GOALS_HEARTBEAT_HOUR_UTC, assess every active goal via the
NON-DESTRUCTIVE engine.advance_active_goals(), and (optionally) Telegram-notify
the operator. Mirrors services/digest/scheduler.py:

  - opt-in via KAI_GOALS_HEARTBEAT_ENABLED=1 (standing approval for an
    unattended daily assess pass — the pass itself executes nothing),
  - each tick re-checks KAI_SCOPE_GOALS so toggling scope off stops it,
  - NO startup run (avoids a Telegram burst on every daemon restart),
  - one run per calendar day (deduped by YYYYMMDD).

The pass only records progress/next_action on goals. Turning a proposal into an
executable plan is a separate operator action (POST /admin/goals/{id}/approve-proposal).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _enabled() -> bool:
    return (os.environ.get("KAI_GOALS_HEARTBEAT_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _notify_enabled() -> bool:
    return (os.environ.get("KAI_GOALS_NOTIFY_TELEGRAM") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _scheduled_hour() -> int:
    raw = (os.environ.get("KAI_GOALS_HEARTBEAT_HOUR_UTC") or "8").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 8
    return max(0, min(h, 23))


def _scope_on() -> bool:
    try:
        from app.services.governance import is_scope_enabled
        return bool(is_scope_enabled("goals"))
    except Exception:
        return False


def _notify(results: list[dict]) -> bool:
    """Telegram-notify the operator when the pass found something noteworthy.
    Fail-soft: returns False on any error; never raises."""
    done = [r for r in results if r.get("status") == "done"]
    blocked = [r for r in results if r.get("status") == "blocked"]
    proposals = [r for r in results if r.get("proposed_next")]
    if not (done or blocked or proposals):
        return False
    lines = [
        "🎯 KAI goal loop",
        f"✓ done: {len(done)}  ⚠ blocked: {len(blocked)}  → proposals: {len(proposals)}",
    ]
    for r in proposals[:3]:
        lines.append(f"• {str(r.get('proposed_next', ''))[:120]}")
    try:
        from app.services.supreme.scanner import telegram_send
        return bool(telegram_send("\n".join(lines)))
    except Exception as e:  # noqa: BLE001
        logger.warning("goals: telegram notify failed: %s", e)
        return False


def run_cycle(*, notify: bool | None = None) -> dict:
    """Self-contained heartbeat run for the scheduler thread: opens its own DB
    session, builds the router, runs the NON-DESTRUCTIVE advance pass, and
    (optionally) notifies. Fail-soft: any wiring error degrades to a skipped
    result rather than crashing the loop."""
    from app.database import SessionLocal
    from app.services.goals import engine
    from app.services.router import build_default_router

    do_notify = _notify_enabled() if notify is None else notify
    session = None
    try:
        session = SessionLocal()
        rt = build_default_router(session)
        results = engine.advance_active_goals(router=rt, context="", prefer_local=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("goals: heartbeat cycle failed: %s", e)
        return {"advanced": 0, "results": [], "notified": False, "error": str(e)}
    finally:
        if session is not None:
            session.close()

    notified = _notify(results) if do_notify else False
    return {
        "advanced": len(results),
        "done": sum(1 for r in results if r.get("status") == "done"),
        "blocked": sum(1 for r in results if r.get("status") == "blocked"),
        "proposals": sum(1 for r in results if r.get("proposed_next")),
        "results": results,
        "notified": notified,
    }


def _loop() -> None:
    last_run_day: str | None = None
    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == _scheduled_hour() and today_key != last_run_day:
            if _scope_on():
                try:
                    res = run_cycle()
                    last_run_day = today_key  # mark done even if notify failed; retry tomorrow
                    logger.info("goals: heartbeat ran (advanced=%s notified=%s)",
                                res.get("advanced"), res.get("notified"))
                except Exception as e:
                    logger.exception("goals: heartbeat crashed: %s", e)
            else:
                logger.info("goals: heartbeat hour reached but KAI_SCOPE_GOALS off — skipping")
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break
    logger.info("goals: scheduler thread exiting")


def start() -> bool:
    """Start the scheduler thread if KAI_GOALS_HEARTBEAT_ENABLED=1. Returns True
    if started, False if disabled or already running."""
    global _thread, _stop_event
    if not _enabled():
        logger.info("goals: scheduler not started (KAI_GOALS_HEARTBEAT_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("goals: scheduler already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-goals", daemon=True)
    _thread.start()
    logger.info("goals: scheduler thread started (hour=%d UTC)", _scheduled_hour())
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
        "scope_on": _scope_on(),
        "notify": _notify_enabled(),
    }
