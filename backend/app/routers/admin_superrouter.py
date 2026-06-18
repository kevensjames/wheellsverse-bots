"""Super-router admin endpoints — decompose a complex ask into a proposed plan.

  GET  /admin/superrouter/should-plan?message=...   free heuristic (no LLM/audit)
  POST /admin/superrouter/propose                   message -> draft plan
                                                    (@audited scope=superrouter)

The proposed plan lands in the Plans tab as a draft; approve it there to run via
the existing executor. The super-router never auto-executes.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.routers.admin_chat import OperatorNotConfigured, _resolve_operator_profile
from app.services import superrouter
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.router import build_default_router

router = APIRouter(
    prefix="/admin/superrouter",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class ProposeRequest(BaseModel):
    message: str
    prefer_local: bool = False
    max_steps: int = 8
    approved: bool = False  # accepted; proposing a draft is non-destructive


@router.get("/should-plan")
def superrouter_should_plan(message: str) -> dict[str, Any]:
    ok, reason = superrouter.should_plan(message)
    return {"should_plan": ok, "reason": reason, "enabled_in_chat": superrouter.enabled()}


@audited(scope="superrouter", destructive=False)
def _audited_propose(*, message: str, prefer_local: bool, max_steps: int,
                     session: Session) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    proposal = superrouter.propose_plan(
        message, router=rt, user_id=prof.id, prefer_local=prefer_local, max_steps=max_steps,
    )
    if proposal is None:
        raise ValueError("could not decompose this request into a plan")
    return proposal


@router.post("/propose")
def superrouter_propose(body: ProposeRequest, session: Session = Depends(get_db)):
    try:
        return _audited_propose(message=body.message, prefer_local=body.prefer_local,
                                max_steps=body.max_steps, session=session)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
