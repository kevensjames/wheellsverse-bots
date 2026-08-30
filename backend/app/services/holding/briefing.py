"""Morning briefing runner — report-only, audited, NEVER sends externally.

Schedulable (Celery beat) behind KAI_HOLDING_BRIEFING_ENABLED and callable on-demand by the
governed endpoint. It builds the source-backed briefing, records an audit event, and returns
it. Sending the briefing to any external recipient (email/Telegram/etc.) is a separate,
approval-gated action that is intentionally NOT implemented here.
"""
from __future__ import annotations
from app.services.holding.reports import build_morning_briefing
from app.services.holding.signals import collect_live_signals, health_block
from app.services.holding import kpi_history


def run_morning_briefing(*, now_iso: str = "", fetch_health: bool = False,
                         audit=None, persist: bool = False) -> dict:
    """Build the briefing (report-only). If fetch_health, collect live self-observed signals
    (public probes) → ranked priorities + a health block. Movement is computed vs. the last
    STORED snapshot; only the scheduled daily run persists a new snapshot (persist=True) so
    history stays one-per-day and deltas stay meaningful. `audit` is optional callable(name,payload)."""
    signals = collect_live_signals() if fetch_health else None
    health = health_block(signals) if signals else None
    prev = kpi_history.previous_snapshot()          # baseline for real movement (None → disclaimed)
    briefing = build_morning_briefing(health=health, signals=signals, prev_kpis=prev, now_iso=now_iso)
    if persist:
        kpi_history.record_snapshot(briefing["kpis"])   # fails soft (returns False) if DB unavailable
    if audit is not None:
        try:
            audit("holding.morning_briefing.generated",
                  {"entities": len(briefing["portfolio_status"]),
                   "priorities": len(briefing["todays_priorities"]) if isinstance(briefing["todays_priorities"], list) else 0,
                   "requires_confirmation": len(briefing["requires_confirmation"]),
                   "persisted": persist,
                   "delivery": "in-app only (no external send)"})
        except Exception:
            pass  # audit best-effort here; the endpoint enforces fail-closed audit separately
    return briefing
