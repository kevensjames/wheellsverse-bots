"""Holding reports — Executive Overview, Company Portfolio, Morning Briefing.

Pure builders (no network, no send). Source-backed only: any datum still marked
REQUIRES_OPERATOR_CONFIRMATION is reported as needing confirmation, never invented.
Live health/monitor data is INJECTED by the caller (the Celery task) so these stay testable;
absent health data is disclosed as unverified, not guessed.
"""
from __future__ import annotations
from typing import Optional
from app.services.holding import registry as reg


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


def build_morning_briefing(*, health: Optional[dict] = None, monitor: Optional[dict] = None,
                           now_iso: str = "") -> dict:
    """Report-only. Reports source-backed status + explicitly what needs confirmation.
    Never fabricates KPI movement, revenue, or system health it wasn't given."""
    ents = reg.all_entities()
    sys_health = health if health else {"status": "UNVERIFIED — no live health data supplied to this briefing"}
    monitor_state = monitor if monitor else {"status": "UNVERIFIED — no monitor snapshot supplied"}
    return {
        "generated_at": now_iso or "",
        "timezone": "America/New_York",
        "system_health": sys_health,
        "monitor": monitor_state,
        "portfolio_status": [
            {"brand": e.brand_name, "status": e.operational_status, "confidence": e.confidence.value}
            for e in ents
        ],
        # honest: priorities/KPI-movement/revenue are NOT invented — they need source-backed inputs
        "kpi_movement": "REQUIRES_OPERATOR_CONFIRMATION (no source-backed KPI feed connected)",
        "todays_priorities": ("No source-backed priorities are connected yet. Confirm holding data / connect a "
                              "source-backed KPI + task feed to enable ranked priorities."),
        "requires_confirmation": reg.needs_confirmation(),
        "delivery": "report generated in-app only — sending to any external recipient requires explicit approval",
    }
