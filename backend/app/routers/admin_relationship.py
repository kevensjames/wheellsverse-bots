"""Relationship admin endpoints — the KAI↔operator bond.

  GET  /admin/relationship/state       counters + trust/familiarity + days-known
  GET  /admin/relationship/milestones  recent shared milestones
  POST /admin/relationship/milestones  operator logs a milestone (a 'win' nudges trust)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services.relationship import storage

router = APIRouter(
    prefix="/admin/relationship",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


class MilestoneRequest(BaseModel):
    text: str
    kind: str = "moment"


@router.get("/state")
def relationship_state() -> dict[str, Any]:
    return storage.stats()


@router.get("/milestones")
def relationship_milestones(limit: int = 50) -> dict[str, Any]:
    rows = storage.list_milestones(limit=limit)
    return {"count": len(rows), "milestones": [m.as_dict() for m in rows],
            "kinds": list(storage.MILESTONE_KINDS)}


@router.post("/milestones")
def relationship_add_milestone(body: MilestoneRequest):
    try:
        m = storage.add_milestone(body.text, body.kind)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    return {"milestone": m.as_dict()}
