"""Self-healing admin endpoints — KAI's bounded auto-remediation surface.

  GET  /admin/self-heal/detect   read-only: list detected issues (no audit)
  POST /admin/self-heal/run      apply=false → dry-run (read-only);
                                 apply=true  → run the SAFE auto-fix allowlist.
                                 apply=true is @audited(scope="self_heal",
                                 destructive=True) AND requires the
                                 KAI_SELF_HEAL_ENABLED kill switch — three gates
                                 before KAI mutates anything, and the allowlist
                                 itself is safe + reversible only.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services import self_heal
from app.services.governance import PendingApproval, ScopeDenied, audited

router = APIRouter(
    prefix="/admin/self-heal",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/detect")
def self_heal_detect() -> dict[str, Any]:
    """Read-only: what KAI would consider fixing."""
    return {"issues": self_heal.detect(), "auto_fix_enabled": self_heal.self_heal_enabled()}


class RunRequest(BaseModel):
    apply: bool = False
    approved: bool = False


@audited(scope="self_heal", destructive=True)
def _audited_run() -> dict[str, Any]:
    # destructive=True: only reached for apply=true. The allowlist is safe +
    # reversible (config edit w/ backup, __pycache__ cleanup), and the
    # KAI_SELF_HEAL_ENABLED kill switch is re-checked inside heal().
    return self_heal.heal(apply=True)


@router.post("/run")
def self_heal_run(body: RunRequest) -> dict[str, Any]:
    if not body.apply:
        # Dry-run is read-only — no scope/approval needed.
        return self_heal.heal(apply=False)
    try:
        return _audited_run(approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
