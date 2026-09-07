"""Worker-dispatch queue with a real state machine, lease, heartbeat, and idempotency (autonomy cert).

Seam between an APPROVED proposal and an ISOLATED worker. Prod (kai-prod) cannot run Docker, so it
only QUEUES; a persistent worker-runner on the operator's colima host claims jobs over owner-authed
HTTP, runs the certified read-only worker in isolation, heartbeats, and posts evidence back.

State machine:   queued → claimed/running → succeeded | failed          (+ expired reclaim, cancelled)
Illegal transitions are refused by the WHERE-guards on every UPDATE (e.g. succeeded→running never matches).
Lease + heartbeat:  a claim sets lease_expires_at; the runner heartbeats to extend it. If a worker
  crashes, its lease expires and the job becomes claimable again (bounded, attempt-tracked) — so a
  crash never strands a job, and two workers never execute the same job (FOR UPDATE SKIP LOCKED + a
  claimed_by ownership check on heartbeat/complete).
Idempotency:  a unique idempotency_key makes re-dispatch return the SAME job (no duplicate execution);
  complete is idempotent (a terminal job ignores repeats), so an evidence-post retry never duplicates.

Self-creating table; fails soft (returns [] / None / False) if the DB is unavailable.
"""
from __future__ import annotations
import json
import uuid
from typing import Optional

from sqlalchemy import text
from app.database import SessionLocal

DEFAULT_LEASE_SECONDS = 300
MAX_ATTEMPTS = 3
TERMINAL = ("succeeded", "failed", "cancelled", "expired")

_DDL = """CREATE TABLE IF NOT EXISTS holding_worker_jobs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    proposal_id BIGINT, mission_id TEXT, idempotency_key TEXT UNIQUE,
    worker TEXT NOT NULL, task JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    claimed_by TEXT, claimed_at TIMESTAMPTZ, lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ, attempt INT NOT NULL DEFAULT 0, max_attempts INT NOT NULL DEFAULT 3,
    correlation_id TEXT, done_at TIMESTAMPTZ, evidence JSONB
)"""
# Upgrade older (Wave-3) tables in place:
_ALTERS = (
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS mission_id TEXT",
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS idempotency_key TEXT",
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS claimed_by TEXT",
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ",
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ",
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS attempt INT NOT NULL DEFAULT 0",
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS max_attempts INT NOT NULL DEFAULT 3",
    "ALTER TABLE holding_worker_jobs ADD COLUMN IF NOT EXISTS correlation_id TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS holding_worker_jobs_idem ON holding_worker_jobs (idempotency_key)",
)


def _ensure(db) -> None:
    db.execute(text(_DDL))
    for a in _ALTERS:
        try:
            db.execute(text(a))
        except Exception:
            pass


def enqueue(proposal_id: int, worker: str, task: dict, *, idempotency_key: Optional[str] = None,
            mission_id: Optional[str] = None) -> Optional[dict]:
    """Create a queued job. Idempotent on idempotency_key — a repeat returns the SAME job (no dup).
    Returns {id, status, correlation_id, deduped}. None if DB down. Never raises."""
    key = idempotency_key or f"prop:{proposal_id}:{worker}"
    corr = "corr-" + uuid.uuid4().hex[:12]
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            row = db.execute(text("""
                INSERT INTO holding_worker_jobs (proposal_id, mission_id, idempotency_key, worker, task,
                                                 status, correlation_id, max_attempts)
                VALUES (:pid, :mid, :key, :w, CAST(:t AS JSONB), 'queued', :corr, :maxa)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id, status, correlation_id
            """), {"pid": proposal_id, "mid": mission_id, "key": key, "w": worker,
                   "t": json.dumps(task), "corr": corr, "maxa": MAX_ATTEMPTS}).fetchone()
            db.commit()
            if row:
                return {"id": row[0], "status": row[1], "correlation_id": row[2], "deduped": False}
            existing = db.execute(text(
                "SELECT id, status, correlation_id FROM holding_worker_jobs WHERE idempotency_key = :key"),
                {"key": key}).fetchone()
            return {"id": existing[0], "status": existing[1], "correlation_id": existing[2], "deduped": True} if existing else None
        finally:
            db.close()
    except Exception:
        return None


