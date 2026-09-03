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
    """The worker-runner posts a job's evidence (running -> succeeded/failed). Owner-only, owning-worker
    guarded (worker_id REQUIRED so the ownership guard is never optional), idempotent. For an A2 CODING
    job, deployed KAI INDEPENDENTLY re-verifies the evidence (verify_a2_evidence) and records ITS decision
    as authoritative — the worker's self-reported state/status is never trusted as the label."""
    import os
    from app.services.holding import worker_jobs
    worker_id = body.get("worker_id")
    if not worker_id:                                          # §41 — never let the ownership guard be optional
        raise HTTPException(status_code=400, detail="worker_id required")
    evidence = body.get("evidence", body)
    status = body.get("status", "succeeded")
    # A2 coding evidence carries an A2Prepared shape (state + action_type). Deployed KAI decides, not the worker.
    if isinstance(evidence, dict) and evidence.get("action_type") and "state" in evidence:
        from app.services.holding.a2_dispatch import verify_a2_evidence
        base = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or ""
        decision = verify_a2_evidence(evidence, expected_company="wheellsverse", expected_base_sha=base)
        evidence = {**evidence, "kai_decision": decision}     # authoritative decision recorded with the evidence
        status = "succeeded" if decision["decision"] in ("READY_FOR_REVIEW", "OWNER_REQUIRED") else "failed"
    ok = worker_jobs.complete(job_id, evidence, status=status, worker_id=worker_id)
    if not ok:
        raise HTTPException(status_code=409, detail="job not in 'running' state / not owner / already terminal")
    _audit_proposal("holding.worker_job.completed", {"job_id": job_id, "status": status, "worker_id": worker_id,
                    "kai_decision": (evidence.get("kai_decision") or {}).get("decision") if isinstance(evidence, dict) else None})
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


@router.post("/a2-dispatch")
def holding_a2_dispatch(body: dict = Body(default={}), principal=Depends(require_kai_ultra)):
    """Deployed KAI ENQUEUES ONE governed A2 coding job onto the existing worker plane (worker_jobs) — the
    §37 hosted-A2 origin. Owner-only, staging-only (else 404), and the enqueue itself refuses unless all
    three brakes + the grant + a base_sha allow it (a2_dispatch.enqueue_a2_coding_job). KAI never runs git;
    the colima worker-runner claims the job and runs the whole governed prepare(). Body carries only a
    non-authoritative mission_id/goal; base_sha is the deployed SHA (server-derived)."""
    import os
    from app.config import settings
    from app.services.holding.a2_dispatch import enqueue_a2_coding_job
    if str(getattr(settings, "APP_ENV", "")).lower() != "staging":
        raise HTTPException(status_code=404, detail="not found")
    mission_id = str(body.get("mission_id") or "a2-hosted-cert")[:64]
    base_sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or ""
    r = enqueue_a2_coding_job(mission_id=mission_id, base_sha=base_sha, settings=settings,
                             company_id="wheellsverse", suite_id="holding_self_model",
                             goal=str(body.get("goal") or "prepare a bounded fix")[:200])
    _audit_proposal("holding.a2_job_created", {"principal": getattr(principal, "id", "owner"),
                    "mission_id": mission_id, "enqueued": r.get("enqueued"), "reason": r.get("reason"),
                    "job_id": (r.get("job") or {}).get("id")})
    return {"enqueued": r.get("enqueued"), "reason": r.get("reason"),
            "job_id": (r.get("job") or {}).get("id"), "base_sha_present": bool(base_sha)}


@router.post("/self-improvement-dispatch")
def holding_self_improvement_dispatch(body: dict = Body(default={}), principal=Depends(require_kai_ultra)):
    """Part C (§21) HOSTED self-improvement ORIGIN. Owner-only, staging-only (else 404). Deployed KAI turns
    a candidate into a CONFIRMED decision (self_improvement.confirm) and — only if confirmed AND the §22
    self-improvement brake is on — dispatches it through the CERTIFIED A2 path (which still needs all three
    A2 brakes + grant + base_sha). The persistent worker runs the whole prepare(); nothing is merged/deployed.

    HARDENED (Part 5 / V6): the failing baseline is NEVER a client boolean. Like /self-improvement-run, this
    endpoint RUNS the certified suite server-side (internal_test) on the deployed code and derives
    test_before_fails from the real result. Without a suite_id whose suite genuinely FAILS, the candidate
    cannot confirm -> BLOCKED_EVIDENCE, 0 dispatch. (This endpoint is now equivalent to /self-improvement-run,
    retained for back-compat; prefer /self-improvement-run.)"""
    import os
    from app.config import settings
    from app.services.holding.self_improvement import dispatch_self_improvement, SelfImprovementCandidate
    from app.services.holding.internal_test import make_internal_test_provider, TestDenied
    if str(getattr(settings, "APP_ENV", "")).lower() != "staging":
        raise HTTPException(status_code=404, detail="not found")
    base_sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or ""
    suite_id = str(body.get("suite_id") or "")[:64]
    before_failed = False                                    # server-derived only; a bare client boolean is ignored
    if suite_id:
        try:
            before = make_internal_test_provider()({"suite_id": suite_id, "company_id": "wheellsverse"})
        except TestDenied as e:
            raise HTTPException(status_code=400, detail=f"suite denied: {e}")
        before_failed = (before.get("execution") == "COMPLETED" and before.get("test_result") == "FAILED")
    cand = SelfImprovementCandidate(
        improvement_id=str(body.get("improvement_id") or "si-hosted-cert")[:64],
        subsystem=str(body.get("subsystem") or "holding")[:80],
        problem_type=str(body.get("problem_type") or "DEFECT")[:40],
        problem=str(body.get("problem") or "")[:400],
        desired_outcome=str(body.get("desired_outcome") or "CORRECTNESS")[:40],
        company_id=str(body.get("company_id") or "wheellsverse")[:40],
        evidence_refs=list(body.get("evidence_refs") or [])[:20])
    r = dispatch_self_improvement(
        cand, settings=settings, base_sha=base_sha, suite_id=suite_id or "holding_self_model",
        goal=str(body.get("goal") or "prepare a bounded fix")[:200],
        deployment_comparison=str(body.get("deployment_comparison") or "UNCOMPARABLE"),
        test_before_fails=before_failed,                     # NEVER from the client body
        is_config_issue=bool(body.get("is_config_issue")))
    _audit_proposal("holding.self_improvement_dispatch", {"principal": getattr(principal, "id", "owner"),
                    "improvement_id": cand.improvement_id, "dispatched": r.get("dispatched"),
                    "reason": r.get("reason"), "job_id": (r.get("job") or {}).get("id")})
    return {"dispatched": r.get("dispatched"), "reason": r.get("reason"),
            "candidate_status": (r.get("candidate") or {}).get("status"),
            "job_id": (r.get("job") or {}).get("id"), "base_sha_present": bool(base_sha)}


