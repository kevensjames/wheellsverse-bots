"""Cyber Operations evidence bus (arch §3) — read-only joiners over the REAL
in-process sources. NO mutation, NO offensive action, NO fabrication.

Every source function returns ``(data, SourceState)``. A value is either a real
source read or a typed marker (NOT_CONNECTED / UNKNOWN / UNAVAILABLE /
PHASE_C_PENDING) — never a fabricated zero, finding, edge, or "healthy" (arch §49).
Every emitted datum carries an EvidenceReference; the bus stamps its own
``retrieval_time`` (the pure models carry no clock).

Sources (arch §3):
  graph_nodes()      holding registry.all_entities() + entity_status overlay
  graph_edges()      CONFIG-evidence-only edges (bridge/DB/Redis/Railway); §4 no-fabricate-topology
  security_events()  governance.list_actions() -> SecurityEvent
  scan_findings()    core.security_scanner on LOCAL AUTHORIZED paths only
  monitor_signals()  vendored ops.monitor collect()->evaluate(); isolation -> NOT_CONNECTED
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.services.security.models import (
    Edge,
    EvidenceReference,
    Node,
    SecurityEvent,
    Severity,
    SourceState,
)
from app.services.holding import entity_status, registry
from app.services.governance import list_actions


# ── small helpers ───────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(obj) -> str:
    """sha256 over a canonical json view of a record. For DB/Redis edges the
    descriptor is only {"setting": name, "present": True} — the secret VALUE is
    never hashed or read."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _evidence(source_type: str, source_id: str, *, timestamp: str = "UNKNOWN",
              digest: str = "", system: str = "UNKNOWN") -> EvidenceReference:
    return EvidenceReference(source_type=source_type, source_id=source_id, timestamp=timestamp,
                             digest=digest, system=system, retrieval_time=_now())


def _settings():
    from app.config import settings  # lazy: needs DATABASE_URL in env; keeps this module import-light
    return settings


# ── graph nodes: holding registry + live status overlay (arch §2/§6) ─────────
def graph_nodes(*, status_overlay: dict | None = None):
    """11 holding entities as Nodes, joined with the live-status overlay.

    ``status_overlay`` is the injection seam (mirrors the injectable holding
    patterns): None -> call the real ``entity_status.collect_live_entity_status()``
    (best-effort public probes, fail-open); a dict -> use it (tests avoid network).
    Money/customer/banking/legal fields are NEVER placed on a Node — the Node model
    has no slot for them, and ``company`` is read through ``registry.report_value``
    so the confirm-sentinel can never leak (arch §49)."""
    ents = registry.all_entities()
    overlay = status_overlay if status_overlay is not None else entity_status.collect_live_entity_status()
    if not isinstance(overlay, dict):
        overlay = {}

    nodes: list[Node] = []
    for e in ents:
        eid = e.entity_id
        ov = overlay.get(eid)
        # health: probe ok -> healthy, probe present-but-failed -> degraded, no probe -> UNKNOWN
        if ov is None:
            health = "UNKNOWN"                 # solcircle / nurtelle have NO probe (honest gap §4)
        else:
            health = "healthy" if ov.get("ok") else "degraded"
        reachable = bool(ov and ov.get("ok"))
        domains = list(e.domains or [])
        trust_zone = "internet_facing" if domains else "internal"     # real domains field
        exposure = "public" if (domains and reachable) else "UNKNOWN"  # needs domains + live reachability
        os_status = (e.operational_status or "").upper()
        environment = "production" if ("LIVE" in os_status or "DEPLOYED" in os_status) else "UNKNOWN"
        # ownership routed through the honesty gate: a confirm-sentinel returns None -> UNKNOWN
        company, _prov = registry.report_value(eid, "ownership")
        nodes.append(Node(
            node_id=eid,
            system=e.brand_name,
            company=company or "UNKNOWN",
            asset_type=e.entity_type or "UNKNOWN",
            environment=environment,
            trust_zone=trust_zone,
            health=health,
            security_state="UNKNOWN",          # aikido NOT_CONNECTED this sprint
            exposure=exposure,
            findings_count="UNAVAILABLE",      # aikido NOT_CONNECTED -> not a fake zero (§16)
            incident_count="PHASE_C_PENDING",  # no incident engine in Phase A
            last_seen=e.last_verified_at or "UNKNOWN",
        ))
    state = SourceState.WORKING if ents else SourceState.UNAVAILABLE
    return nodes, state


