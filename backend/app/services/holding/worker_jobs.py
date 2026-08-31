"""Worker-dispatch queue (Wave 3+) — the seam between an APPROVED proposal and an ISOLATED worker.

Prod (kai-prod) cannot run Docker, so it does not execute isolated workers itself. Instead an approved
WORKER proposal ENQUEUES a job here; a worker-runner on the operator's colima host (ops/holding-worker-
runner/) claims it, runs the certified read-only worker in its isolated container, and posts evidence
back. This keeps isolation intact: prod only queues; the container host executes.

Jobs are created only from an approved proposal (the executor enforces that). The worker task is
read-only by construction (the certified workers refuse writes). Self-creating table; fails soft.
"""
from __future__ import annotations
import json
from typing import Optional

from sqlalchemy import text
from app.database import SessionLocal

_DDL = """CREATE TABLE IF NOT EXISTS holding_worker_jobs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    proposal_id BIGINT, worker TEXT NOT NULL, task JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'dispatched',
    claimed_at TIMESTAMPTZ, done_at TIMESTAMPTZ, evidence JSONB
)"""


def enqueue(proposal_id: int, worker: str, task: dict) -> Optional[int]:
    """Create a dispatched job. Returns the job id (or None if DB down). Never raises."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            row = db.execute(text("""
                INSERT INTO holding_worker_jobs (proposal_id, worker, task, status)
                VALUES (:pid, :w, CAST(:t AS JSONB), 'dispatched') RETURNING id
            """), {"pid": proposal_id, "w": worker, "t": json.dumps(task)}).fetchone()
            db.commit()
            return row[0] if row else None
        finally:
            db.close()
    except Exception:
        return None


def list_jobs(status: Optional[str] = None, limit: int = 50) -> list:
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            q = "SELECT id, created_at, proposal_id, worker, task, status, done_at, evidence FROM holding_worker_jobs"
            params = {"lim": limit}
            if status:
                q += " WHERE status = :st"; params["st"] = status
            q += " ORDER BY created_at DESC, id DESC LIMIT :lim"
            out = []
            for r in db.execute(text(q), params).fetchall():
                out.append({"id": r[0], "created_at": str(r[1]), "proposal_id": r[2], "worker": r[3],
                            "task": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                            "status": r[5], "done_at": str(r[6]) if r[6] else None,
                            "evidence": r[7] if isinstance(r[7], (dict, list)) else (json.loads(r[7]) if r[7] else None)})
            return out
        finally:
            db.close()
    except Exception:
        return []


def claim_next() -> Optional[dict]:
    """Atomically claim the oldest 'dispatched' job (dispatched → running). For the worker-runner."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            row = db.execute(text("""
                UPDATE holding_worker_jobs SET status = 'running', claimed_at = now()
                 WHERE id = (SELECT id FROM holding_worker_jobs WHERE status = 'dispatched'
                             ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED)
             RETURNING id, proposal_id, worker, task
            """)).fetchone()
            db.commit()
            if not row:
                return None
            return {"id": row[0], "proposal_id": row[1], "worker": row[2],
                    "task": row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}")}
        finally:
            db.close()
    except Exception:
        return None


def complete(job_id: int, evidence: dict, status: str = "done") -> bool:
    """Record a running job's result (running → done/failed). Never raises."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            res = db.execute(text("""
                UPDATE holding_worker_jobs SET status = :st, done_at = now(), evidence = CAST(:ev AS JSONB)
                 WHERE id = :id AND status = 'running' RETURNING id
            """), {"st": status if status in ("done", "failed") else "done",
                   "ev": json.dumps(evidence), "id": job_id}).fetchone()
            db.commit()
            return bool(res)
        finally:
            db.close()
    except Exception:
        return False
