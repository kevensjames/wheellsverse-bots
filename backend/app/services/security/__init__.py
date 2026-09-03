"""KAI Cyber Operations (Phase A) — defensive, READ-ONLY security services.

Public read API (arch §1, mirrors governance/__init__.py). Nothing outside this
package imports the internals — the router and the Brain call only these names:

    graph_view       evidence_bus  — holding nodes + config-only edges (arch §6)
    events           evidence_bus  — governance audit -> SecurityEvent (arch §10)
    posture_view     posture       — controls: present vs enforced (arch §22/§23)
    aikido_view      here          — Aikido health+issues; NOT_CONNECTED until secrets (§16)
    risk_view        here          — deterministic versioned risk score (§26), NO LLM
    capability_view  capabilities  — security manifests + selectable gate (§32/§35)
    overview         here          — §36 card / §4 home aggregate

Non-negotiable (arch §0/§49/§59): defensive-only, zero-fake (every value is a real
source read or a typed NOT_CONNECTED/UNKNOWN/UNAVAILABLE/PHASE_C_PENDING marker),
flag-dormant. No mutation, no offensive action, no privileged capability made selectable.
"""
from __future__ import annotations

from app.services.security.models import SourceState
from app.services.security.evidence_bus import graph_view, events, graph_nodes
from app.services.security.posture import posture_view
from app.services.security.capabilities import capability_view
from app.services.security.aikido_adapter import AikidoReadAdapter
from app.services.security.risk_score import compute_risk

__all__ = [
    "graph_view", "events", "posture_view", "aikido_view",
    "risk_view", "capability_view", "overview",
]


def _settings():
    from app.config import settings  # lazy: needs DATABASE_URL in env; keeps import light
    return settings


# ── aikido_view (arch §6/§16) ────────────────────────────────────────────────
def aikido_view(settings=None, *, adapter=None) -> dict:
    """Aikido health + whitelisted/redacted issues. With no AIKIDO_* secrets (or no
    read client wired) this is honestly NOT_CONNECTED with issues=[] — never a fake
    zero (§16). ``adapter`` is the injection seam (default: a client-less adapter)."""
    s = settings if settings is not None else _settings()
    adapter = adapter if adapter is not None else AikidoReadAdapter()
    read = adapter.read(s)            # {state, issues, [reason]}
    return {"health": adapter.health(s), **read}


# ── risk_view (arch §6/§26) ──────────────────────────────────────────────────
def risk_view(settings=None, *, status_overlay=None) -> dict:
    """Deterministic, versioned risk score. The ONLY connected input in Phase A is
    ``internet_exposed`` (a real config-derived count from the graph); every other
    factor's source is NOT_CONNECTED (aikido/monitor) or PHASE_C_PENDING (incidents),
    so it contributes 0 AND leaves an explicit caveat component — the score is never
    silently understated (§16/§26). No LLM. ``status_overlay`` is unused here (kept as
    a seam) — internet_exposed is config-only, so this never touches the network."""
    nodes, _ = graph_nodes(status_overlay={})   # config-only (trust_zone from domains); no probe
    internet_exposed = sum(1 for n in nodes if n.trust_zone == "internet_facing")
    result = compute_risk(
        criticals="NOT_CONNECTED",          # aikido — no secrets
        highs="NOT_CONNECTED",              # aikido
        stale_findings="NOT_CONNECTED",     # aikido
        internet_exposed=internet_exposed,  # REAL — holding domains (config)
        active_incidents="PHASE_C_PENDING", # incident engine = Phase C
        auth_anomalies="NOT_CONNECTED",     # monitor telemetry — not connected in isolation
        audit_gaps="NOT_CONNECTED",         # monitor telemetry
    )
    result["sources"] = {
        "internet_exposed": SourceState.WORKING.value,
        "criticals": SourceState.NOT_CONNECTED.value,
        "highs": SourceState.NOT_CONNECTED.value,
        "stale_findings": SourceState.NOT_CONNECTED.value,
        "active_incidents": SourceState.PHASE_C_PENDING.value,
        "auth_anomalies": SourceState.NOT_CONNECTED.value,
        "audit_gaps": SourceState.NOT_CONNECTED.value,
    }
    # The SCORE is deterministic, but the ASSESSMENT is only as complete as its
    # connected inputs. Do NOT stamp WORKING when most factors are unmeasured — that
    # would read as an all-clear on the §36 card while Aikido/monitor/incidents are
    # NOT_CONNECTED (§49). Surface coverage + the explicit gap list instead.
    connected = [k for k, v in result["sources"].items() if v == SourceState.WORKING.value]
    unmeasured = [k for k, v in result["sources"].items() if v != SourceState.WORKING.value]
    result["connected_sources"] = connected
    result["unmeasured_sources"] = unmeasured
    result["coverage"] = f"{len(connected)}/{len(result['sources'])}"
    result["state"] = SourceState.WORKING.value if not unmeasured else "PARTIAL"
    return result


# ── incidents (arch §14/§58) — never fabricated ──────────────────────────────
def _incidents() -> dict:
    return {"incidents": [], "state": SourceState.PHASE_C_PENDING.value,
            "reason": "correlation/triage = spec §58 Phase C"}


# ── overview (arch §6 /overview + §36 card) ──────────────────────────────────
def overview(*, settings=None, status_overlay=None, app_a=None, adapter=None) -> dict:
    """§36-card / §4-home aggregate: assembles graph + events + posture + risk +
    aikido + capabilities. EVERY value is a real source read or a typed marker
    (NOT_CONNECTED / UNKNOWN / PHASE_C_PENDING) — no fabricated count, finding, or
    incident. Injection seams (status_overlay/app_a/adapter) default to the real
    sources; the only possible network call is the graph node live-status overlay."""
    s = settings if settings is not None else _settings()

    g = graph_view(status_overlay=status_overlay, settings=s)   # real nodes + config edges
    ev = events(limit=1000)                                     # real audit -> SecurityEvent
    last_event = ev["events"][0] if ev["events"] else None      # newest-first; None if log empty
    rv = risk_view(settings=s)                                  # deterministic; network-free
    av = aikido_view(s, adapter=adapter)                        # NOT_CONNECTED until secrets
    pv = posture_view(s, app_a=app_a)                           # controls present vs enforced
    cv = capability_view()                                      # manifests + selectable gate

    controls = pv["controls"]
    return {
        "state": SourceState.WORKING.value,
        "systems": {"count": len(g["nodes"]), "state": g["nodes_state"]},
        "edges": {"count": len(g["edges"]), "state": g["edges_state"]},
        "events": {"count": ev["count"], "state": ev["state"], "last_event": last_event},
        "incidents": _incidents(),
        "risk": {"score": rv["score"], "band": rv["band"], "version": rv["version"],
                 "state": rv["state"], "coverage": rv["coverage"],
                 "unmeasured_sources": rv["unmeasured_sources"]},
        "aikido": {"state": av["state"], "reason": av.get("reason", "")},
        "posture": {
            "app_a_status": pv["app_a_status"],
            "controls_total": len(controls),
            "controls_enforced": sum(1 for c in controls if c["enforced"] is True),
            "controls_unknown": sum(1 for c in controls if c["enforced"] == "UNKNOWN"),
        },
        "capabilities": cv["summary"],
    }
