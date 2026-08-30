"""Holding reports — Executive Overview, Company Portfolio, Morning Briefing.

Pure builders (no network, no send). Source-backed only: any datum still marked
REQUIRES_OPERATOR_CONFIRMATION is reported as needing confirmation, never invented.
Live health/monitor data is INJECTED by the caller (the Celery task) so these stay testable;
absent health data is disclosed as unverified, not guessed.
"""
from __future__ import annotations
from typing import Optional
from app.services.holding import registry as reg
from app.services.holding.priorities import derive_priorities


def executive_overview() -> dict:
    ents = reg.all_entities()
    return {
        "entities": [
            {"entity_id": e.entity_id, "brand": e.brand_name, "type": e.entity_type,
             "status": e.operational_status, "stage": e.stage, "confidence": e.confidence.value,
             "repository": e.repository, "deployment": e.deployment}
            for e in ents
        ],
        "counts": {
            "total": len(ents),
            "verified": sum(1 for e in ents if e.confidence.value == "VERIFIED"),
            "needs_confirmation_fields": len(reg.needs_confirmation()),
        },
        # financials are NOT summarized — none are source-backed
        "financials": "REQUIRES_OPERATOR_CONFIRMATION (no source-backed revenue/expense connected)",
        "requires_confirmation": reg.needs_confirmation(),
    }


def company_portfolio(entity_id: str) -> Optional[dict]:
    e = reg.get(entity_id)
    if e is None:
        return None
    d = e.as_dict()
    # replace confirm-markers with an explicit disclaimer object so the UI never shows a fake value
    for fld in ("revenue_metrics", "expense_metrics", "customers", "banking_provider_reference",
                "payment_provider_reference", "compliance_items", "ownership"):
        if d.get(fld) == "REQUIRES_OPERATOR_CONFIRMATION":
            d[fld] = {"value": None, "status": "REQUIRES_OPERATOR_CONFIRMATION"}
    return d


def _movement(cur: dict, prev: Optional[dict]) -> dict:
    """REAL day-over-day deltas from a stored prior snapshot. No history yet → honest baseline note."""
    if not prev:
        return {"status": "baseline captured — deltas available from the next daily briefing (no prior snapshot yet)"}
    flds = ("entities_total", "entities_verified", "open_incidents", "open_risks", "fields_awaiting_confirmation")
    d = {"since": prev.get("as_of", "")}
    for f in flds:
        try:
            d[f] = int(cur.get(f, 0)) - int(prev.get(f, 0))
        except Exception:
            pass
    return d


def build_morning_briefing(*, health: Optional[dict] = None, monitor: Optional[dict] = None,
                           signals: Optional[list] = None, prev_kpis: Optional[dict] = None,
                           now_iso: str = "") -> dict:
    """Report-only. Reports source-backed status + explicitly what needs confirmation.
    Never fabricates KPI movement, revenue, or system health it wasn't given. `signals` are
    live self-observed probes (feed priorities); `prev_kpis` is the last stored snapshot (feed movement)."""
    ents = reg.all_entities()
    sys_health = health if health else {"status": "UNVERIFIED — no live health data supplied to this briefing"}
    monitor_state = monitor if monitor else {"status": "UNVERIFIED — no monitor snapshot supplied"}
    ok_probes = sum(1 for h in (health or {}).values() if isinstance(h, dict) and h.get("http") == 200)
    # Source-backed point-in-time KPI snapshot (real counts from live state — never invented):
    kpis = {
        "as_of": now_iso or "",
        "entities_total": len(ents),
        "entities_verified": sum(1 for e in ents if e.confidence.value == "VERIFIED"),
        "open_incidents": sum(len(getattr(e, "incidents", None) or []) for e in ents),
        "open_risks": sum(len(getattr(e, "risks", None) or []) for e in ents),
        "fields_awaiting_confirmation": len(reg.needs_confirmation()),
        "health": f"{ok_probes}/{len(health)} probes OK" if health else "UNVERIFIED — no live probe this briefing",
    }
    # Deterministic, source-cited ranked priorities (empty only if nothing is surfaced):
    priorities = derive_priorities(health=health, monitor=monitor, signals=signals)
    return {
        "generated_at": now_iso or "",
        "timezone": "America/New_York",
        "system_health": sys_health,
        "monitor": monitor_state,
        "portfolio_status": [
            {"brand": e.brand_name, "status": e.operational_status, "confidence": e.confidence.value}
            for e in ents
        ],
        "kpis": kpis,
        # REAL movement when a prior snapshot exists; honest baseline note on the first run.
        "kpi_movement": _movement(kpis, prev_kpis),
        "todays_priorities": priorities if priorities else (
            "No priorities surfaced — no failing probes, logged risks/incidents, unverified entities, "
            "or pending confirmations."),
        "requires_confirmation": reg.needs_confirmation(),
        "delivery": "report generated in-app only — sending to any external recipient requires explicit approval",
    }
