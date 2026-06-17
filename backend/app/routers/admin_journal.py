"""Voice/text journal admin endpoints.

  GET  /admin/journal/history   recent entries (raw + summary + mood)
  GET  /admin/journal/stats     counts by mood
  POST /admin/journal/entries   text → summarize + mood + store + remember
                                (@audited scope=journal; costs one LLM call)

Audio: transcribe via POST /transcribe first, then POST the text here.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.routers.admin_chat import OperatorNotConfigured, _resolve_operator_profile
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.journal import service, storage
from app.services.router import build_default_router

router = APIRouter(
    prefix="/admin/journal",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class JournalRequest(BaseModel):
    text: str
    prefer_local: bool = True
    approved: bool = False  # accepted; entry creation is non-destructive


@router.get("/history")
def journal_history(limit: int = 50) -> dict[str, Any]:
    rows = storage.recent(limit=limit)
    return {"count": len(rows), "entries": [e.as_dict() for e in rows]}


@router.get("/stats")
def journal_stats() -> dict[str, Any]:
    return storage.stats()


@audited(scope="journal", destructive=False)
def _audited_create(*, text: str, prefer_local: bool, session: Session) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return service.create_journal_entry(
        text, session=session, user_id=prof.id, router=rt, prefer_local=prefer_local,
    )


@router.post("/entries")
def journal_add(body: JournalRequest, session: Session = Depends(get_db)):
    try:
        return _audited_create(text=body.text, prefer_local=body.prefer_local, session=session)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
