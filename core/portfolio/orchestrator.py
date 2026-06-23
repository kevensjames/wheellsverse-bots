"""W-MOS Master Supervisor: the autonomous sweep over all businesses.

Two active gates, every cycle:
  1. kill-switch  (WMOS_KILL=1)               -> halt immediately
  2. dormant      (WMOS_ORCHESTRATOR_ENABLED) -> do nothing until armed

Deferred gates:
  3. budget       (budget.would_exceed)       -> [DEFERRED — not enforced in this sweep yet;
                                                   wired later via the auto_capped
                                                   under_cost_ceiling precondition]

Ships dormant. Arm only after hand-verifying ticks tick-by-tick (see plan §scope).
Mirrors core/siteboost_scheduler.start_worker for the daemon-thread pattern.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from core.portfolio import loops, registry, state

logger = logging.getLogger("wmos_orchestrator")


def is_enabled() -> bool:
    return os.getenv("WMOS_ORCHESTRATOR_ENABLED") == "1"


def kill_engaged() -> bool:
    return os.getenv("WMOS_KILL") == "1"


def run_once(adapter_for, ctx_for, *, slugs: list[str] | None = None) -> dict:
    if kill_engaged():
        return {"status": "killed", "ticked": {}}
    if not is_enabled():
        return {"status": "dormant", "ticked": {}}

    target = slugs if slugs is not None else [b.slug for b in registry.list_businesses()]
    ticked: dict[str, str | None] = {}
    for slug in target:
        try:
            result = loops.tick(slug, adapter_for, ctx_for)
            ticked[slug] = result.status if result is not None else None
        except Exception as e:
            logger.error(f"tick failed for {slug!r}: {e}")
            ticked[slug] = "error"
    state.audit({"verb": "_sweep", "status": "ran", "businesses": list(ticked.keys())})
    return {"status": "ran", "ticked": ticked}


_worker_started = False
_worker_lock = threading.Lock()


def start_worker(adapter_for, ctx_for, interval_s: int = 300) -> None:
    """Idempotent background sweeper. Safe to call repeatedly; only one thread runs.
    While dormant the cycle is a cheap no-op (run_once returns immediately)."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    def _loop() -> None:
        logger.info(f"wmos orchestrator worker started (interval={interval_s}s, "
                    f"enabled={is_enabled()})")
        while True:
            try:
                if not kill_engaged() and is_enabled():
                    run_once(adapter_for, ctx_for)
            except Exception as e:
                logger.error(f"orchestrator cycle error: {e}")
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, daemon=True, name="wmos-orchestrator")
    t.start()
