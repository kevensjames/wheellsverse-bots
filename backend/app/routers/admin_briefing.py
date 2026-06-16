"""Admin endpoint for KAI's Daily Brief.

Gated by the same X-Admin-Token as the rest of /admin/*. Brief generation
also routes through the governance @audited decorator — every call lands
in data/governance/audit.jsonl.

Endpoints:
  POST /admin/briefing/generate   Run today's brief (audit-logged)
  GET  /admin/briefing/audit      Recent governance audit entries
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.services.briefing import generate_daily_brief
from app.services.governance import (
    PendingApproval,
    ScopeDenied,
    list_actions,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/briefing",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.post("/generate")
def briefing_generate(session: Session = Depends(get_db)):
    """Produce today's brief. Audit-logged via @audited decorator on the
    inner function. Free of side effects beyond that one log line."""
    try:
        brief = generate_daily_brief(session)
    except ScopeDenied as e:
        # Surface the scope-not-enabled error helpfully — most likely the
        # operator hasn't set KAI_SCOPE_BRIEFING_DAILY=1 yet.
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("briefing generation failed")
        raise HTTPException(status_code=502, detail=f"brief error: {e}")
    return brief


@router.get("/audit")
def briefing_audit_tail(limit: int = 50):
    """Recent governance audit entries — what KAI has done lately. Filter
    by scope='briefing.daily' on the client if you only want briefs."""
    return {"actions": list_actions(limit=limit)}
