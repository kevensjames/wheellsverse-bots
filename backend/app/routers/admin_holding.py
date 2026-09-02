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


@router.post("/workers/heartbeat")
def holding_worker_hb(body: dict = Body(default={})):
    """The runner pings its liveness (even when idle) so the UI shows ONLINE/OFFLINE truthfully."""
    from app.services.holding import status as stat
    ok = stat.worker_heartbeat(str(body.get("worker_id") or "unknown"), host_id=str(body.get("host_id") or ""),
                               version=str(body.get("version") or ""), runtime=str(body.get("runtime") or ""),
                               current_job=body.get("current_job"))
    return {"ok": ok}


@router.get("/status")
def holding_status():
    """Operational status: worker liveness, cron, Telegram presence (never the token), autonomy roll-up."""
    from app.services.holding import status as stat
    return stat.full_status()


_manual_cycle_calls: dict = {}   # principal_id -> [monotonic ts] (conservative owner-scoped rate limit)


def _manual_cycle_rate_ok(principal_id: str, *, limit: int = 6, window_s: int = 60) -> bool:
    import time
    now = time.monotonic()
    win = [t for t in _manual_cycle_calls.get(principal_id, []) if now - t < window_s]
    if len(win) >= limit:
        _manual_cycle_calls[principal_id] = win
        return False
    win.append(now); _manual_cycle_calls[principal_id] = win
    return True


@router.get("/self-cert")
def holding_self_cert(principal=Depends(require_kai_ultra)):
    """Run the FIXED A0 + A1 certification scripts AS A SUBPROCESS INSIDE THIS DEPLOYED CONTAINER and
    return their results — true hosted-runtime proof (contrast `railway run`, which executes on the
    operator's local machine). Owner-only, staging-only, off by default (KAI_HOLDING_SELFCERT_ENABLED).
    No request input reaches the subprocess (fixed in-repo script paths); bounded output + timeout. The
    subprocess inherits THIS container's env, so the brakes/APP_ENV/MONEY_MODE it reports are the real ones."""
    import os
    import subprocess
    from pathlib import Path
    from app.config import settings
    if not getattr(settings, "KAI_HOLDING_SELFCERT_ENABLED", False) or \
       str(getattr(settings, "APP_ENV", "")).lower() != "staging":
        raise HTTPException(status_code=404, detail="not found")
    root = Path(__file__).resolve().parents[3]   # repo root (/app in the image): holds ops/ + backend/
    scripts = {"a0": "ops/holding-staging/hosted_a0_execute_cert.py",
               "a1": "ops/holding-staging/hosted_a1_execute_cert.py"}
    out = {"ran_in": "deployed-container", "hostname": os.uname().nodename,
           "app_env": getattr(settings, "APP_ENV", ""),
           "deployed_sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or "UNAVAILABLE",
           "results": {}}
    for name, rel in scripts.items():
        try:
            r = subprocess.run(["python3", str(root / rel)], cwd=str(root),
                               capture_output=True, text=True, timeout=120)
            stdout = r.stdout or ""
            verdict = next((ln.strip() for ln in reversed(stdout.splitlines()) if "CERT:" in ln), "")
            out["results"][name] = {"exit": r.returncode, "passed": r.returncode == 0,
                                    "verdict": verdict, "output_tail": stdout[-6000:]}
        except Exception as e:
            out["results"][name] = {"exit": None, "passed": False, "error": str(e)[:200]}
    _audit_proposal("holding.self_cert", {"principal": getattr(principal, "id", "owner"),
                    "a0": out["results"].get("a0", {}).get("passed"),
                    "a1": out["results"].get("a1", {}).get("passed")})
    return out


