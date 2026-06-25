"""Portfolio HQ admin API — the W-MOS Master Supervisor operator surface.

Read + control over the dormant Plan-1 engine: the 10-business rollup, the AMBER
approval queue, the orchestrator arm/disarm/kill controls, and the audit log.
Reaches NO adapter — nothing autonomous can fire from here.

All endpoints require X-API-Key == env API_KEY. Mounted at /api/narai/portfolio/*.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from core.portfolio import execute, orchestrator, rollup, state

router = APIRouter(prefix="/api/narai/portfolio", tags=["portfolio-admin"])


def verify_admin_api_key(x_api_key: str = Header(None)) -> bool:
    """FastAPI dep: require X-API-Key matching the platform API_KEY env."""
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(503, "Admin API not configured (API_KEY env missing)")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return True


class ResolveRequest(BaseModel):
    status: str  # "approved" | "rejected"


class OrchestratorRequest(BaseModel):
    action: str  # "arm" | "disarm" | "kill" | "unkill"


@router.get("/overview")
def overview(_=Depends(verify_admin_api_key)) -> dict:
    return {"businesses": rollup.portfolio_overview()}


@router.get("/approvals")
def approvals(status: str | None = None, _=Depends(verify_admin_api_key)) -> dict:
    return {"approvals": state.list_approvals(status)}


@router.post("/approvals/{approval_id}/resolve")
def resolve(approval_id: str, req: ResolveRequest, _=Depends(verify_admin_api_key)) -> dict:
    if req.status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be 'approved' or 'rejected'")
    return {"ok": state.resolve_approval(approval_id, req.status)}


@router.post("/approvals/{approval_id}/execute")
def execute_approved(approval_id: str, _=Depends(verify_admin_api_key)) -> dict:
    return execute.execute_approval(approval_id)


@router.get("/orchestrator")
def orchestrator_state(_=Depends(verify_admin_api_key)) -> dict:
    return orchestrator.control_state()


@router.post("/orchestrator")
def orchestrator_control(req: OrchestratorRequest, _=Depends(verify_admin_api_key)) -> dict:
    if req.action == "arm":
        orchestrator.set_enabled(True)
    elif req.action == "disarm":
        orchestrator.set_enabled(False)
    elif req.action == "kill":
        orchestrator.engage_kill()
    elif req.action == "unkill":
        orchestrator.disengage_kill()
    else:
        raise HTTPException(400, "action must be arm|disarm|kill|unkill")
    return orchestrator.control_state()


@router.get("/audit")
def audit(limit: int = 50, _=Depends(verify_admin_api_key)) -> dict:
    return {"audit": rollup.recent_audit(limit=limit)}