@router.post("/self-improvement-run")
def holding_self_improvement_run(body: dict = Body(default={}), principal=Depends(require_kai_ultra)):
    """STRICT before/after origination (§Part1). Owner-only, staging-only (else 404). Deployed KAI first
    RUNS the certified suite server-side (RUN_INTERNAL_TEST / internal_test) on the DEPLOYED code to
    establish a REAL baseline — the failing before-result is server-derived, NEVER a client boolean, so it
    can't be simulated. Only if the baseline genuinely FAILED does confirm() pass (test_before_fails=True);
    then it dispatches the SAME suite_id through the certified A2 path so the worker runs the byte-identical
    suite in its fixed worktree for the AFTER result. A passing baseline -> BLOCKED_EVIDENCE, 0 dispatch."""
    import os
    from app.config import settings
    from app.services.holding.self_improvement import dispatch_self_improvement, SelfImprovementCandidate
    from app.services.holding.internal_test import make_internal_test_provider, TestDenied
    if str(getattr(settings, "APP_ENV", "")).lower() != "staging":
        raise HTTPException(status_code=404, detail="not found")
    suite_id = str(body.get("suite_id") or "si_before_after")[:64]
    # 1. SERVER-RUN baseline on the deployed code (non-forgeable). A suite failure is a COMPLETED run.
    try:
        before = make_internal_test_provider()({"suite_id": suite_id, "company_id": "wheellsverse"})
    except TestDenied as e:
        raise HTTPException(status_code=400, detail=f"suite denied: {e}")
    before_failed = (before.get("execution") == "COMPLETED" and before.get("test_result") == "FAILED")
    base_sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or ""
    cand = SelfImprovementCandidate(
        improvement_id=str(body.get("improvement_id") or "si-before-after")[:64],
        subsystem="holding", problem_type="DEFECT",
        problem=str(body.get("problem") or f"{suite_id} reproduces a failing assertion on deployed code")[:400],
        desired_outcome=str(body.get("desired_outcome") or "CORRECTNESS")[:40], company_id="wheellsverse",
        evidence_refs=[f"{suite_id}: execution={before.get('execution')} result={before.get('test_result')} "
                       f"failed={before.get('failed')}/{before.get('tests_discovered')}"])
    # 2. dispatch with the SERVER-DERIVED baseline; the SAME suite_id is the worker's AFTER test.
    r = dispatch_self_improvement(
        cand, settings=settings, base_sha=base_sha, suite_id=suite_id,
        goal=str(body.get("goal") or "prepare a bounded fix")[:200],
        deployment_comparison=str(body.get("deployment_comparison") or "UNCOMPARABLE"),
        test_before_fails=before_failed, is_config_issue=bool(body.get("is_config_issue")))
    _audit_proposal("holding.self_improvement_run", {"principal": getattr(principal, "id", "owner"),
                    "improvement_id": cand.improvement_id, "suite_id": suite_id,
                    "before_result": before.get("test_result"), "dispatched": r.get("dispatched"),
                    "reason": r.get("reason"), "job_id": (r.get("job") or {}).get("id")})
    return {"before": {"execution": before.get("execution"), "test_result": before.get("test_result"),
                       "passed": before.get("passed"), "failed": before.get("failed"),
                       "tests_discovered": before.get("tests_discovered"), "commit_sha": before.get("commit_sha")},
            "baseline_failed": before_failed, "dispatched": r.get("dispatched"), "reason": r.get("reason"),
            "candidate_status": (r.get("candidate") or {}).get("status"),
            "job_id": (r.get("job") or {}).get("id"), "base_sha_present": bool(base_sha)}


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
