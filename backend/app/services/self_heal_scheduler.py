"""Background scheduler for KAI's bounded self-healing.

Runs `self_heal.heal(apply=True)` every N seconds inside the uvicorn daemon
(daemon thread, same pattern as the Supreme scheduler) so the safe auto-fixes
happen autonomously — no human in the loop for the boring/common cases.

Triple-gated, by design:
  - KAI_SELF_HEAL_SCHEDULER_ENABLED=1   starts the loop (default off)
  - is_scope_enabled("self_heal")        re-checked every tick
  - self_heal.self_heal_enabled()        re-checked inside heal()
And the only thing it can ever DO is the safe + reversible allowlist
(extend OLLAMA_MODEL_MAP, clean __pycache__) — never code/commits/process kills.
So even running unattended, the blast radius is bounded.
"""
from __future__ import annotations

import logging
import os
import threading

from app.services import self_heal

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 1800  # 30 min
_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None


def _interval() -> int:
    try:
        return max(60, int(os.environ.get("KAI_SELF_HEAL_INTERVAL_SECONDS", "") or _DEFAULT_INTERVAL_SECONDS))
    except ValueError:
        return _DEFAULT_INTERVAL_SECONDS


def _scope_on() -> bool:
    try:
        from app.services.governance import is_scope_enabled
        return bool(is_scope_enabled("self_heal"))
    except Exception:
        return False


def _loop() -> None:
    while _stop_event is not None and not _stop_event.is_set():
        try:
            # Re-check gates every tick so the operator can disable live.
            if _scope_on() and self_heal.self_heal_enabled():
                report = self_heal.heal(apply=True)
                applied = report.get("applied", [])
                if applied:
                    logger.info(
                        "self_heal: auto-fixed %d issue(s): %s",
                        len(applied), [a.get("kind") for a in applied],
                    )
            else:
                logger.debug("self_heal: tick skipped (scope/kill-switch off)")
        except Exception as e:
            logger.exception("self_heal: scheduler cycle crashed: %s", e)
        if _stop_event is not None and _stop_event.wait(timeout=_interval()):
            break
    logger.info("self_heal: scheduler thread exiting")


def start() -> bool:
    """Start the loop if KAI_SELF_HEAL_SCHEDULER_ENABLED=1. Safe to call from
    FastAPI startup. Returns True if started."""
    global _thread, _stop_event
    if (os.environ.get("KAI_SELF_HEAL_SCHEDULER_ENABLED") or "").strip().lower() not in ("1", "true", "yes"):
        logger.info("self_heal: scheduler not started (KAI_SELF_HEAL_SCHEDULER_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        logger.info("self_heal: scheduler already running")
        return False
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, name="kai-self-heal", daemon=True)
    _thread.start()
    logger.info("self_heal: scheduler thread started (interval=%ss)", _interval())
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