# ── graph edges: config evidence ONLY; never fabricate topology (arch §2/§4) ─
def graph_edges(*, settings=None, env: dict | None = None):
    """Draw an edge ONLY where App B's own config proves it. No config evidence
    -> the edge is not drawn (arch §4). Every drawn edge carries an
    EvidenceReference. The DB/Redis URL VALUES are never read — only presence.

    ``settings`` / ``env`` are injection seams (default: real app settings + os.environ)."""
    s = settings if settings is not None else _settings()
    e = env if env is not None else os.environ
    edges: list[Edge] = []

    # App A -> App B governed bridge. App B proves its side of the trust boundary by
    # being configured to accept App A's forwarded unified session.
    # ponytail: A-side flags (KAI_BRIDGE_ENABLED / KAI_UPSTREAM_URL) live in App A's
    # config; confirming them fully needs an injected App A config (not in Phase A).
    if getattr(s, "OPERATOR_SESSION_ENABLED", False) and getattr(s, "SESSION_SIGNING_SECRET", ""):
        edges.append(Edge(
            source="app_a", target="app_b", relationship="governed_bridge",
            protocol="https", trust_boundary=True, authorization="kai.ultra", exposure="internal",
            evidence=_evidence("config", "OPERATOR_SESSION_ENABLED+SESSION_SIGNING_SECRET",
                               digest=_digest({"setting": "OPERATOR_SESSION_ENABLED", "present": True}),
                               system="app_b")))

    # App B -> PostgreSQL (presence only; value never read)
    if bool(getattr(s, "DATABASE_URL", "")):
        edges.append(Edge(
            source="app_b", target="postgres", relationship="database",
            protocol="postgresql", trust_boundary=True, authorization="service_credential",
            exposure="internal",
            evidence=_evidence("config", "DATABASE_URL",
                               digest=_digest({"setting": "DATABASE_URL", "present": True}),
                               system="app_b")))

    # App B -> Redis (presence only; value never read)
    if bool(getattr(s, "REDIS_URL", "")):
        edges.append(Edge(
            source="app_b", target="redis", relationship="cache",
            protocol="redis", trust_boundary=True, authorization="service_credential",
            exposure="internal",
            evidence=_evidence("config", "REDIS_URL",
                               digest=_digest({"setting": "REDIS_URL", "present": True}),
                               system="app_b")))

    # Railway -> App (deploy) via the platform-injected build SHA env
    sha = e.get("RAILWAY_GIT_COMMIT_SHA") or e.get("GIT_COMMIT_SHA")
    if sha:
        edges.append(Edge(
            source="railway", target="app_b", relationship="deploys",
            protocol="platform", trust_boundary=True, authorization="platform_credential",
            exposure="internal",
            evidence=_evidence("config", "RAILWAY_GIT_COMMIT_SHA",
                               digest=_digest({"setting": "RAILWAY_GIT_COMMIT_SHA", "present": True}),
                               system="app_b")))

    # UNKNOWN (not WORKING) when nothing is provable — no fabricated topology.
    state = SourceState.WORKING if edges else SourceState.UNKNOWN
    return edges, state


# ── security events: governance audit log -> SecurityEvent (arch §2/§10) ─────
def _event_from_audit(r: dict) -> SecurityEvent:
    scope = r.get("scope") or ""
    prefix = scope.split(".")[0] if scope else ""
    company = prefix if (prefix and registry.get(prefix) is not None) else "UNKNOWN"
    destructive = bool(r.get("destructive"))
    success = bool(r.get("success"))
    approved = bool(r.get("approved"))
    # severity: destructive & !success -> HIGH; destructive -> MEDIUM; else INFO
    if destructive and not success:
        severity = Severity.HIGH
    elif destructive:
        severity = Severity.MEDIUM
    else:
        severity = Severity.INFO
    category = "authz_denial" if (destructive and not approved) else "audit_action"
    rid = r.get("id") or "UNKNOWN"
    ts = r.get("ts") or "UNKNOWN"
    ev = _evidence("audit", rid, timestamp=ts, digest=_digest(r), system="app_b")
    return SecurityEvent(
        event_id=rid,                                   # == audit id (stable dedup key)
        timestamp=ts,
        source="governance.audit_log",
        company=company,
        system="app_b",                                 # the governance audit log is App B's
        environment=str(getattr(_settings(), "APP_ENV", "")),
        category=category,
        severity=severity,
        actor=r.get("actor") or "UNKNOWN",
        resource=scope or "UNKNOWN",
        action=r.get("action") or "UNKNOWN",
        result="success" if success else "failure",
        # correlation_id / ip stay UNKNOWN — the audit schema carries neither (arch §10)
        evidence_refs=[ev],
    )


def security_events(limit: int = 100):
    """Newest-first audit records normalized to SecurityEvents. Empty log -> []
    honestly (still a WORKING in-process source, just no records)."""
    recs = list_actions(limit=limit)
    events = [_event_from_audit(r) for r in recs]
    return events, SourceState.WORKING


# ── scanner findings: local-authorized paths only (arch §2/§3) ───────────────
# The scanner module has NO allow-list of its own, so the bus enforces one: a
# defensive scan runs ONLY on local, operator-owned scratch locations.
_AUTHORIZED_ROOTS = [
    Path("/tmp"), Path("/private/tmp"), Path("/var/folders"),
    Path.home() / "Downloads", Path.home() / "Desktop", Path.cwd(),
]


