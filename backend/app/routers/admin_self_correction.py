"""Self-correction admin endpoints — read-only view of the critic loop.

Three endpoints:
  GET /admin/self-correction/stats     aggregate counters
  GET /admin/self-correction/events    newest-first events list
  GET /admin/self-correction/latest    most-recent single event (full)

No write endpoint by design — events come from the chat loop, not from
operator dictation. The chat endpoint sets `self_correct=True` to trigger
a correction pass; the events log captures every one.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.dependencies.admin import require_admin_token
from app.services.self_correction.loop import list_events, stats_summary

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/self-correction",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/stats")
def sc_stats():
    return stats_summary()


@router.get("/events")
def sc_events(limit: int = 50):
    rows = list_events(limit=limit)
    return {"count": len(rows), "events": rows}


@router.get("/latest")
def sc_latest():
    rows = list_events(limit=1)
    return {"event": rows[0] if rows else None}
