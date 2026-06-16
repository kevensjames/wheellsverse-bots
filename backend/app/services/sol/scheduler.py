"""Sol monthly scheduler — a daemon-thread tick that keeps circles moving.

Mirrors the digest/research/supreme scheduler pattern (in-process daemon thread,
60s poll, fires once/day at a UTC hour, scope-gated, graceful stop). But Sol's
tick is REMINDER-FIRST and NON-DESTRUCTIVE:

  * It scans active circles for due actions (collect / payout / advance).
  * Money actions (collect, payout) are surfaced as Telegram REMINDERS only —
    they stay behind the operator's approved=True gate. The scheduler never
    moves money.
  * Cycle ADVANCE (opening the next cycle — no money) happens automatically only
    when KAI_SOL_AUTOPILOT is set; otherwise it's a reminder too.

Gating:
  KAI_SOL_SCHEDULER_ENABLED=1   start the thread
  KAI_SOL_SCHEDULER_HOUR_UTC    hour to tick (default 14)
  KAI_SCOPE_SOL (or _SOL_*)     re-checked each cycle; off ⇒ skip
  KAI_SOL_AUTOPILOT=1           auto-open next cycles (still no money)
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
# Serializes the scheduled tick and a concurrent manual /scheduler/run-now so
# they can't both autopilot-advance the same circle (duplicate open_cycle).
_tick_lock = threading.Lock()


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _enabled() -> bool:
    return _truthy("KAI_SOL_SCHEDULER_ENABLED")


def _autopilot() -> bool:
    return _truthy("KAI_SOL_AUTOPILOT")


def _scheduled_hour() -> int:
    raw = (os.environ.get("KAI_SOL_SCHEDULER_HOUR_UTC") or "14").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 14
    return max(0, min(h, 23))


def _scope_on() -> bool:
    try:
        from app.services.governance import is_scope_enabled
        return bool(is_scope_enabled("sol"))
    except Exception:  # noqa: BLE001
        return False


def run_sol_tick(*, autopilot: bool | None = None, notify: bool = True) -> dict[str, Any]:
    """One scheduler tick. Self-contained (no request scope). Fail-soft.

    Scans due actions; if autopilot, auto-opens the next cycle for any paid
    circle (non-destructive); then notifies the operator of everything still
    needing a human (collect/payout approvals). Returns a summary dict.
    """
    if autopilot is None:
        autopilot = _autopilot()
    # Non-blocking: if a tick is already running (scheduled vs manual run-now),
    # skip rather than double-advance.
    if not _tick_lock.acquire(blocking=False):
        return {"scanned": 0, "due_actions": [], "advanced": [], "notified": False,
                "skipped": "tick already running"}
    try:
        return _run_sol_tick_locked(autopilot=autopilot, notify=notify)
    finally:
        _tick_lock.release()


def _run_sol_tick_locked(*, autopilot: bool, notify: bool) -> dict[str, Any]:
    try:
        from app.services.sol import engine
    except Exception as e:  # noqa: BLE001
        logger.warning("sol: tick import failed: %s", e)
        return {"scanned": 0, "due_actions": [], "advanced": [], "notified": False,
                "error": str(e)}

    advanced: list[dict[str, Any]] = []
    try:
        actions = engine.scan_due_actions()
        if autopilot:
            for a in [x for x in actions if x["action"] == "advance_ready"]:
                try:
                    res = engine.advance_circle(a["circle_id"])
                    advanced.append({"circle_id": a["circle_id"], "result": res})
                except Exception as e:  # noqa: BLE001
                    logger.warning("sol: autopilot advance circle %s failed: %s",
                                   a["circle_id"], e)
            # Re-scan so the freshly opened cycles show as collect_due.
            actions = engine.scan_due_actions()
    except Exception as e:  # noqa: BLE001
        logger.exception("sol: tick scan failed: %s", e)
        return {"scanned": 0, "due_actions": [], "advanced": advanced,
                "notified": False, "error": str(e)}

    sent = False
    if notify and (actions or advanced):
        try:
            sent = _notify_operator(actions, advanced)
        except Exception as e:  # noqa: BLE001
            logger.warning("sol: tick notify failed: %s", e)

    return {"scanned": len(actions), "due_actions": actions,
            "advanced": advanced, "notified": sent}


def _notify_operator(actions: list[dict[str, Any]], advanced: list[dict[str, Any]]) -> bool:
    from app.services import observability
    esc = observability._html_escape
    lines = ["☀️ <b>Sol circles — daily check</b>"]
    if advanced:
        lines.append(f"• auto-opened {len(advanced)} next cycle(s)")
    due = {"collect_due": [], "retry_due": [], "payout_ready": [], "advance_ready": []}
    for a in actions:
        due.setdefault(a["action"], []).append(a)
    if due["collect_due"]:
        lines.append(f"\n💵 <b>Collection due</b> ({len(due['collect_due'])}) — approve in dashboard:")
        for a in due["collect_due"][:10]:
            lines.append(f"  • {esc(a['circle_name'])} · cycle {a['cycle_number']} — {esc(a['detail'])}")
    if due["retry_due"]:
        lines.append(f"\n🔁 <b>Retryable failures</b> ({len(due['retry_due'])}):")
        for a in due["retry_due"][:10]:
            lines.append(f"  • {esc(a['circle_name'])} · cycle {a['cycle_number']} — {esc(a['detail'])}")
    if due["payout_ready"]:
        lines.append(f"\n🏦 <b>Payout ready</b> ({len(due['payout_ready'])}):")
        for a in due["payout_ready"][:10]:
            lines.append(f"  • {esc(a['circle_name'])} · cycle {a['cycle_number']} — {esc(a['detail'])}")
    if due["advance_ready"]:
        lines.append(f"\n➡️ <b>Ready to advance</b> ({len(due['advance_ready'])})")
    observability.notify("\n".join(lines))
    return True


# ─── thread lifecycle (mirrors digest/research/supreme) ───────────────
def _loop() -> None:
    last_tick_day: str | None = None
    while _stop_event is not None and not _stop_event.is_set():
        now = datetime.now(timezone.utc)
        today_key = now.strftime("%Y%m%d")
        if now.hour == _scheduled_hour() and today_key != last_tick_day:
            if _scope_on():
                try:
                    res = run_sol_tick()
                    last_tick_day = today_key  # mark done even if notify failed
                    logger.info("sol: scheduled tick (due=%d advanced=%d notified=%s)",
                                res.get("scanned", 0), len(res.get("advanced", [])),
                                res.get("notified"))
                except Exception as e:  # noqa: BLE001
                    logger.exception("sol: scheduled tick crashed: %s", e)
            else:
                logger.info("sol: scheduled hour reached but KAI_SCOPE_SOL off — skipping")
        if _stop_event is not None and _stop_event.wait(timeout=_POLL_INTERVAL_SECONDS):
            break


def start() -> bool:
    global _thread, _stop_event
    if not _enabled():
        logger.info("sol: scheduler not started (KAI_SOL_SCHEDULER_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("sol: scheduler already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-sol", daemon=True)
    _thread.start()
    logger.info("sol: scheduler thread started (hour=%d UTC, autopilot=%s)",
                _scheduled_hour(), _autopilot())
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
    return {
        "enabled": _enabled(),
        "running": is_running(),
        "hour_utc": _scheduled_hour(),
        "autopilot": _autopilot(),
        "scope_on": _scope_on(),
    }
