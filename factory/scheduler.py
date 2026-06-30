"""The nightly Factory daemon. Two gates every sweep: kill-switch (FACTORY_KILL)
halts immediately; dormancy (FACTORY_ENABLED) does nothing until armed. Mirrors
core.portfolio.orchestrator. run_once ticks each ACTIVE project once and writes a
morning report. Ships dormant."""
from __future__ import annotations

import logging
import os
import threading
import time

from factory import paths, pipeline, project as projects, report

logger = logging.getLogger("factory_scheduler")


def _control() -> dict:
    cfg = paths.load_json(paths.data_root() / "portfolio.json", {}) or {}
    return cfg.get("control", {}) or {}


def is_enabled() -> bool:
    return os.getenv("FACTORY_ENABLED") == "1" or bool(_control().get("enabled"))


def kill_engaged() -> bool:
    return os.getenv("FACTORY_KILL") == "1" or bool(_control().get("kill"))


def _set_control(key: str, value: bool) -> None:
    f = paths.data_root() / "portfolio.json"
    cfg = paths.load_json(f, {}) or {}
    cfg.setdefault("control", {})[key] = bool(value)
    paths.save_json_atomic(f, cfg)


def set_enabled(enabled: bool) -> None:
    _set_control("enabled", enabled)


def engage_kill() -> None:
    _set_control("kill", True)


def disengage_kill() -> None:
    _set_control("kill", False)


def control_state() -> dict:
    return {"enabled": is_enabled(), "kill": kill_engaged()}


def run_once(runner, *, now_iso: str, slugs: list[str] | None = None) -> dict:
    if kill_engaged():
        return {"status": "killed", "ticked": {}}
    if not is_enabled():
        return {"status": "dormant", "ticked": {}}

    target = slugs if slugs is not None else [p.slug for p in projects.list_active()]
    ticked: dict[str, str] = {}
    date = now_iso[:10]
    for slug in target:
        try:
            res = pipeline.run_cycle(slug, runner, now_iso=now_iso)
            ticked[slug] = res.status
            if res.status in ("completed", "blocked"):
                report.write_report(slug, {
                    "cycle_id": res.cycle_id, "slug": slug, "task_id": res.task_id,
                    "status": res.status, "stages": res.stages, "pr_url": res.pr_url,
                    "cost_usd": res.cost_usd, "at": now_iso,
                }, date=date)
        except Exception as e:  # fail-soft: one project's failure never stops the sweep
            logger.error(f"factory tick failed for {slug!r}: {e}")
            ticked[slug] = "error"
    return {"status": "ran", "ticked": ticked}


_worker_started = False
_worker_lock = threading.Lock()


def start_worker(runner, *, interval_s: int = 60) -> None:
    """Idempotent nightly worker. Wakes every interval, fires run_once at the
    configured local hour (FACTORY_TICK_HOUR, default 2) at most once per day.
    Time is read here (not in run_once) so the testable core stays deterministic."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    hour = int(os.getenv("FACTORY_TICK_HOUR", "2"))

    def _loop() -> None:
        last_date = None
        logger.info(f"factory worker started (tick hour={hour}, enabled={is_enabled()})")
        while True:
            try:
                lt = time.localtime()
                today = time.strftime("%Y-%m-%d", lt)
                if lt.tm_hour == hour and today != last_date and not kill_engaged() and is_enabled():
                    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    run_once(runner, now_iso=now_iso)
                    last_date = today
            except Exception as e:
                logger.error(f"factory worker cycle error: {e}")
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, daemon=True, name="factory-scheduler")
    t.start()
