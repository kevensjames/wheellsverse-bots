"""Digital-twin admin endpoints — the operator's Twin tab.

Reads + operator-authored entries (admin-token; low-risk self-description):
  GET  /admin/twin/profile     active/proposed profile entries (optional ?section=)
  GET  /admin/twin/drafts      drafts KAI wrote in the operator's voice
  GET  /admin/twin/stats       counts
  POST /admin/twin/entries     operator adds a profile fact (lands active)

Audited actions (KAI_SCOPE_TWIN):
  POST /admin/twin/suggest             KG facts → PROPOSED entries (LLM); destructive=False
  POST /admin/twin/entries/{id}/activate   approve a proposed entry → injects; destructive=True
  POST /admin/twin/entries/{id}/archive    retire an entry; destructive=True
  POST /admin/twin/draft               draft text in the operator's voice (DRAFT
                                       only, never sent); destructive=False
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
from app.services.router import build_default_router
from app.services.twin import draft as twin_draft
from app.services.twin import storage, suggest_entries

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/twin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


# ─── reads + operator-authored entries ───────────────────────────────


class EntryRequest(BaseModel):
    section: str
    text: str


@router.get("/profile")
def twin_profile(section: str | None = None, status: str | None = None, limit: int = 200):
    rows = storage.list_entries(section=section, status=status, limit=limit)
    return {"count": len(rows), "entries": [e.as_dict() for e in rows]}


@router.get("/drafts")
def twin_drafts(limit: int = 50):
    rows = storage.list_drafts(limit=limit)
    return {"count": len(rows), "drafts": [d.as_dict() for d in rows]}


@router.get("/stats")
def twin_stats() -> dict[str, Any]:
    return storage.stats()


@router.post("/entries")
def twin_add_entry(body: EntryRequest):
    """Operator authors a profile fact (lands 'active' — it's their own
    self-description, authoritative)."""
    try:
        e = storage.add_entry(body.section, body.text, source="operator", status="active")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"entry": e.as_dict()}


# ─── audited actions ─────────────────────────────────────────────────


class ApproveRequest(BaseModel):
    approved: bool = False


class SuggestRequest(BaseModel):
    max_entries: int = 8
    prefer_local: bool = False
    approved: bool = False


class DraftRequest(BaseModel):
    task: str
    prefer_local: bool = False
    approved: bool = False


@audited(scope="twin.suggest", destructive=False)
def _audited_suggest(*, max_entries: int, prefer_local: bool, session: Session) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return suggest_entries(
        router=rt, user_id=prof.id, max_entries=max_entries, prefer_local=prefer_local,
    )


@audited(scope="twin.activate", destructive=True)
def _audited_activate(*, entry_id: int) -> dict[str, Any]:
    return {"entry": storage.set_entry_status(entry_id, "active").as_dict()}


@audited(scope="twin.archive", destructive=True)
def _audited_archive(*, entry_id: int) -> dict[str, Any]:
    return {"entry": storage.set_entry_status(entry_id, "archived").as_dict()}


@audited(scope="twin.draft", destructive=False)
def _audited_draft(*, task: str, prefer_local: bool, session: Session) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return twin_draft.draft_as_operator(
        router=rt, user_id=prof.id, task=task, prefer_local=prefer_local,
    )


def _guard(fn, **kwargs):
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


@router.post("/suggest")
def twin_suggest(body: SuggestRequest, session: Session = Depends(get_db)):
    return _guard(_audited_suggest, max_entries=body.max_entries,
                  prefer_local=body.prefer_local, session=session, approved=body.approved)


@router.post("/entries/{entry_id}/activate")
def twin_activate(entry_id: int, body: ApproveRequest):
    return _guard(_audited_activate, entry_id=entry_id, approved=body.approved)


@router.post("/entries/{entry_id}/archive")
def twin_archive(entry_id: int, body: ApproveRequest):
    return _guard(_audited_archive, entry_id=entry_id, approved=body.approved)


@router.post("/draft")
def twin_draft_endpoint(body: DraftRequest, session: Session = Depends(get_db)):
    return _guard(_audited_draft, task=body.task, prefer_local=body.prefer_local,
                  session=session, approved=body.approved)