@router.post("/run-cycle")
def holding_run_cycle(body: dict = Body(default={}), principal=Depends(require_kai_ultra)):
    """Run EXACTLY ONE existing Holding cycle (owner-only, staging-cert/diagnostics). Reuses
    build_live_engine + run_persistent_cycle — NO new engine. Gated by KAI_HOLDING_MANUAL_CYCLE_ENABLED
    + APP_ENV=staging (else 404). Both emergency brakes remain authoritative; the route grants nothing.
    Single-flight (409), idempotent, server-side prior snapshot. Returns a normalized CycleRecord."""
    from datetime import datetime, timezone
    from app.config import settings
    from app.services.holding.manual_cycle import (run_manual_cycle, validate_request,
                                                   ManualCycleDenied, CycleRunning)
    pid = getattr(principal, "id", "owner")

    # §5/§6 — off by default, staging-only; not exposed in production merely because autonomy is on
    if not getattr(settings, "KAI_HOLDING_MANUAL_CYCLE_ENABLED", False) or \
       str(getattr(settings, "APP_ENV", "")).lower() != "staging":
        raise HTTPException(status_code=404, detail="not found")
    if not _manual_cycle_rate_ok(pid):
        raise HTTPException(status_code=429, detail="manual cycle rate limit")
    try:
        req = validate_request(body)   # §3 — only idempotency_key; forbidden keys rejected
    except ManualCycleDenied as e:
        _audit_proposal("holding.cycle_denied", {"principal": pid, "reason": str(e)[:120]})
        raise HTTPException(status_code=400, detail=str(e))

    now = datetime.now(timezone.utc).isoformat()
    _audit_proposal("holding.cycle_requested", {"principal": pid, "env": getattr(settings, "APP_ENV", ""),
                    "brakes": {"capability": getattr(settings, "KAI_CAPABILITY_EXECUTION_ENABLED", False),
                               "autonomy": getattr(settings, "HOLDING_AUTONOMY_ENABLED", False)}})
    from app.services.holding.holding_cycle import build_live_engine
    from app.services.holding.cycle_store import DbCycleStore
    from app.services.holding.digital_twin import HoldingDigitalTwin
    engine = build_live_engine()   # reads BOTH brakes from config; route overrides nothing
    try:
        rec = run_manual_cycle(DbCycleStore(), engine,
                               lambda: HoldingDigitalTwin(observed_at=now, today=now[:10]).snapshot(),
                               now=now, idempotency_key=req["idempotency_key"])
    except CycleRunning as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        _audit_proposal("holding.cycle_failed", {"principal": pid, "reason": str(e)[:120]})
        raise HTTPException(status_code=500, detail="cycle infrastructure failure")
    _audit_proposal("holding.cycle_completed", {"principal": pid, "cycle_id": rec.get("cycle_id"),
                    "status": rec.get("status"), "auto_actions_executed": rec.get("auto_actions_executed"),
                    "owner_actions_created": rec.get("owner_actions_created")})
    return rec


@router.get("/view")
def holding_view():
    """The /admin/holding UI view-model (Part E): TODAY FOR YOU first, KAI-work buckets, self-improvement
    ready-for-review, company cards, the Operational Self Model (never sentient), and autonomy state.
    Read-only + owner-gated; assembled live from the certified twin + self-model + owner queue. KAI-work
    and self-improvement lists populate once the persistent cycle runs live (empty until then)."""
    from app.services.holding.digital_twin import HoldingDigitalTwin
    from app.services.holding.self_model import OperationalSelfModel
    from app.services.holding.holding_view import build_holding_view
    from app.services.holding import proposals_store
    try:
        twin = HoldingDigitalTwin().snapshot()
    except Exception:
        twin = {}
    try:
        sm = OperationalSelfModel(environment="production").snapshot()
    except Exception:
        sm = {}
    try:
        owner_actions = proposals_store.list_proposals(status="proposed")
    except Exception:
        owner_actions = []
    return build_holding_view(twin_snapshot=twin, self_model=sm, owner_actions=owner_actions,
                              cycle_record=None, kai_work=[], self_improvements=[])
