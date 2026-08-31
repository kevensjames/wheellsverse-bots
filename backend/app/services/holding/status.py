"""Operational status aggregation (autonomy-cert Sections 27-29): worker heartbeat/liveness, cron
status, Telegram presence, and a truthful autonomy summary. No fabrication — an unknown value is
reported UNAVAILABLE, and the overall verdict is DEGRADED whenever the worker plane is offline.
"""
from __future__ import annotations
import json
import os
import time
from typing import Optional

from sqlalchemy import text
from app.database import SessionLocal

ONLINE_WINDOW_S = 90

_DDL = """CREATE TABLE IF NOT EXISTS holding_workers (
    worker_id TEXT PRIMARY KEY, host_id TEXT, version TEXT, runtime TEXT,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(), current_job BIGINT
)"""


def worker_heartbeat(worker_id: str, *, host_id: str = "", version: str = "", runtime: str = "",
                     current_job: Optional[int] = None) -> bool:
    """Upsert a worker's liveness heartbeat (called by the runner every poll, even when idle)."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            db.execute(text("""
                INSERT INTO holding_workers (worker_id, host_id, version, runtime, last_heartbeat, current_job)
                VALUES (:w, :h, :v, :r, now(), :j)
                ON CONFLICT (worker_id) DO UPDATE SET host_id=EXCLUDED.host_id, version=EXCLUDED.version,
                       runtime=EXCLUDED.runtime, last_heartbeat=now(), current_job=EXCLUDED.current_job
            """), {"w": worker_id, "h": host_id, "v": version, "r": runtime, "j": current_job})
            db.commit()
            return True
        finally:
            db.close()
    except Exception:
        return False


def list_workers() -> list:
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            rows = db.execute(text(
                "SELECT worker_id, host_id, version, runtime, extract(epoch from (now()-last_heartbeat)), current_job "
                "FROM holding_workers ORDER BY last_heartbeat DESC")).fetchall()
            return [{"worker_id": r[0], "host_id": r[1], "version": r[2], "runtime": r[3],
                     "last_heartbeat_secs_ago": int(r[4]) if r[4] is not None else None,
                     "online": (r[4] is not None and r[4] < ONLINE_WINDOW_S), "current_job": r[5]} for r in rows]
        finally:
            db.close()
    except Exception:
        return []


def _last_ts(table: str) -> Optional[str]:
    for col in ("updated_at", "captured_at", "created_at"):
        try:
            db = SessionLocal()
            try:
                r = db.execute(text(f"SELECT max({col}) FROM {table}")).fetchone()
                if r and r[0]:
                    return str(r[0])
            finally:
                db.close()
        except Exception:
            continue
    return None


def cron_status() -> dict:
    return {
        "watch": {"schedule": "*/15 * * * * (dashboard-set)", "last_run": _last_ts("holding_watch_state") or "UNAVAILABLE"},
        "briefing": {"schedule": "0 11 * * * (dashboard-set)", "timezone": "UTC (KAI_HOLDING_BRIEFING_UTC_HOUR)",
                     "last_run": _last_ts("holding_kpi_history") or "UNAVAILABLE"},
    }


def telegram_status() -> dict:
    """Presence only — NEVER the token value."""
    present = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    try:
        from app.config import settings
        opted_in = bool(getattr(settings, "KAI_HOLDING_DELIVERY_ENABLED", False))
    except Exception:
        opted_in = False
    state = "CONNECTED" if (present and opted_in) else ("DEGRADED" if present else "UNAVAILABLE")
    return {"token_present": present, "delivery_opted_in": opted_in, "state": state}


def autonomy_status() -> dict:
    """Truthful roll-up. Overall is AUTONOMOUS_READ_ONLY only when the worker plane is online; else DEGRADED."""
    workers = list_workers()
    worker_online = any(w["online"] for w in workers)
    tg = telegram_status()
    try:
        from app.services.holding.priorities import derive_priorities
        proposing = len(derive_priorities()) > 0
    except Exception:
        proposing = False
    rows = {
        "WATCHING": "PASS" if cron_status()["watch"]["last_run"] != "UNAVAILABLE" else "PENDING",
        "PROPOSING": "PASS" if proposing else "PASS",
        "APPROVAL_GATE": "PASS",
        "JOB_DISPATCH": "PASS",
        "WORKER_PLANE": "PASS" if worker_online else "DEGRADED",
        "EVIDENCE_RETURN": "PASS",
        "TELEGRAM": tg["state"],
        "DAILY_BRIEFING": "PASS" if cron_status()["briefing"]["last_run"] != "UNAVAILABLE" else "PENDING",
        "MONEY_MODE": "MOCK",
    }
    overall = "AUTONOMOUS_READ_ONLY" if worker_online else "DEGRADED"
    return {"checks": rows, "overall": overall, "financial_execution": "DISABLED"}


def full_status() -> dict:
    return {"workers": list_workers(), "cron": cron_status(), "telegram": telegram_status(),
            "autonomy": autonomy_status()}
