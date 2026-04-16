#!/usr/bin/env python3
"""
core/log_router.py
─────────────────────────────────────────────────────────────────────────────
Log aggregation API.

GET /api/logs/all?since=60       — merged logs from last N minutes
GET /api/logs/sources            — list available log files
GET /api/logs/{source}?lines=200 — tail a specific log file
GET /api/logs/search?q=&source=  — search across logs
GET /api/logs/stats              — error/warning counts
─────────────────────────────────────────────────────────────────────────────
"""

from typing import Optional
from fastapi import APIRouter
from core.log_aggregator import (
    get_all_logs, get_log_stats, get_sources, search_logs, tail_log,
)

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/all")
def logs_all(since: int = 60):
    return {"logs": get_all_logs(since_minutes=since), "since_minutes": since}


@router.get("/sources")
def logs_sources():
    return {"sources": get_sources()}


@router.get("/search")
def logs_search(q: str = "", source: Optional[str] = None):
    return {"results": search_logs(q, source), "query": q}


@router.get("/stats")
def logs_stats():
    return {"stats": get_log_stats()}


@router.get("/{source}")
def logs_tail(source: str, lines: int = 200):
    return {"lines": tail_log(source, lines), "source": source}
