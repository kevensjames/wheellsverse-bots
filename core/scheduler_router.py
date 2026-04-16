#!/usr/bin/env python3
"""
core/scheduler_router.py
─────────────────────────────────────────────────────────────────────────────
Bot scheduler API — leverages APScheduler.

GET    /api/scheduler/jobs            — list all jobs
POST   /api/scheduler/jobs            — create job
PATCH  /api/scheduler/jobs/{id}       — update (enable/disable/reschedule)
DELETE /api/scheduler/jobs/{id}       — delete job
POST   /api/scheduler/jobs/{id}/run-now — trigger immediately
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.chat_db import _get_conn, _lock

logger = logging.getLogger("scheduler_router")
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

_scheduler = None


def _get_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.start()
        logger.info("[scheduler] APScheduler started")
    except Exception as e:
        logger.warning(f"[scheduler] APScheduler failed to start: {e}")
    return _scheduler


def _run_job(bot_name: str, category: str, job_id: str):
    """Execute a scheduled bot run."""
    try:
        from core.bot_manager import start_bot
        start_bot(bot_name, category)
        conn = _get_conn()
        with _lock:
            conn.execute(
                "UPDATE scheduled_jobs SET last_run=?,run_count=run_count+1 WHERE id=?",
                (datetime.utcnow().isoformat(), job_id)
            )
            conn.commit()
        logger.info(f"[scheduler] Ran bot {bot_name} (job {job_id})")
    except Exception as e:
        logger.error(f"[scheduler] Job {job_id} failed: {e}")


def _register_job(job: dict):
    """Register a job with APScheduler."""
    sched = _get_scheduler()
    if sched is None:
        return
    try:
        job_id = job["id"]
        # Remove existing
        try:
            sched.remove_job(job_id)
        except Exception:
            pass
        if not job.get("enabled", True):
            return
        sched_type = job.get("schedule_type", "interval")
        value = job.get("schedule_value", "60")
        if sched_type == "cron":
            parts = value.split()
            if len(parts) == 5:
                sched.add_job(
                    _run_job, "cron",
                    id=job_id,
                    args=[job["bot_name"], job.get("category", ""), job_id],
                    minute=parts[0], hour=parts[1], day=parts[2],
                    month=parts[3], day_of_week=parts[4],
                    replace_existing=True,
                )
        else:
            minutes = int(value) if str(value).isdigit() else 60
            sched.add_job(
                _run_job, "interval",
                id=job_id,
                args=[job["bot_name"], job.get("category", ""), job_id],
                minutes=minutes,
                replace_existing=True,
            )
    except Exception as e:
        logger.error(f"[scheduler] Register job error: {e}")


def _load_jobs_from_db():
    """Load all enabled jobs from DB and register with APScheduler."""
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id,name,bot_name,category,schedule_type,schedule_value,enabled FROM scheduled_jobs WHERE enabled=1"
        ).fetchall()
    for row in rows:
        job = {
            "id": row[0], "name": row[1], "bot_name": row[2],
            "category": row[3], "schedule_type": row[4],
            "schedule_value": row[5], "enabled": bool(row[6])
        }
        _register_job(job)


# Load jobs on module import
try:
    _load_jobs_from_db()
except Exception:
    pass


class JobCreate(BaseModel):
    name: str
    bot_name: str
    category: str = ""
    schedule_type: str = "interval"   # interval | cron
    schedule_value: str = "60"        # minutes or "0 8 * * *"
    enabled: bool = True


class JobUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    schedule_type: Optional[str] = None
    schedule_value: Optional[str] = None


def _row_to_job(row) -> dict:
    keys = ["id", "name", "bot_name", "category", "schedule_type", "schedule_value",
            "enabled", "last_run", "next_run", "run_count"]
    d = dict(zip(keys, row))
    d["enabled"] = bool(d["enabled"])
    # Get next run from APScheduler
    sched = _get_scheduler()
    if sched:
        try:
            apjob = sched.get_job(d["id"])
            if apjob and apjob.next_run_time:
                d["next_run"] = apjob.next_run_time.isoformat()
        except Exception:
            pass
    return d


@router.get("/jobs")
def scheduler_list():
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id,name,bot_name,category,schedule_type,schedule_value,enabled,last_run,next_run,run_count "
            "FROM scheduled_jobs ORDER BY name"
        ).fetchall()
    return {"jobs": [_row_to_job(r) for r in rows]}


@router.post("/jobs")
def scheduler_create(req: JobCreate):
    job_id = str(uuid.uuid4())
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO scheduled_jobs(id,name,bot_name,category,schedule_type,schedule_value,enabled,run_count) "
            "VALUES(?,?,?,?,?,?,?,0)",
            (job_id, req.name, req.bot_name, req.category,
             req.schedule_type, req.schedule_value, int(req.enabled))
        )
        conn.commit()
    job = {"id": job_id, "name": req.name, "bot_name": req.bot_name,
           "category": req.category, "schedule_type": req.schedule_type,
           "schedule_value": req.schedule_value, "enabled": req.enabled}
    _register_job(job)
    return {"id": job_id, "created": True}


@router.patch("/jobs/{job_id}")
def scheduler_update(job_id: str, req: JobUpdate):
    conn = _get_conn()
    with _lock:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    fields, vals = [], []
    if req.name is not None:
        fields.append("name=?")
        vals.append(req.name)
    if req.enabled is not None:
        fields.append("enabled=?")
        vals.append(int(req.enabled))
    if req.schedule_type is not None:
        fields.append("schedule_type=?")
        vals.append(req.schedule_type)
    if req.schedule_value is not None:
        fields.append("schedule_value=?")
        vals.append(req.schedule_value)
    if fields:
        vals.append(job_id)
        with _lock:
            conn.execute(f"UPDATE scheduled_jobs SET {', '.join(fields)} WHERE id=?", vals)
            conn.commit()
        # Re-register
        with _lock:
            row2 = conn.execute(
                "SELECT id,name,bot_name,category,schedule_type,schedule_value,enabled FROM scheduled_jobs WHERE id=?",
                (job_id,)
            ).fetchone()
        if row2:
            _register_job(dict(zip(["id", "name", "bot_name", "category", "schedule_type", "schedule_value", "enabled"], row2)))
    return {"updated": True}


@router.delete("/jobs/{job_id}")
def scheduler_delete(job_id: str):
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
        conn.commit()
    sched = _get_scheduler()
    if sched:
        try:
            sched.remove_job(job_id)
        except Exception:
            pass
    return {"deleted": True}


@router.post("/jobs/{job_id}/run-now")
def scheduler_run_now(job_id: str):
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT id,bot_name,category FROM scheduled_jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    import threading
    threading.Thread(target=_run_job, args=(row[1], row[2], row[0]), daemon=True).start()
    return {"triggered": True, "bot_name": row[1]}
