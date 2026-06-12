"""Research admin endpoints — read-only view of digests + manual trigger.

  GET  /admin/research/status              scheduler health + config
  GET  /admin/research/digests?limit=N     digest header rows, newest first
  GET  /admin/research/latest              most-recent digest in full
  POST /admin/research/run-now             trigger a cycle synchronously
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.admin import require_admin_token
from app.services.governance import audited
from app.services.research import (
    latest_digests,
    list_digests,
    run_research_cycle,
)
from app.services.research.scheduler import is_running
from app.services.research.scorer import (
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    load_interests,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/research",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/status")
def research_status():
    return {
        "scheduler_running": is_running(),
        "interests": load_interests(),
        "thresholds": {
            "medium": MEDIUM_THRESHOLD,
            "high": HIGH_THRESHOLD,
        },
        "telegram_enabled": bool(
            __import__("os").environ.get("TELEGRAM_BOT_TOKEN")
            and __import__("os").environ.get("TELEGRAM_CHAT_ID")
        ),
    }


@router.get("/digests")
def research_digests(limit: int = 30):
    return {"digests": list_digests(limit=limit)}


@router.get("/latest")
def research_latest():
    rows = latest_digests(n=1)
    return {"digest": rows[0] if rows else None}


@audited(scope="research.run_cycle", destructive=False)
def _audited_run_cycle():
    d = run_research_cycle()
    return {
        "id": d.id,
        "high_count": d.high_count,
        "total_items_fetched": d.total_items_fetched,
        "severity_counts": d.severity_counts,
    }


@router.post("/run-now")
def research_run_now():
    """Trigger a cycle synchronously. Audited via @audited so every
    manual run lands in audit.jsonl. Network calls take ~5-10s total."""
    try:
        return _audited_run_cycle()
    except Exception as e:
        logger.exception("research: manual run-now failed")
        raise HTTPException(status_code=502, detail=f"research cycle error: {e}")
