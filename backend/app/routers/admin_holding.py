"""Governed, READ-ONLY Holding Operations endpoints (owner-only kai.ultra).

Dormant unless KAI_HOLDING_ENABLED — main.py only includes this router when the flag is on,
so a disabled deployment has ZERO new surface. All endpoints are GET/read-only and source-backed
(no fabricated financials). No write/send endpoints exist here — external actions are separate and
approval-gated by design.
"""
from __future__ import annotations
from fastapi import APIRouter, Body, Depends, HTTPException

from app.routers.admin_chat import require_kai_ultra  # reuse the owner-only gate (no parallel auth)
from app.services.holding import reports
from app.services.holding.briefing import run_morning_briefing

router = APIRouter(prefix="/admin/holding", tags=["holding"],
                   dependencies=[Depends(require_kai_ultra)])


@router.get("/overview")
def holding_overview():
    return reports.executive_overview()


@router.get("/entities/{entity_id}")
def holding_entity(entity_id: str):
    rec = reports.company_portfolio(entity_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    return rec


@router.get("/briefing")
def holding_briefing():
    # report-only; never sends externally
    return run_morning_briefing(fetch_health=True)


def _audit_proposal(event: str, payload: dict) -> None:
    """Best-effort audit of a proposal decision (fail-open)."""
    try:
        from app.database import SessionLocal
        from app.models.admin import AuditLog
        s = SessionLocal()
        try:
            s.add(AuditLog(action=event, actor_type="owner", event_metadata=payload)); s.commit()
        finally:
            s.close()
    except Exception:
        pass


@router.get("/proposals")
def holding_proposals():
    """KAI's current draft proposals (read-only/investigative actions) + a ranked daily plan.
    Proposals are generated from the live priorities and persisted (deduped). Nothing runs — the
    operator approves or rejects, and even an approved proposal only records a decision (execution
    is a later, separate wave)."""
    from app.services.holding import proposals as prop, proposals_store
    from app.services.holding.priorities import derive_priorities
    proposals_store.sync_open(prop.build_proposals(derive_priorities()))   # persist any new, deduped
    open_props = proposals_store.list_proposals(status="proposed")
    return {"open": open_props, "daily_plan": prop.build_daily_plan(open_props),
            "note": "KAI proposes; you approve or reject. Nothing executes — approval records a decision only."}


@router.post("/proposals/{proposal_id}/approve")
def holding_approve(proposal_id: int):
    """OWNER approves a proposal — records the decision + audits it. Does NOT execute anything."""
    from app.services.holding import proposals_store
    r = proposals_store.decide(proposal_id, "approved")
    if r is None:
        raise HTTPException(status_code=404, detail="no open proposal with that id")
    _audit_proposal("holding.proposal.approved", r)
    return {"approved": True, "proposal": r,
            "note": "Decision recorded and audited. Execution is a separate later wave — nothing has run."}


@router.post("/proposals/{proposal_id}/reject")
def holding_reject(proposal_id: int, reason: str = ""):
    """OWNER rejects a proposal (optional reason) — records the decision + audits it."""
    from app.services.holding import proposals_store
    r = proposals_store.decide(proposal_id, "rejected", reason=reason)
    if r is None:
        raise HTTPException(status_code=404, detail="no open proposal with that id")
    _audit_proposal("holding.proposal.rejected", {**r, "reason": reason})
    return {"rejected": True, "proposal": r}


@router.post("/proposals/{proposal_id}/execute")
def holding_execute(proposal_id: int):
    """Execute an APPROVED proposal's READ-ONLY action (re-probe / gather evidence) — bound to the
    prior approval. Refuses anything not already approved. No writes, money, or deploys. Audited."""
    from app.services.holding.executor import execute_approved
    r = execute_approved(proposal_id)
    if not r.get("executed"):
        # 409 when the proposal exists but isn't in an approved state; 404-ish reasons collapse here too
        raise HTTPException(status_code=409, detail=r.get("reason", "cannot execute"))
    _audit_proposal("holding.proposal.executed",
                    {"id": proposal_id, "action_class": r.get("action_class"), "evidence": r.get("evidence")})
    return r


# ── Worker-job queue (Wave 3+): prod queues; the operator's colima worker-runner executes ──
@router.get("/worker-jobs")
def holding_worker_jobs(status: str = ""):
    from app.services.holding import worker_jobs
    return {"jobs": worker_jobs.list_jobs(status=status or None)}


@router.post("/worker-jobs/claim")
def holding_worker_claim(body: dict = Body(default={})):
    """The worker-runner claims the next eligible job (queued or a lease-expired reclaim → running),
    bound to its worker_id. Owner-only. Reclaims stranded jobs first so a crash never permanently strands."""
    from app.services.holding import worker_jobs
    worker_jobs.reclaim_expired()
    worker_id = str(body.get("worker_id") or "holding-worker-unknown")
    job = worker_jobs.claim_next(worker_id)
    return {"job": job, "worker_id": worker_id}   # job is None when the queue is empty


@router.post("/worker-jobs/{job_id}/heartbeat")
def holding_worker_heartbeat(job_id: int, body: dict = Body(default={})):
    """The worker-runner extends a running job's lease. Owner-only + owning-worker guarded."""
    from app.services.holding import worker_jobs
    ok = worker_jobs.heartbeat(job_id, str(body.get("worker_id") or ""))
    if not ok:
        raise HTTPException(status_code=409, detail="not running / not owner")
    return {"heartbeat": True, "job_id": job_id}


@router.post("/worker-jobs/{job_id}/complete")
def holding_worker_complete(job_id: int, body: dict = Body(default={})):
    """The worker-runner posts a job's read-only evidence (running -> succeeded/failed). Owner-only,
    owning-worker guarded, idempotent (a terminal job is a no-op → no duplicate evidence)."""
    from app.services.holding import worker_jobs
    ok = worker_jobs.complete(job_id, body.get("evidence", body), status=body.get("status", "succeeded"),
                              worker_id=body.get("worker_id"))
    if not ok:
        raise HTTPException(status_code=409, detail="job not in 'running' state / not owner / already terminal")
    _audit_proposal("holding.worker_job.completed",
                    {"job_id": job_id, "status": body.get("status", "succeeded"), "worker_id": body.get("worker_id")})
    return {"completed": True, "job_id": job_id}


@router.post("/worker-jobs/reclaim")
def holding_worker_reclaim():
    """Return lease-expired stranded jobs to the queue (crash recovery). Owner-only."""
    from app.services.holding import worker_jobs
    return {"reclaimed": worker_jobs.reclaim_expired()}
