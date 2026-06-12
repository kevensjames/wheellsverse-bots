"""Operator Digest admin endpoints.

  GET  /admin/digest/history   recent digests (reads)
  GET  /admin/digest/latest    most recent digest
  POST /admin/digest/run       build the cross-subsystem digest + (optionally)
                               push to Telegram; @audited scope=digest.run
                               destructive=True (outward send + LLM cost → approved).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.routers.admin_chat import OperatorNotConfigured, _resolve_operator_profile
from app.services.digest import list_digests, send_digest
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.router import build_default_router

router = APIRouter(
    prefix="/admin/digest",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/history")
def digest_history(limit: int = 20) -> dict[str, Any]:
    rows = list_digests(limit=limit)
    return {"count": len(rows), "digests": rows}


@router.get("/latest")
def digest_latest() -> dict[str, Any]:
    rows = list_digests(limit=1)
    return {"digest": rows[0] if rows else None}


@router.get("/scheduler")
def digest_scheduler_status() -> dict[str, Any]:
    """Is the daily auto-send cron live? (KAI_DIGEST_SCHEDULER_ENABLED +
    KAI_DIGEST_HOUR_UTC + KAI_SCOPE_DIGEST)."""
    from app.services.digest.scheduler import status
    return status()


class RunRequest(BaseModel):
    deliver: bool = True          # push to Telegram
    prefer_local: bool = False
    approved: bool = False


@audited(scope="digest.run", destructive=True)
def _audited_run(*, deliver: bool, prefer_local: bool, session: Session) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return send_digest(router=rt, user_id=prof.id, deliver=deliver, prefer_local=prefer_local)


@router.post("/run")
def digest_run(body: RunRequest, session: Session = Depends(get_db)):
    try:
        return _audited_run(
            deliver=body.deliver, prefer_local=body.prefer_local,
            session=session, approved=body.approved,
        )
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
