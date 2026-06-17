"""Daily check-in admin endpoints.

  GET  /admin/checkin/history     recent check-ins
  GET  /admin/checkin/scheduler   is the daily auto-send live?
  POST /admin/checkin/run-now     send today's check-in now (@audited checkin; force option)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services.checkin import scheduler, storage
from app.services.governance import PendingApproval, ScopeDenied, audited

router = APIRouter(
    prefix="/admin/checkin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class RunRequest(BaseModel):
    force: bool = False
    deliver: bool = True
    approved: bool = False  # accepted; run is non-destructive


@router.get("/history")
def checkin_history(limit: int = 30) -> dict[str, Any]:
    rows = storage.recent(limit=limit)
    return {"count": len(rows), "checkins": [c.as_dict() for c in rows]}


@router.get("/scheduler")
def checkin_scheduler() -> dict[str, Any]:
    return scheduler.status()


@audited(scope="checkin", destructive=False)
def _run(*, force: bool, deliver: bool) -> dict[str, Any]:
    return scheduler.run_checkin(force=force, deliver=deliver)


@router.post("/run-now")
def checkin_run_now(body: RunRequest):
    try:
        return _run(force=body.force, deliver=body.deliver)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