def _under_authorized_root(target: Path) -> bool:
    t = str(target)
    for root in _AUTHORIZED_ROOTS:
        r = str(root.resolve()) if root.exists() else str(root)
        if t == r or t.startswith(r + os.sep):
            return True
    return False


def scan_findings(path: str):
    """Run core.security_scanner on a LOCAL AUTHORIZED path. Unauthorized path ->
    UNKNOWN, not scanned. The scanner is a low-fidelity secondary source and the
    result is labeled with its ceiling (arch §3)."""
    target = Path(path).resolve()
    if not _under_authorized_root(target):
        return ({"path": str(target), "authorized": False,
                 "reason": "path not under an authorized local root — defensive scan is "
                           "local-authorized-only"},
                SourceState.UNKNOWN)

    from core.security_scanner import scan_file, scan_directory  # lazy: needs core on path
    if target.is_dir():
        res = scan_directory(str(target))
        ev_id = f"dir:{target}"
        digest = _digest({"dir": str(target), "files_scanned": res.get("files_scanned")})
    else:
        res = scan_file(str(target))
        ev_id = res.get("sha256") or f"file:{target}"      # scanner gives a real file sha256
        digest = res.get("sha256") or _digest({"file": str(target)})

    res["authorized"] = True
    res["_ceiling"] = ("EICAR SHA-256 hash match + fixed 18-regex heuristic only — no CVE/AV feed, "
                       "no behavioral analysis; low-fidelity secondary source (arch §3)")
    res["_evidence"] = _evidence("scanner", ev_id, timestamp=res.get("scanned_at", "UNKNOWN"),
                                 digest=digest, system="local").as_dict()
    return res, SourceState.WORKING


# ── monitor signals: vendored ops.monitor; isolation -> NOT_CONNECTED (arch §3) ─
def monitor_signals(*, snap: dict | None = None):
    """collect()->evaluate() over the vendored production monitor. Security
    telemetry REQUIRES the owner canary (needs SESSION_SIGNING_SECRET); without it
    we have NO governed security signal, so the source is NOT_CONNECTED — never a
    fake "healthy". A degraded/erroring collection is also NOT_CONNECTED
    (monitor_self). There is deliberately NO top-level "healthy" key.

    ``snap`` is the injection seam (default: real best-effort collection)."""
    from ops.monitor import collectors
    from ops.monitor.run import evaluate

    if snap is None:
        secret = os.environ.get("SESSION_SIGNING_SECRET")
        snap = collectors.collect(secret=secret, do_canary=bool(secret))
    alerts = evaluate(snap)

    errs = list(snap.get("errors", []))
    core_errs = [x for x in errs if not x.startswith("no_secret")]
    canary_ran = bool(snap.get("canary_ran"))
    if not canary_ran:
        state = SourceState.NOT_CONNECTED
        reason = ("owner canary not run (no SESSION_SIGNING_SECRET) — governed security "
                  "telemetry unavailable in isolation")
    elif core_errs:
        state = SourceState.NOT_CONNECTED
        reason = "monitor collection errors: " + ",".join(core_errs)
    else:
        state = SourceState.WORKING
        reason = ""

    self_alert = any(a.signal in ("monitor_self", "monitor_stale") for a in alerts)
    payload = {
        "state": state.value,                 # honest state — NEVER "healthy" in isolation
        "reason": reason,
        "canary_ran": canary_ran,
        "errors": errs,
        "self_alert": self_alert,
        "alerts": [{"signal": a.signal, "severity": a.severity, "summary": a.summary,
                    "service": a.service} for a in alerts],
        "evidence": _evidence("monitor", "monitor_self" if self_alert else "monitor_snapshot",
                              timestamp=_now(),
                              digest=_digest({"errors": errs, "canary_ran": canary_ran}),
                              system="monitor").as_dict(),
    }
    return payload, state


# ── aggregators (arch §6) — graph_view / events (overview() lives in __init__) ─
def graph_view(*, status_overlay: dict | None = None, settings=None, env: dict | None = None) -> dict:
    nodes, ns = graph_nodes(status_overlay=status_overlay)
    edges, es = graph_edges(settings=settings, env=env)
    return {"nodes": [n.as_dict() for n in nodes], "edges": [e.as_dict() for e in edges],
            "nodes_state": ns.value, "edges_state": es.value}


def events(limit: int = 100) -> dict:
    evs, st = security_events(limit=limit)
    return {"events": [e.as_dict() for e in evs], "count": len(evs), "state": st.value}


# NOTE: the served overview() lives in app.services.security.__init__ — it emits
# incidents as {"incidents": []} (no fabricated count) and forwards risk coverage.
# The earlier minimal overview() here was removed to avoid a second, divergent
# aggregate that stamped a fake incidents.count:0 for a Phase-C source (§49).
