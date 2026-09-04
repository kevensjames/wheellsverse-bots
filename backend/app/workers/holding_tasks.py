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


@celery_app.task(name="app.workers.holding_tasks.holding_cycle_tick")
def holding_cycle_tick() -> dict:
    """§30 — one BOUNDED Holding cycle on the existing celery-beat schedule. Reuses build_live_engine (the
    3 fail-closed brakes) + run_manual_cycle (single-flight, idempotent, server-side snapshot) over the
    HoldingDigitalTwin — it creates NO new engine/planner/queue/daemon/loop (§79); run_manual_cycle runs
    EXACTLY ONE existing cycle. Flag-gated by KAI_HOLDING_CYCLE_ENABLED (default off → skip), the same
    dedicated flag that schedules it. Grants NO authority: with the brakes off (default) the engine
    executes 0, so a no-change cycle yields 0 work. Deploy-not-enable — scheduling this does NOT enable
    autonomous execution (the brakes stay authoritative).
    """
    if not getattr(settings, "KAI_HOLDING_CYCLE_ENABLED", False):
        return {"ran": False, "skipped": "KAI_HOLDING_CYCLE_ENABLED is off"}
    from app.services.holding.holding_cycle import build_live_engine
    from app.services.holding.cycle_store import DbCycleStore
    from app.services.holding.manual_cycle import run_manual_cycle, CycleRunning
    from app.services.holding.digital_twin import HoldingDigitalTwin
    now = datetime.now(timezone.utc).isoformat()
    engine = build_live_engine()   # reads the 3 brakes from config; all OFF by default → 0 execution
    try:
        rec = run_manual_cycle(DbCycleStore(), engine,
                               lambda: HoldingDigitalTwin(observed_at=now, today=now[:10]).snapshot(),
                               now=now)
    except CycleRunning:
        return {"ran": False, "skipped": "a holding cycle is already running (single-flight)"}
    except Exception as e:
        return {"ran": False, "error": str(e)[:120]}
    return {"ran": True, "cycle_id": rec.get("cycle_id"), "status": rec.get("status"),
            "auto_actions_executed": rec.get("auto_actions_executed", 0),
            "owner_actions_created": rec.get("owner_actions_created", 0)}
