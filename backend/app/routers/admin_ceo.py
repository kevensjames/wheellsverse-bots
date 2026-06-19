"""CEO admin endpoints — the operator board for KAI's autonomous CEO layer.

  GET  /admin/ceo/            board: company goal, latest KPIs, recent decisions
  POST /admin/ceo/company     set/replace the company goal (@audited ceo.set_goal, destructive)
  POST /admin/ceo/run         run one heartbeat cycle now (@audited ceo.run, destructive)
  GET  /admin/ceo/decisions   recent executive decisions
  POST /admin/ceo/kill        engage the kill switch (halts autonomous action)
  GET  /admin/ceo/kill        kill-switch status
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.routers.admin_chat import OperatorNotConfigured, _resolve_operator_profile
from app.services.governance import PendingApproval, ScopeDenied, audited, is_scope_enabled
from app.services.router import build_default_router
from app.services.ceo import store, floor, heartbeat

router = APIRouter(
    prefix="/admin/ceo",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class GoalBody(BaseModel):
    goal: str
    target_value: float | None = None
    target_deadline: str | None = None
    approved: bool = False


class RunBody(BaseModel):
    dry_run: bool | None = None
    approved: bool = False


@audited(scope="ceo.set_goal", destructive=True)
def _set_goal(*, goal: str, target_value: float | None, target_deadline: str | None) -> dict[str, Any]:
    return store.upsert_company(goal, target_value=target_value, target_deadline=target_deadline)


@audited(scope="ceo.run", destructive=True)
def _run(*, router_obj, user_id, dry_run: bool | None) -> dict[str, Any]:
    return heartbeat.run_cycle(router=router_obj, user_id=user_id, dry_run=dry_run)


@router.get("/")
def board() -> dict[str, Any]:
    return {
        "company": store.get_company(),
        "snapshot": store.latest_snapshot(),
        "decisions": store.list_decisions(limit=20),
        "org": store.list_org(),
        "killed": floor.is_killed(),
        "scope_on": is_scope_enabled("ceo"),
    }


@router.post("/company")
def set_company(body: GoalBody):
    try:
        return _set_goal(goal=body.goal, target_value=body.target_value,
                         target_deadline=body.target_deadline, approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/run")
def run_cycle(body: RunBody, session: Session = Depends(get_db)):
    try:
        rt = build_default_router(session)
        prof = _resolve_operator_profile(session)
        return _run(router_obj=rt, user_id=prof.id, dry_run=body.dry_run, approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/decisions")
def decisions(limit: int = 50):
    return {"decisions": store.list_decisions(limit=limit)}


@router.post("/kill")
def kill():
    os.environ["KAI_CEO_KILLED"] = "1"
    return {"killed": True}


@router.get("/kill")
def kill_status():
    return {"killed": floor.is_killed()}
