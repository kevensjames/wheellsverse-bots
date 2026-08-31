"""Daily holding morning-briefing Celery task — REPORT-ONLY, no external send.

Flag-gated by KAI_HOLDING_BRIEFING_ENABLED (default off). When it runs it builds the
source-backed briefing, records an AuditLog row, and stops. It NEVER emails/messages
anyone — external delivery is a separate approval-gated action.
"""
from __future__ import annotations
from datetime import datetime, timezone

from app.config import settings
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.holding_tasks.morning_briefing")
def morning_briefing() -> dict:
    if not getattr(settings, "KAI_HOLDING_BRIEFING_ENABLED", False):
        return {"skipped": "KAI_HOLDING_BRIEFING_ENABLED is off"}
    from app.services.holding.briefing import run_morning_briefing

    audit_ids = []

    def _audit(event: str, payload: dict):
        # durable audit on an isolated session (never blocks the report; report-only anyway)
        try:
            from app.database import SessionLocal
            from app.models.admin import AuditLog
            s = SessionLocal()
            try:
                row = AuditLog(action=event, actor_type="system", event_metadata=payload)
                s.add(row); s.commit()
                audit_ids.append(getattr(row, "id", None))
            finally:
                s.close()
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()
    # persist=True: the daily scheduled run stores a KPI snapshot so movement/deltas accrue
    # (the on-demand endpoint reads movement but does NOT persist — keeps history one-per-day).
    briefing = run_morning_briefing(now_iso=now, fetch_health=True, audit=_audit, persist=True)
    # OPT-IN delivery: strict no-op unless the operator enabled KAI_HOLDING_DELIVERY_ENABLED AND
    # configured a channel. Report-only by default; nothing sends autonomously.
    from app.services.holding.delivery import deliver_briefing
    delivery = deliver_briefing(briefing)
    return {"generated": True, "audit_event_ids": audit_ids,
            "entities": len(briefing.get("portfolio_status", [])),
            "delivery": delivery}
