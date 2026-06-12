"""KAI Supreme admin endpoints — surface scan results in /admin.

Mirrors the standalone NarAI Supreme .app's data shape so any tooling
that read scan-*.json files keeps working. All routes admin-gated.

Endpoints:
  GET  /admin/supreme/status         scheduler running? interval? map loaded?
  GET  /admin/supreme/history?limit  proposal metadata (no full findings)
  GET  /admin/supreme/proposal/{n}   one proposal in full
  GET  /admin/supreme/latest         most recent proposal in full
  POST /admin/supreme/scan           run a scan cycle now (manual trigger)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.admin import require_admin_token
from app.services.supreme import (
    latest_proposals,
    list_proposals,
    load_map,
    read_proposal,
)
from app.services.supreme.scanner import run_full_cycle
from app.services.supreme.scheduler import is_running

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/supreme",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/status")
def supreme_status():
    smap = load_map()
    supr = smap.get("supreme", {}) if smap else {}
    return {
        "scheduler_running": is_running(),
        "scan_interval_seconds": supr.get("scan_interval_seconds", 900),
        "telegram_notify_severity": supr.get("telegram_notify_severity", "medium"),
        "active_scans": supr.get("scans", []),
        "map_loaded": bool(smap),
        "map_version": smap.get("version") if smap else None,
    }


@router.get("/history")
def supreme_history(limit: int = 50):
    """Return proposal metadata — name, timestamp, finding count, severity
    counts. Each row is light so 50–100 fits cheaply in the dashboard."""
    return {"proposals": list_proposals(limit=limit)}


@router.get("/latest")
def supreme_latest():
    """Most recent proposal in full. Returns {} when no scans yet so the
    dashboard can render the empty state without a 404 dance."""
    proposals = latest_proposals(n=1)
    if not proposals:
        return {"proposal": None}
    return {"proposal": proposals[0]}


@router.get("/proposal/{name}")
def supreme_get_proposal(name: str):
    data = read_proposal(name)
    if data is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return data


@router.post("/scan")
def supreme_run_scan_now():
    """Manual 'run scan now' trigger. Runs synchronously — typical full
    cycle takes 1-3 seconds. Telegram alert still fires for medium+.
    """
    try:
        path, findings = run_full_cycle()
    except Exception as e:
        logger.exception("supreme: manual scan crashed")
        raise HTTPException(status_code=502, detail=f"scan error: {e}")
    return {
        "proposal_name": path.name,
        "finding_count": len(findings),
    }
