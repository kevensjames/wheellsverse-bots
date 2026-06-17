"""KAI persona admin endpoints — shape KAI's own character.

Reads + operator-authored traits (admin-token):
  GET  /admin/persona/profile   active/proposed traits (optional ?section=)
  GET  /admin/persona/stats     counts
  POST /admin/persona/entries   operator adds a trait (lands 'active')

Audited (KAI_SCOPE_PERSONA):
  POST /admin/persona/entries/{id}/activate   approve a proposed trait; destructive=True
  POST /admin/persona/entries/{id}/archive    retire a trait; destructive=True

The active traits inject at the TOP of every system prompt (see
services/persona/injection.py), so edits here change how KAI talks immediately.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.persona import storage

router = APIRouter(
    prefix="/admin/persona",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class EntryRequest(BaseModel):
    section: str
    text: str


class ApproveRequest(BaseModel):
    approved: bool = False


@router.get("/profile")
def persona_profile(section: str | None = None, status: str | None = None, limit: int = 200):
    storage.seed_defaults()  # idempotent: ensures the warm default exists on first view
    rows = storage.list_entries(section=section, status=status, limit=limit)
    return {"count": len(rows), "entries": [e.as_dict() for e in rows],
            "sections": list(storage.SECTIONS)}


@router.get("/stats")
def persona_stats() -> dict[str, Any]:
    return storage.stats()


@router.post("/entries")
def persona_add_entry(body: EntryRequest):
    """Operator authors a persona trait (lands 'active' — it's KAI's character,
    operator-defined)."""
    try:
        e = storage.add_entry(body.section, body.text, source="operator", status="active")
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"entry": e.as_dict()}


@audited(scope="persona.activate", destructive=True)
def _audited_activate(*, entry_id: int) -> dict[str, Any]:
    return {"entry": storage.set_entry_status(entry_id, "active").as_dict()}


@audited(scope="persona.archive", destructive=True)
def _audited_archive(*, entry_id: int) -> dict[str, Any]:
    return {"entry": storage.set_entry_status(entry_id, "archived").as_dict()}


def _guard(fn, **kwargs):
    try:
        return fn(**kwargs)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/entries/{entry_id}/activate")
def persona_activate(entry_id: int, body: ApproveRequest):
    return _guard(_audited_activate, entry_id=entry_id, approved=body.approved)


@router.post("/entries/{entry_id}/archive")
def persona_archive(entry_id: int, body: ApproveRequest):
    return _guard(_audited_archive, entry_id=entry_id, approved=body.approved)
