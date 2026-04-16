#!/usr/bin/env python3
"""
core/analytics_router.py
─────────────────────────────────────────────────────────────────────────────
Analytics API — tracks bot runs and API usage.

GET /api/analytics/overview      — 7d/30d KPI summary
GET /api/analytics/bots          — per-bot stats
GET /api/analytics/usage         — token usage by model/day
GET /api/analytics/timeline?days — daily event counts for Chart.js
─────────────────────────────────────────────────────────────────────────────
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter

from core.chat_db import _get_conn, _lock

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def record_bot_run(
    bot_name: str,
    category: str = "",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    exit_code: Optional[int] = None,
    triggered_by: str = "manual",
):
    """Record a bot run event. Called by bot_manager."""
    rid = str(uuid.uuid4())
    start = start_time or datetime.utcnow().isoformat()
    duration = None
    if start_time and end_time:
        try:
            s = datetime.fromisoformat(start_time)
            e = datetime.fromisoformat(end_time)
            duration = (e - s).total_seconds()
        except Exception:
            pass
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO bot_runs(id,bot_name,category,start_time,end_time,exit_code,duration_sec,triggered_by) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (rid, bot_name, category, start, end_time, exit_code, duration, triggered_by)
        )
        conn.commit()


def record_api_event(
    endpoint: str,
    method: str = "GET",
    status_code: int = 200,
    duration_ms: float = 0,
    model_used: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
):
    """Record an API call event. Called by middleware."""
    eid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        with _lock:
            conn.execute(
                "INSERT INTO api_events(id,endpoint,method,status_code,duration_ms,ts,model_used,tokens_in,tokens_out) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (eid, endpoint, method, status_code, duration_ms, now, model_used, tokens_in, tokens_out)
            )
            conn.commit()
    except Exception:
        pass


@router.get("/overview")
def analytics_overview(days: int = 7):
    """KPI summary for the last N days."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    with _lock:
        total_runs = conn.execute("SELECT COUNT(*) FROM bot_runs WHERE start_time>=?", (since,)).fetchone()[0]
        api_calls = conn.execute("SELECT COUNT(*) FROM api_events WHERE ts>=?", (since,)).fetchone()[0]
        tokens_in = conn.execute("SELECT SUM(tokens_in) FROM api_events WHERE ts>=?", (since,)).fetchone()[0] or 0
        tokens_out = conn.execute("SELECT SUM(tokens_out) FROM api_events WHERE ts>=?", (since,)).fetchone()[0] or 0
        errors = conn.execute("SELECT COUNT(*) FROM api_events WHERE ts>=? AND status_code>=400", (since,)).fetchone()[0]
        bot_crashes = conn.execute("SELECT COUNT(*) FROM bot_runs WHERE start_time>=? AND exit_code!=0 AND exit_code IS NOT NULL", (since,)).fetchone()[0]
    error_rate = round(errors / api_calls * 100, 2) if api_calls else 0
    return {
        "days": days,
        "bot_runs": total_runs,
        "api_calls": api_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": tokens_in + tokens_out,
        "error_rate_pct": error_rate,
        "bot_crashes": bot_crashes,
    }


@router.get("/bots")
def analytics_bots(days: int = 30):
    """Per-bot run statistics."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT bot_name, COUNT(*) as runs, "
            "AVG(duration_sec) as avg_dur, "
            "SUM(CASE WHEN exit_code!=0 AND exit_code IS NOT NULL THEN 1 ELSE 0 END) as errors "
            "FROM bot_runs WHERE start_time>=? GROUP BY bot_name ORDER BY runs DESC",
            (since,)
        ).fetchall()
    return {
        "days": days,
        "bots": [
            {"name": r[0], "runs": r[1], "avg_duration_sec": round(r[2] or 0, 1), "errors": r[3]}
            for r in rows
        ]
    }


@router.get("/usage")
def analytics_usage(days: int = 30):
    """Token usage by model."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT model_used, COUNT(*) as calls, SUM(tokens_in) as tin, SUM(tokens_out) as tout "
            "FROM api_events WHERE ts>=? AND model_used!='' GROUP BY model_used ORDER BY tout DESC",
            (since,)
        ).fetchall()
    return {
        "days": days,
        "models": [
            {"model": r[0], "calls": r[1], "tokens_in": r[2] or 0, "tokens_out": r[3] or 0}
            for r in rows
        ]
    }


@router.get("/timeline")
def analytics_timeline(days: int = 30):
    """Daily event counts — for Chart.js line charts."""
    conn = _get_conn()
    labels = []
    api_counts = []
    bot_counts = []
    for i in range(days - 1, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        labels.append(day_str)
        with _lock:
            api_n = conn.execute(
                "SELECT COUNT(*) FROM api_events WHERE ts LIKE ?", (day_str + "%",)
            ).fetchone()[0]
            bot_n = conn.execute(
                "SELECT COUNT(*) FROM bot_runs WHERE start_time LIKE ?", (day_str + "%",)
            ).fetchone()[0]
        api_counts.append(api_n)
        bot_counts.append(bot_n)
    return {
        "labels": labels,
        "datasets": [
            {"label": "API Calls", "data": api_counts, "color": "#7c6af7"},
            {"label": "Bot Runs", "data": bot_counts, "color": "#00ff88"},
        ]
    }
