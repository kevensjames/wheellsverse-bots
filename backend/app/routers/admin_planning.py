"""Long-term planning admin endpoints — the operator's Plans surface.

Read endpoints (no audit, non-destructive):
  GET  /admin/planning/stats            counts by status
  GET  /admin/planning/list             list plans (optional ?status=)
  GET  /admin/planning/{plan_id}        full plan: steps + recent runs

Write endpoints (each @audited, destructive=True, gated by KAI_SCOPE_PLANNING):
  POST /admin/planning/create           goal → draft plan (KAI proposes steps)
  POST /admin/planning/{id}/steps       replace steps (operator edits the draft)
  POST /admin/planning/{id}/approve     draft|blocked → approved
  POST /admin/planning/{id}/execute-next run ONE pending step, advance the plan
  POST /admin/planning/{id}/revise      propose a revision for a blocked plan

Proactive (destructive=False — proposes inert draft plans only):
  POST /admin/planning/remediate        scan KAI's detected issues (audit/
                                        failures/lessons/blocked) → draft a plan
                                        per top issue (operator approves to run)
  POST /admin/planning/scout-integrate  scout GitHub for a capability → draft an
                                        integration plan for the top safely-
                                        adoptable repo (reference design only;
                                        operator approves to run; never installs)

The LLM-touching actions (create / execute-next / revise) build the router
and resolve the operator profile INSIDE the @audited function, so a scope-
denied or pending-approval call short-circuits before any model cost.
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
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.planning import (
    executor as ex,
    integration,
    planner,
    remediation,
    revision,
    storage,
)
from app.services.router import build_default_router
from app.services.tools import build_default_registry
from app.services.tools.base import ToolContext

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/planning",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


# ─── reads ───────────────────────────────────────────────────────────


@router.get("/stats")
def planning_stats() -> dict[str, Any]:
    """Counts by status for the dashboard header."""
    return storage.stats()


@router.get("/list")
def planning_list(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    plans = storage.list_plans(status=status, limit=limit)
    return {
        "count": len(plans),
        "plans": [
            {
                "id": p.id,
                "title": p.title,
                "goal": p.goal,
                "status": p.status,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in plans
        ],
    }


@router.get("/{plan_id}")
def planning_get(plan_id: int) -> dict[str, Any]:
    plan = storage.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"no plan with id {plan_id}")
    return {
        "plan": plan.as_dict(),
        "recent_runs": [r.as_dict() for r in storage.list_step_runs(plan_id, limit=50)],
    }


# ─── request models ──────────────────────────────────────────────────


class CreateRequest(BaseModel):
    goal: str
    title: str | None = None
    max_steps: int = 15
    prefer_local: bool = False
    approved: bool = False


class StepIn(BaseModel):
    action: str
    kind: str = "chat"
    tool_name: str | None = None
    on_fail: str | None = None
    on_done: str | None = None


class EditStepsRequest(BaseModel):
    steps: list[StepIn]
    approved: bool = False


class ApproveRequest(BaseModel):
    approved: bool = False


class ExecuteRequest(BaseModel):
    prefer_local: bool = False
    approved: bool = False


class ReviseRequest(BaseModel):
    prefer_local: bool = False
    approved: bool = False


class RemediateRequest(BaseModel):
    max_plans: int = 2
    prefer_local: bool = False
    approved: bool = False


class ScoutIntegrateRequest(BaseModel):
    capability: str
    max_plans: int = 1
    min_stars: int = 100
    language: str | None = None
    prefer_local: bool = False
    approved: bool = False


# ─── audited core actions ────────────────────────────────────────────


@audited(scope="planning.create", destructive=True)
def _audited_create(
    *, goal: str, title: str | None, max_steps: int, prefer_local: bool, session: Session
) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    plan, cost = planner.generate_plan(
        goal, router=rt, user_id=prof.id, title=title,
        max_steps=max_steps, prefer_local=prefer_local,
    )
    return {"plan": plan.as_dict(), "proposal_cost_usd": round(cost, 6)}


@audited(scope="planning.edit", destructive=True)
def _audited_edit_steps(*, plan_id: int, steps: list[dict[str, Any]]) -> dict[str, Any]:
    storage.replace_steps(plan_id, steps)
    plan = storage.get_plan(plan_id)
    return {"plan": plan.as_dict() if plan else None}


@audited(scope="planning.approve", destructive=True)
def _audited_approve(*, plan_id: int) -> dict[str, Any]:
    plan = storage.get_plan(plan_id)
    if plan is None:
        raise ValueError(f"no plan with id {plan_id}")
    if plan.status not in ("draft", "blocked"):
        raise ValueError(
            f"cannot approve a plan in status '{plan.status}' "
            f"(only draft or blocked plans can be approved)"
        )
    updated = storage.update_plan_status(plan_id, "approved")
    return {"plan": updated.as_dict()}


@audited(scope="planning.execute", destructive=True)
def _audited_execute_next(
    *, plan_id: int, prefer_local: bool, session: Session
) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    registry = build_default_registry()
    ctx = ToolContext(user_id=prof.id, session=session)
    runner = ex.make_llm_runner(
        rt, prof.id, registry=registry, tool_context=ctx, prefer_local=prefer_local,
    )
    result = ex.execute_next(plan_id, runner=runner)
    plan = storage.get_plan(plan_id)
    return {"result": result.as_dict(), "plan": plan.as_dict() if plan else None}


@audited(scope="planning.revise", destructive=True)
def _audited_revise(
    *, plan_id: int, prefer_local: bool, session: Session
) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return revision.propose_revision(
        plan_id, router=rt, user_id=prof.id, prefer_local=prefer_local,
    )


@audited(scope="planning.remediate", destructive=False)
def _audited_remediate(
    *, max_plans: int, prefer_local: bool, session: Session
) -> dict[str, Any]:
    # destructive=False: drafts are inert. Each draft still needs a separate
    # planning.approve (destructive=True) before any step executes.
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return remediation.propose_remediations(
        router=rt, user_id=prof.id, max_plans=max_plans, prefer_local=prefer_local,
    )


@audited(scope="planning.scout", destructive=False)
def _audited_scout_integrate(
    *, capability: str, max_plans: int, min_stars: int, language: str | None,
    prefer_local: bool, session: Session,
) -> dict[str, Any]:
    # destructive=False: discovery is read-only and the drafted plan is inert.
    # Each draft still needs a separate planning.approve (destructive=True)
    # before any step runs — and no step ever runs downloaded code.
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return integration.propose_integrations(
        capability, router=rt, user_id=prof.id, session=session,
        max_plans=max_plans, min_stars=min_stars, language=language,
        prefer_local=prefer_local,
    )


# ─── write routes ────────────────────────────────────────────────────


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


@router.post("/create")
def planning_create(body: CreateRequest, session: Session = Depends(get_db)):
    return _guard(
        _audited_create,
        goal=body.goal, title=body.title, max_steps=body.max_steps,
        prefer_local=body.prefer_local, session=session, approved=body.approved,
    )


@router.post("/{plan_id}/steps")
def planning_edit_steps(plan_id: int, body: EditStepsRequest):
    return _guard(
        _audited_edit_steps,
        plan_id=plan_id,
        steps=[s.model_dump() for s in body.steps],
        approved=body.approved,
    )


@router.post("/{plan_id}/approve")
def planning_approve(plan_id: int, body: ApproveRequest):
    return _guard(_audited_approve, plan_id=plan_id, approved=body.approved)


@router.post("/{plan_id}/execute-next")
def planning_execute_next(
    plan_id: int, body: ExecuteRequest, session: Session = Depends(get_db)
):
    return _guard(
        _audited_execute_next,
        plan_id=plan_id, prefer_local=body.prefer_local,
        session=session, approved=body.approved,
    )


@router.post("/{plan_id}/revise")
def planning_revise(
    plan_id: int, body: ReviseRequest, session: Session = Depends(get_db)
):
    return _guard(
        _audited_revise,
        plan_id=plan_id, prefer_local=body.prefer_local,
        session=session, approved=body.approved,
    )


@router.post("/remediate")
def planning_remediate(body: RemediateRequest, session: Session = Depends(get_db)):
    return _guard(
        _audited_remediate,
        max_plans=body.max_plans, prefer_local=body.prefer_local,
        session=session, approved=body.approved,
    )


@router.post("/scout-integrate")
def planning_scout_integrate(
    body: ScoutIntegrateRequest, session: Session = Depends(get_db)
):
    return _guard(
        _audited_scout_integrate,
        capability=body.capability, max_plans=body.max_plans,
        min_stars=body.min_stars, language=body.language,
        prefer_local=body.prefer_local, session=session, approved=body.approved,
    )
