"""Morning briefing runner — report-only, audited, NEVER sends externally.

Schedulable (Celery beat) behind KAI_HOLDING_BRIEFING_ENABLED and callable on-demand by the
governed endpoint. It builds the source-backed briefing, records an audit event, and returns
it. Sending the briefing to any external recipient (email/Telegram/etc.) is a separate,
approval-gated action that is intentionally NOT implemented here.
"""
from __future__ import annotations
from typing import Optional
from app.services.holding.reports import build_morning_briefing


def _live_health() -> Optional[dict]:
    """Best-effort live health via the same public probes the monitor uses. Absent → None
    (the briefing then discloses health as unverified rather than inventing it)."""
    import json, urllib.request
    out = {}
    for name, url in (("app_a", "https://app.wheellsverse.com/api/health"),
                      ("app_b", "https://kai-prod-production.up.railway.app/health")):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                out[name] = {"http": r.status}
        except Exception:
            out[name] = {"http": 0, "note": "unreachable"}
    return out or None


def run_morning_briefing(*, now_iso: str = "", fetch_health: bool = False,
                         audit=None) -> dict:
    """Build the briefing (report-only). If fetch_health, attach live probe results.
    `audit` is an optional callable(event_name, payload) to record an audit event."""
    health = _live_health() if fetch_health else None
    briefing = build_morning_briefing(health=health, now_iso=now_iso)
    if audit is not None:
        try:
            audit("holding.morning_briefing.generated",
                  {"entities": len(briefing["portfolio_status"]),
                   "requires_confirmation": len(briefing["requires_confirmation"]),
                   "delivery": "in-app only (no external send)"})
        except Exception:
            pass  # audit best-effort here; the endpoint enforces fail-closed audit separately
    return briefing
