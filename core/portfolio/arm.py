"""Arm-readiness — the gate before a business's loop may fire its REAL money/outreach/
deploy steps. Every gate must be green AND the operator must explicitly confirm. Ships
refusing (business not registered). This is the last safety layer on top of the per-step
envelope: the loops run perfectly in dry-run; arming is what turns real actions on.
"""
from __future__ import annotations

import os

from core.portfolio import state
from core.portfolio.registry import get_business


def _gates(slug: str) -> list[dict]:
    return [
        {"key": "business_registered",
         "met": os.getenv("WMOS_BUSINESS_REGISTERED", "").strip() == "1",
         "how": "Register the business (LLC/entity) with legal review, then set WMOS_BUSINESS_REGISTERED=1."},
        {"key": "places_key", "met": bool(os.getenv("GOOGLE_PLACES_API_KEY", "").strip()),
         "how": "Set GOOGLE_PLACES_API_KEY (real lead-gen)."},
        {"key": "hunter_key", "met": bool(os.getenv("HUNTER_API_KEY", "").strip()),
         "how": "Set HUNTER_API_KEY (email enrichment)."},
        {"key": "sending_configured",
         "met": bool(os.getenv("INSTANTLY_API_KEY", "").strip() or os.getenv("SMTP_HOST", "").strip()),
         "how": "Configure INSTANTLY_API_KEY or SMTP (outreach sending)."},
        {"key": "outbound_domain", "met": bool(os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "").strip()),
         "how": "Set SITEBOOST_OUTBOUND_DOMAIN (a warmed sending subdomain, not the apex)."},
        {"key": "warmup_complete", "met": bool(state.get_flag(slug, "warmup_complete")),
         "how": "Complete the ~14-day sending-domain warmup, then set the warmup_complete flag."},
    ]


def arm_readiness(slug: str) -> dict:
    """Read-only honest checklist: which gates are met, and the blockers."""
    b = get_business(slug)
    if b is None:
        return {"slug": slug, "known": False}
    gates = _gates(slug)
    return {
        "slug": slug, "name": b.name, "known": True,
        "armed": bool(state.get_flag(slug, "armed")),
        "ready": all(g["met"] for g in gates),
        "gates": gates,
        "blockers": [g["key"] for g in gates if not g["met"]],
    }


def is_armed(slug: str) -> bool:
    return bool(state.get_flag(slug, "armed"))


def arm_business(slug: str, *, confirm: bool = False) -> dict:
    """Arm a business's real actions. Refuses unless EVERY gate is green AND confirm=True."""
    r = arm_readiness(slug)
    if not r.get("known"):
        return {"status": "unknown_business", "slug": slug}
    if not r["ready"]:
        return {"status": "blocked", "slug": slug,
                "reason": "arm-readiness not met — clear the blockers first", "blockers": r["blockers"]}
    if not confirm:
        return {"status": "needs_confirm", "slug": slug,
                "reason": "all gates green — pass confirm=True to arm (this enables REAL actions)."}
    state.set_flag(slug, "armed", True)
    return {"status": "armed", "slug": slug}


def disarm_business(slug: str) -> dict:
    state.set_flag(slug, "armed", False)
    return {"status": "disarmed", "slug": slug}
