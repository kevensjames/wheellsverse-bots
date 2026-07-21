"""Operator surface for the autonomous SWE agent.

Lifecycle across three separate requests:
  POST /admin/swe/tasks              create a task + produce a plan (LLM/heuristic
                                     only, NO exec) -> awaiting_plan_approval
  GET  /admin/swe/tasks/{id}         status / approvers / attempts
  GET  /admin/swe/tasks/{id}/plan    the proposed steps (Gate-1 review payload)
  GET  /admin/swe/tasks/{id}/patch   the produced diff (Gate-2 review payload)
  POST /admin/swe/tasks/{id}/plan/approve   GATE 1 (destructive): run the bounded
                                     sandbox loop -> awaiting_push_approval | failed
  POST /admin/swe/tasks/{id}/reject  decline at either gate -> rejected

Governed exactly like admin_swe.py: require_admin_token + @audited scopes, gated
by KAI_SWE_RUNTIME_ENABLED and a source-dir allowlist. NEVER an LLM tool; mounted
only on a non-prod runner (main.py swe_admin_enabled()). Push (Gate 2) is Inc 3.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.swe_runtime import task_store
from app.services.swe_runtime.brain import (AgentBrain, DefaultBrain, Mission,
                                            Step)
from app.services.swe_runtime.budget import Budget
from app.services.swe_runtime.config import (default_policy, image_allowed,
                                             repo_allowed, runtime_enabled)
from app.services.swe_runtime.policy import PolicyDenied
from app.services.swe_runtime.runtime import AgentRuntime, SandboxCommandRuntime
from app.services.swe_runtime.task_store import IllegalTransition

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/swe",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


# ── Injectable seams so tests can supply a fake runtime/brain ────────────────
def get_swe_runtime() -> AgentRuntime:
    return SandboxCommandRuntime()


def get_brain() -> AgentBrain:
    return DefaultBrain()


class CreateTaskRequest(BaseModel):
    goal: str
    source_dir: str
    commands: list[str]
    image: str | None = None
    task_id: str | None = None   # supply a stable id for idempotency; omit -> random


class ApproveRequest(BaseModel):
    approved: bool = False
    approver: str


def _is_expired(task: dict) -> bool:
    """Lazy, fail-closed approval timeout: a pending approval older than
    KAI_SWE_APPROVAL_TIMEOUT_HOURS is refused at approve-time. No daemon."""
    try:
        hours = float(os.environ.get("KAI_SWE_APPROVAL_TIMEOUT_HOURS", "24"))
    except ValueError:
        hours = 24.0
    created = task.get("created_at")
    if created is None:
        return False
    return (datetime.now(timezone.utc) - created).total_seconds() > hours * 3600


def _public(task: dict | None) -> dict:
    """Operator-facing view: str the id, trim logs, list artifact names instead
    of dumping bodies, float the cost."""
    if task is None:
        return {}
    t = dict(task)
    t["id"] = str(t.get("id"))
    if t.get("stdout"):
        t["stdout"] = t["stdout"][-4000:]
    if t.get("stderr"):
        t["stderr"] = t["stderr"][-2000:]
    arts = t.pop("artifacts", {}) or {}
    t["artifact_files"] = sorted(arts.keys())
    if t.get("cost_usd") is not None:
        t["cost_usd"] = float(t["cost_usd"])
    return t


# ── Gate 0: create + plan (non-destructive, scope swe.plan) ──────────────────
@audited(scope="swe.plan")
def _do_plan(*, db: Session, task_id: str, goal: str, source_dir: str,
             image: str | None, policy: dict, plan: list[dict]) -> dict:
    return task_store.create_task(
        db, task_id=task_id, goal=goal, source_dir=source_dir,
        image=image, policy=policy, plan=plan,
    )


@router.post("/tasks")
def create_task(body: CreateTaskRequest, db: Session = Depends(get_db),
                brain: AgentBrain = Depends(get_brain)):
    if not runtime_enabled():
        raise HTTPException(409, "SWE runtime disabled (set KAI_SWE_RUNTIME_ENABLED=1 on a non-prod runner)")
    if not os.path.isdir(body.source_dir):
        raise HTTPException(400, "source_dir is not a directory")
    if not repo_allowed(body.source_dir):
        raise HTTPException(403, "source_dir is not under KAI_SWE_REPO_ALLOWLIST")
    if body.image and not image_allowed(body.image):
        raise HTTPException(400, "image is not in KAI_SWE_IMAGE_ALLOWLIST")
    if not body.commands:
        raise HTTPException(400, "commands required (the LLM planner is a follow-up; supply the plan)")

    task_id = body.task_id or uuid.uuid4().hex[:12]
    pol_obj = default_policy()
    if body.image:
        pol_obj.image = body.image
    policy = {"image": pol_obj.image, "timeout_seconds": pol_obj.timeout_seconds,
              "memory": pol_obj.memory, "pids_limit": pol_obj.pids_limit, "cpus": pol_obj.cpus}
    mission = Mission(task_id=task_id, source_dir=body.source_dir, goal=body.goal,
                      commands=body.commands, image=body.image)
    steps = brain.plan(mission)  # LLM/heuristic only — NO sandbox exec
    try:
        row = _do_plan(db=db, task_id=task_id, goal=body.goal, source_dir=body.source_dir,
                       image=body.image, policy=policy, plan=[s.as_dict() for s in steps])
    except ScopeDenied as e:
        raise HTTPException(403, str(e))
    return _public(row)


@router.get("/tasks/{task_id}")
def read_task(task_id: str, db: Session = Depends(get_db)):
    t = task_store.get_task(db, task_id=task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    return _public(t)


@router.get("/tasks/{task_id}/plan")
def read_plan(task_id: str, db: Session = Depends(get_db)):
    t = task_store.get_task(db, task_id=task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    return {"task_id": task_id, "status": t["status"], "plan": t.get("plan") or []}


@router.get("/tasks/{task_id}/patch")
def read_patch(task_id: str, db: Session = Depends(get_db)):
    t = task_store.get_task(db, task_id=task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    return {"task_id": task_id, "status": t["status"], "patch": t.get("patch"),
            "patch_sha256": t.get("patch_sha256")}


# ── Gate 1: approve the plan -> run the bounded loop (destructive) ────────────
@audited(scope="swe.brain.execute", destructive=True)
def _do_execute(*, db: Session, task_row: dict, approver: str,
                brain: AgentBrain, runtime: AgentRuntime):
    # Gate passed (scope on + approved). Conditional transitions keep this
    # race-safe: a concurrent approval/reject loses (IllegalTransition -> 409).
    task_id = task_row["task_id"]
    task_store.transition(
        db, task_id=task_id, from_status="awaiting_plan_approval", to_status="executing",
        touch=("plan_approved_at",), plan_approved_by=approver,
    )
    mission = Mission(task_id=task_id, source_dir=task_row["source_dir"],
                      goal=task_row["goal"], image=task_row.get("image"),
                      budget=Budget.default())
    plan = [Step(n=s["n"], command=s["command"], rationale=s.get("rationale", ""))
            for s in (task_row.get("plan") or [])]
    try:
        result = brain.execute(mission, plan, runtime)
        last = result.last
        common = {
            "exit_code": last.exit_code if last else None,
            "stdout": (last.stdout[-8000:] if last and last.stdout else None),
            "stderr": (last.stderr[-4000:] if last and last.stderr else None),
            "timed_out": bool(last.timed_out) if last else False,
            "artifacts": (last.artifacts if last else {}),
            "attempts": (task_row.get("attempts") or 0) + 1,
        }
        if result.status == "awaiting_push_approval":
            task_store.transition(
                db, task_id=task_id, from_status="executing", to_status="awaiting_push_approval",
                patch=result.patch,
                patch_sha256=hashlib.sha256((result.patch or "").encode()).hexdigest(),
                **common,
            )
        else:
            task_store.transition(
                db, task_id=task_id, from_status="executing", to_status="failed",
                error=result.error, **common,
            )
        return result
    except Exception as e:
        # Never strand the row in transient 'executing' on an unexpected error.
        # DefaultBrain converts EXPECTED failures into a graceful 'failed' result;
        # this catches a genuine bug / DB error / a raise from the runtime and
        # moves the row to terminal 'failed' (best-effort, race-safe via the
        # conditional transition) before re-raising. A hard process kill (SIGKILL/
        # OOM) can still strand 'executing' — reject() is the operator un-stick.
        try:
            task_store.transition(
                db, task_id=task_id, from_status="executing", to_status="failed",
                error=f"execute crashed: {type(e).__name__}: {e}",
                attempts=(task_row.get("attempts") or 0) + 1,
            )
        except Exception:
            logger.exception("could not mark stranded swe task failed")
        raise


@router.post("/tasks/{task_id}/plan/approve")
def approve_plan(task_id: str, body: ApproveRequest, db: Session = Depends(get_db),
                 brain: AgentBrain = Depends(get_brain),
                 runtime: AgentRuntime = Depends(get_swe_runtime)):
    if not body.approver.strip():
        raise HTTPException(400, "approver is required (no anonymous approvals)")
    if not runtime_enabled():
        raise HTTPException(409, "SWE runtime disabled")
    task = task_store.get_task(db, task_id=task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if task["status"] != "awaiting_plan_approval":
        raise HTTPException(409, f"task is {task['status']}, not awaiting_plan_approval")
    # Re-validate at execute time (TOCTOU): the source_dir was allowlisted at
    # create, but the allowlist or the directory itself may have changed since.
    if not os.path.isdir(task["source_dir"]) or not repo_allowed(task["source_dir"]):
        raise HTTPException(403, "source_dir is no longer an allowlisted directory")
    if _is_expired(task):
        try:
            task_store.transition(db, task_id=task_id, from_status="awaiting_plan_approval",
                                  to_status="expired", error="approval window expired")
        except IllegalTransition:
            pass
        raise HTTPException(409, "approval window expired")
    try:
        _do_execute(db=db, task_row=task, approver=body.approver, brain=brain,
                    runtime=runtime, approved=body.approved, actor=body.approver)
    except ScopeDenied as e:
        raise HTTPException(403, str(e))
    except PendingApproval as e:
        raise HTTPException(409, str(e))
    except PolicyDenied as e:
        raise HTTPException(400, f"policy denied: {e}")
    except IllegalTransition as e:
        raise HTTPException(409, str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("swe execute failed")
        raise HTTPException(503, "swe execute failed")
    return _public(task_store.get_task(db, task_id=task_id))


# ── Reject at either gate (non-destructive, scope swe.plan) ───────────────────
@audited(scope="swe.plan")
def _do_reject(*, db: Session, task_id: str, from_status: str):
    return task_store.transition(db, task_id=task_id, from_status=from_status,
                                 to_status="rejected")


@router.post("/tasks/{task_id}/reject")
def reject(task_id: str, body: ApproveRequest, db: Session = Depends(get_db)):
    if not body.approver.strip():
        raise HTTPException(400, "approver is required")
    task = task_store.get_task(db, task_id=task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    st = task["status"]
    # 'executing' is included as the operator un-stick for a task stranded by a
    # hard process kill mid-run (execution is synchronous-in-request, so a live
    # run and a crash-stranded row are indistinguishable to the DB — the
    # single-operator caller knows which they have).
    if st not in ("awaiting_plan_approval", "awaiting_push_approval", "executing"):
        raise HTTPException(409, f"cannot reject a task in {st}")
    try:
        _do_reject(db=db, task_id=task_id, from_status=st, actor=body.approver)
    except ScopeDenied as e:
        raise HTTPException(403, str(e))
    except IllegalTransition as e:
        raise HTTPException(409, str(e))
    return _public(task_store.get_task(db, task_id=task_id))
