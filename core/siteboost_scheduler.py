"""SiteBoost scan scheduler — file-backed, no external cron required.

Schedules live at SITEBOOST_SCHEDULES_PATH (default: data/launches/siteboost/schedules.json,
production overrides to /var/data/siteboost/schedules.json for volume persistence).

Each schedule:
    id            UUID12
    name          operator-friendly label
    location      "Fall River, MA"
    hour          0-23 (UTC)
    days_of_week  list of 0-6 (Mon=0, Sun=6) — only fires on these days
    radius_m, limit, live  — passed straight through to scan
    enabled       bool — disable to pause without deleting
    last_run_at   ISO timestamp of the most recent fire
    created_at    when the schedule was added

Worker is a daemon thread that polls every 60 seconds. On each tick, finds
schedules where:
    1. enabled == True
    2. today's weekday is in days_of_week
    3. current UTC hour == schedule.hour
    4. last_run_at doesn't start with today's date (i.e. hasn't already fired today)

Then calls fire_callback(schedule) for each due one. The callback is responsible
for actually launching the scan (we keep this module ignorant of FastAPI internals).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger("siteboost_scheduler")

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT = ROOT / "data" / "launches" / "siteboost" / "schedules.json"
SCHEDULES_PATH = Path(os.getenv("SITEBOOST_SCHEDULES_PATH", str(_DEFAULT)))


def _load_schedules() -> list[dict]:
    if not SCHEDULES_PATH.exists():
        return []
    try:
        return json.loads(SCHEDULES_PATH.read_text())
    except Exception as e:
        logger.warning(f"schedules load failed: {e}")
        return []


def _save_schedules(schedules: list[dict]) -> None:
    SCHEDULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(schedules, indent=2))
    tmp.replace(SCHEDULES_PATH)


def list_schedules() -> list[dict]:
    return _load_schedules()


def add_schedule(*, name: str, location: str, hour: int,
                  days_of_week: list[int],
                  radius_m: int = 10000, limit: int = 50, live: bool = True) -> dict:
    sched = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "location": location,
        "hour": int(hour),
        "days_of_week": sorted({int(d) for d in days_of_week if 0 <= int(d) <= 6}),
        "radius_m": int(radius_m),
        "limit": int(limit),
        "live": bool(live),
        "enabled": True,
        "last_run_at": "",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    schedules = _load_schedules()
    schedules.append(sched)
    _save_schedules(schedules)
    return sched


def remove_schedule(schedule_id: str) -> bool:
    schedules = _load_schedules()
    new = [s for s in schedules if s.get("id") != schedule_id]
    if len(new) == len(schedules):
        return False
    _save_schedules(new)
    return True


def toggle_schedule(schedule_id: str, enabled: bool) -> bool:
    schedules = _load_schedules()
    for s in schedules:
        if s.get("id") == schedule_id:
            s["enabled"] = enabled
            _save_schedules(schedules)
            return True
    return False


def get_schedule(schedule_id: str) -> dict | None:
    for s in _load_schedules():
        if s.get("id") == schedule_id:
            return s
    return None


def mark_run(schedule_id: str) -> None:
    schedules = _load_schedules()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for s in schedules:
        if s.get("id") == schedule_id:
            s["last_run_at"] = now
            _save_schedules(schedules)
            return


def find_due(now_utc=None) -> list[dict]:
    """Return schedules that should fire right now (current UTC tick)."""
    if now_utc is None:
        now_utc = time.gmtime()
    today_prefix = time.strftime("%Y-%m-%d", now_utc)
    out = []
    for s in _load_schedules():
        if not s.get("enabled"):
            continue
        if now_utc.tm_wday not in s.get("days_of_week", []):
            continue
        if now_utc.tm_hour != s.get("hour"):
            continue
        # Already fired today? Don't double-fire even if the worker ticks twice in one hour.
        if (s.get("last_run_at") or "").startswith(today_prefix):
            continue
        out.append(s)
    return out


_worker_started = False
_worker_lock = threading.Lock()


def start_worker(fire_callback) -> None:
    """Start the background ticker (idempotent — safe to call from each request).

    fire_callback(schedule_dict) is invoked for each due schedule. Caller is
    responsible for launching the actual scan in-process (we keep the scheduler
    module unaware of FastAPI / threading.Thread internals).
    """
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    def _loop() -> None:
        logger.info(f"scheduler worker started; reading from {SCHEDULES_PATH}")
        while True:
            try:
                due = find_due()
                for s in due:
                    logger.info(f"firing schedule {s.get('id')!r} name={s.get('name')!r}")
                    try:
                        fire_callback(s)
                        mark_run(s["id"])
                    except Exception as e:
                        logger.error(f"fire failed for {s.get('id')!r}: {e}")
            except Exception as e:
                logger.error(f"scheduler tick error: {e}")
            time.sleep(60)

    t = threading.Thread(target=_loop, daemon=True, name="siteboost-scheduler")
    t.start()
