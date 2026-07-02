"""Persistent-goal admin endpoints — the operator's Goals surface (KAI v1 #4b).

Reads (non-destructive, KAI_SCOPE_GOALS wildcard ok):
  GET  /admin/goals/stats
  GET  /admin/goals/list?status=&limit=
  GET  /admin/goals/scheduler          heartbeat status
  GET  /admin/goals/{goal_id}

Writes (each @audited; GOV-005 — destructive needs the EXACT scope flag):
  POST /admin/goals/create                       goals.create      (destructive)
  POST /admin/goals/{goal_id}/update             goals.edit        (destructive)
  POST /admin/goals/{goal_id}/approve-proposal   goals.approve_proposal (destructive)  [Task 4]
  POST /admin/goals/run                          goals.run         (non-destructive)   [Task 4]
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.routers.admin_chat import OperatorNotConfigured, _resolve_operator_profile
from app.services.goals import scheduler, store
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.planning import planner, storage
from app.services.router import build_default_router

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/goals",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


# ─── reads ───────────────────────────────────────────────────────────

@router.get("/stats")
def goals_stats() -> dict[str, Any]:
    goals = store.list_goals()
    by_status = {s: 0 for s in store.STATUSES}
    for g in goals:
        by_status[g.status] = by_status.get(g.status, 0) + 1
    return {"total": len(goals), **by_status}


@router.get("/list")
def goals_list(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    goals = store.list_goals(status=status)[:limit]
    return {"count": len(goals), "goals": [g.as_dict() for g in goals]}


@router.get("/scheduler")
def goals_scheduler_status() -> dict[str, Any]:
    # Declared BEFORE /{goal_id} so this literal path isn't captured by the param.
    return scheduler.status()


@router.get("/{goal_id}")
def goals_get(goal_id: str) -> dict[str, Any]:
    g = store.get_goal(goal_id)
    if g is None:
        raise HTTPException(status_code=404, detail=f"no goal with id {goal_id}")
    return {"goal": g.as_dict()}


# ─── request models ──────────────────────────────────────────────────

class CreateRequest(BaseModel):
    title: str
    done_when: str = ""
    approved: bool = False


class UpdateRequest(BaseModel):
    status: str | None = None
    progress: str | None = None
    approved: bool = False


class ApproveProposalRequest(BaseModel):
    prefer_local: bool = False
    approved: bool = False


class RunRequest(BaseModel):
    notify: bool = False
    approved: bool = False


# ─── audited write actions ───────────────────────────────────────────

@audited(scope="goals.create", destructive=True)
def _audited_create(*, title: str, done_when: str) -> dict[str, Any]:
    g = store.create_goal(title, done_when=done_when)
    return {"goal": g.as_dict()}


@audited(scope="goals.edit", destructive=True)
def _audited_update(*, goal_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if store.get_goal(goal_id) is None:
        raise ValueError(f"no goal with id {goal_id}")
    updated = store.update_goal(goal_id, **fields)
    return {"goal": updated.as_dict() if updated else None}


@audited(scope="goals.approve_proposal", destructive=True)
def _audited_approve_proposal(*, goal_id: str, prefer_local: bool, session: Session) -> dict[str, Any]:
    g = store.get_goal(goal_id)
    if g is None:
        raise ValueError(f"no goal with id {goal_id}")
    if g.status != "active":
        raise ValueError(f"cannot bridge a goal in status '{g.status}' (only active goals)")
    proposal = (g.next_action or "").strip()
    if not proposal:
        raise ValueError("goal has no proposed next_action to approve")

    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    plan, cost = planner.generate_plan(
        proposal, router=rt, user_id=prof.id,
        title=f"[goal] {g.title}", prefer_local=prefer_local,
        meta={"goal_id": g.id, "origin": "goal_bridge"},
    )

    note = ""
    if plan.steps:
        # Single-gate auto-approve: the operator's goals.approve_proposal consent
        # IS the approval — deliberately NOT routed through planning.approve, so
        # one action yields one approved plan. Steps still never auto-run
        # (execute-next remains its own gated action).
        storage.update_plan_status(plan.id, "approved")
    else:
        note = "plan created with no steps — left as draft (revise before approving)"

    store.update_goal(g.id, linked_plan_id=str(plan.id))
    final = storage.get_plan(plan.id)
    return {
        "goal": store.get_goal(g.id).as_dict(),
        "plan": (final or plan).as_dict(),
        "cost_usd": round(cost, 6),
        "note": note,
    }


@audited(scope="goals.run", destructive=False)
def _audited_run(*, notify: bool) -> dict[str, Any]:
    return scheduler.run_cycle(notify=notify)


def _guard(fn, **kwargs):
    """Run an @audited action and map governance/validation errors to HTTP."""
    try:
        return fn(**kwargs)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── write routes ────────────────────────────────────────────────────

@router.post("/create")
def goals_create(body: CreateRequest):
    return _guard(_audited_create, title=body.title, done_when=body.done_when,
                  approved=body.approved)


@router.post("/{goal_id}/update")
def goals_update(goal_id: str, body: UpdateRequest):
    fields = {k: v for k, v in {"status": body.status, "progress": body.progress}.items()
              if v is not None}
    return _guard(_audited_update, goal_id=goal_id, fields=fields, approved=body.approved)


@router.post("/{goal_id}/approve-proposal")
def goals_approve_proposal(goal_id: str, body: ApproveProposalRequest,
                           session: Session = Depends(get_db)):
    return _guard(_audited_approve_proposal, goal_id=goal_id,
                  prefer_local=body.prefer_local, session=session, approved=body.approved)


@router.post("/run")
def goals_run(body: RunRequest):
    return _guard(_audited_run, notify=body.notify, approved=body.approved)
