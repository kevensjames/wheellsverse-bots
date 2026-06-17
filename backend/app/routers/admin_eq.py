"""Emotional-intelligence admin endpoints — KAI's read of the operator's mood.

Read-only (admin-token): mood detection runs automatically on every chat message
(services/eq), so there's nothing to author here — just observe the trend.
  GET /admin/eq/stats    mood distribution + latest mood
  GET /admin/eq/history  recent mood samples
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies.admin import require_admin_token
from app.services.eq import storage

router = APIRouter(
    prefix="/admin/eq",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/stats")
def eq_stats(window: int = 200) -> dict[str, Any]:
    return storage.stats(window=window)


@router.get("/history")
def eq_history(limit: int = 50) -> dict[str, Any]:
    rows = storage.recent(limit=limit)
    return {"count": len(rows), "samples": [s.as_dict() for s in rows]}