def claim_next(worker_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Optional[dict]:
    """Atomically claim the oldest eligible job for this worker (queued, OR a stale claimed/running job
    whose lease expired → reclaim, bounded by max_attempts). Sets running + lease + heartbeat + attempt.
    Exactly one worker wins (FOR UPDATE SKIP LOCKED). Returns the job or None."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            row = db.execute(text("""
                UPDATE holding_worker_jobs SET status='running', claimed_by=:wid, claimed_at=now(),
                       heartbeat_at=now(), lease_expires_at = now() + (:lease || ' seconds')::interval,
                       attempt = attempt + 1
                 WHERE id = (
                    SELECT id FROM holding_worker_jobs
                     WHERE (status='queued'
                            OR (status IN ('claimed','running') AND lease_expires_at < now()))
                       AND attempt < max_attempts
                     ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED)
             RETURNING id, proposal_id, worker, task, correlation_id, attempt, max_attempts
            """), {"wid": worker_id, "lease": lease_seconds}).fetchone()
            db.commit()
            if not row:
                return None
            return {"id": row[0], "proposal_id": row[1], "worker": row[2],
                    "task": row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}"),
                    "correlation_id": row[4], "attempt": row[5], "max_attempts": row[6]}
        finally:
            db.close()
    except Exception:
        return None


def heartbeat(job_id: int, worker_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
    """Extend a running job's lease — only the owning worker, only while running. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            res = db.execute(text("""
                UPDATE holding_worker_jobs SET heartbeat_at=now(),
                       lease_expires_at = now() + (:lease || ' seconds')::interval
                 WHERE id=:id AND status='running' AND claimed_by=:wid RETURNING id
            """), {"id": job_id, "wid": worker_id, "lease": lease_seconds}).fetchone()
            db.commit()
            return bool(res)
        finally:
            db.close()
    except Exception:
        return False


def complete(job_id: int, evidence: dict, *, status: str = "succeeded", worker_id: Optional[str] = None) -> bool:
    """Terminal transition (running → succeeded/failed) — ownership + state guarded, idempotent (a job
    already terminal is a no-op, so an evidence-post retry never duplicates). Never raises."""
    st = status if status in ("succeeded", "failed") else "succeeded"
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            guard = " AND claimed_by=:wid" if worker_id else ""
            res = db.execute(text(f"""
                UPDATE holding_worker_jobs SET status=:st, done_at=now(), evidence=CAST(:ev AS JSONB)
                 WHERE id=:id AND status='running'{guard} RETURNING id
            """), {"st": st, "ev": json.dumps(evidence), "id": job_id, "wid": worker_id}).fetchone()
            db.commit()
            return bool(res)
        finally:
            db.close()
    except Exception:
        return False


def reclaim_expired() -> int:
    """Return stranded jobs (lease expired, under max_attempts) to 'queued'; mark exhausted ones 'expired'.
    Returns how many were requeued. Idempotent to run. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            db.execute(text("""
                UPDATE holding_worker_jobs SET status='expired', done_at=now()
                 WHERE status IN ('claimed','running') AND lease_expires_at < now() AND attempt >= max_attempts
            """))
            res = db.execute(text("""
                UPDATE holding_worker_jobs SET status='queued', claimed_by=NULL, lease_expires_at=NULL
                 WHERE status IN ('claimed','running') AND lease_expires_at < now() AND attempt < max_attempts
             RETURNING id
            """)).fetchall()
            db.commit()
            return len(res)
        finally:
            db.close()
    except Exception:
        return 0


def get(job_id: int) -> Optional[dict]:
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            r = db.execute(text("""SELECT id, status, worker, claimed_by, attempt, max_attempts,
                       heartbeat_at, lease_expires_at, correlation_id, evidence FROM holding_worker_jobs WHERE id=:id"""),
                {"id": job_id}).fetchone()
            if not r:
                return None
            return {"id": r[0], "status": r[1], "worker": r[2], "claimed_by": r[3], "attempt": r[4],
                    "max_attempts": r[5], "heartbeat_at": str(r[6]) if r[6] else None,
                    "lease_expires_at": str(r[7]) if r[7] else None, "correlation_id": r[8],
                    "evidence": r[9] if isinstance(r[9], (dict, list)) else (json.loads(r[9]) if r[9] else None)}
        finally:
            db.close()
    except Exception:
        return None


def list_for_mission(mission_id: str, limit: int = 200) -> list:
    """§27 mission linkage — the jobs a Mission header WRAPS (join by the existing mission_id column,
    no copy). Includes status + evidence so the mission's status/verified_outcome is DERIVED live from
    the real worker-plane state. Never raises."""
    if not mission_id:
        return []
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            rows = db.execute(text(
                "SELECT id, created_at, claimed_at, done_at, proposal_id, worker, task, status, claimed_by, "
                "attempt, max_attempts, evidence, correlation_id FROM holding_worker_jobs "
                "WHERE mission_id=:m ORDER BY created_at ASC, id ASC LIMIT :lim"),
                {"m": mission_id, "lim": limit}).fetchall()
            out = []
            for r in rows:
                out.append({"id": r[0], "created_at": str(r[1]), "claimed_at": str(r[2]) if r[2] else None,
                            "done_at": str(r[3]) if r[3] else None, "proposal_id": r[4], "worker": r[5],
                            "task": r[6] if isinstance(r[6], dict) else json.loads(r[6] or "{}"),
                            "status": r[7], "claimed_by": r[8], "attempt": r[9], "max_attempts": r[10],
                            "evidence": r[11] if isinstance(r[11], (dict, list)) else (json.loads(r[11]) if r[11] else None),
                            "correlation_id": r[12]})
            return out
        finally:
            db.close()
    except Exception:
        return []


def list_jobs(status: Optional[str] = None, limit: int = 50) -> list:
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            q = ("SELECT id, created_at, proposal_id, worker, task, status, claimed_by, attempt, "
                 "heartbeat_at, done_at, evidence, correlation_id FROM holding_worker_jobs")
            params = {"lim": limit}
            if status:
                q += " WHERE status=:st"; params["st"] = status
            q += " ORDER BY created_at DESC, id DESC LIMIT :lim"
            out = []
            for r in db.execute(text(q), params).fetchall():
                out.append({"id": r[0], "created_at": str(r[1]), "proposal_id": r[2], "worker": r[3],
                            "task": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                            "status": r[5], "claimed_by": r[6], "attempt": r[7],
                            "heartbeat_at": str(r[8]) if r[8] else None, "done_at": str(r[9]) if r[9] else None,
                            "evidence": r[10] if isinstance(r[10], (dict, list)) else (json.loads(r[10]) if r[10] else None),
                            "correlation_id": r[11]})
            return out
        finally:
            db.close()
    except Exception:
        return []
