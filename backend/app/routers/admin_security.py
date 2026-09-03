"""Governed, READ-ONLY Cyber Operations endpoints (owner-only kai.ultra, arch §6).

Dormant unless KAI_CYBER_OPS_ENABLED — main.py only includes this router when the flag
is on, so a disabled deployment has ZERO new surface. Every endpoint is GET/read-only and
source-backed: each returns a real source read or a typed NOT_CONNECTED/UNKNOWN/
PHASE_C_PENDING marker (arch §49) — no fabricated node/edge/event/incident/finding.

Defensive-only (arch §0/§1): there is NO POST/execution endpoint here — containment,
blocking, revocation and rollback are DISABLED capabilities, never a route. The privileged
security capabilities are non-selectable by design (see services/security/capabilities.py).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends

from app.routers.admin_chat import require_kai_ultra  # reuse the owner-only gate (no parallel auth)
from app.config import settings
from app.services import security

router = APIRouter(prefix="/admin/cyber", tags=["cyber"],
                   dependencies=[Depends(require_kai_ultra)])


@router.get("/overview")
def cyber_overview():
    return security.overview()


@router.get("/graph")
def cyber_graph():
    return security.graph_view()


@router.get("/events")
def cyber_events(limit: int = 100):
    return security.events(limit=limit)


@router.get("/posture")
def cyber_posture():
    return security.posture_view(settings)


@router.get("/aikido")
def cyber_aikido():
    return security.aikido_view(settings)


@router.get("/risk")
def cyber_risk():
    return security.risk_view(settings)


@router.get("/capabilities")
def cyber_capabilities():
    return security.capability_view()


@router.get("/incidents")
def cyber_incidents():
    # No correlation/triage engine in Phase A (spec §58 Phase C). Zero real incidents
    # shown as zero real — never a fabricated "ATTACK DETECTED" (§55).
    return {"incidents": [], "state": "PHASE_C_PENDING",
            "reason": "correlation/triage = spec §58 Phase C"}
