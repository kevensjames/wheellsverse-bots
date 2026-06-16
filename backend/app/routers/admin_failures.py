"""Failure-memory admin endpoints — read-only view of the failure log.

Writes happen automatically (Router.chat hooks into the tool-error path)
or via the failure_lookup tool from within chat. There's no manual-write
endpoint by design: every recorded failure should come from a real failed
action, not operator dictation.

Three reads:
  GET /admin/failures/recent              newest first, optional tool filter
  GET /admin/failures/similar?q=…         top-K Jaccard match
  GET /admin/failures/stats               count by category + tool
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies.admin import require_admin_token
from app.services.failure_memory import find_recent_similar, list_recent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/failures",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


def _to_row(f) -> dict[str, Any]:
    return {
        "id": f.id,
        "when": f.ts,
        "user_id": f.user_id,
        "category": f.category,
        "tool_name": f.tool_name,
        "adapter": f.adapter,
        "prompt": f.prompt,
        "detail": f.detail,
        "context": f.context,
    }


@router.get("/recent")
def failures_recent(
    limit: int = 50,
    category: str | None = None,
    tool_name: str | None = None,
):
    rows = list_recent(limit=limit, category=category, tool_name=tool_name)
    return {"count": len(rows), "failures": [_to_row(f) for f in rows]}


@router.get("/similar")
def failures_similar(q: str = "", k: int = 5):
    rows = find_recent_similar(q, k=k)
    return {
        "query": q,
        "count": len(rows),
        "failures": [
            {**_to_row(f), "similarity_score": round(f.similarity_score, 3)}
            for f in rows
        ],
    }


@router.get("/stats")
def failures_stats():
    """Counts by category + tool — useful for the operator dashboard
    to see what's been breaking the most."""
    rows = list_recent(limit=500)
    by_cat = Counter(f.category for f in rows)
    by_tool = Counter(
        f.tool_name for f in rows if f.tool_name
    )
    return {
        "total_recent": len(rows),
        "by_category": dict(by_cat.most_common()),
        "by_tool": dict(by_tool.most_common(20)),
    }
