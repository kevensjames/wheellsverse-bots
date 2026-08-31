"""Owner-only HTTP boundary for the Capability Fabric execution gateway (§3/§6/§16/§31-33).

THIN: it authenticates the owner (reusing require_kai_ultra), builds the authoritative owner
Principal itself (never from the request body §4/§6), and delegates every decision to the ONE shared
CapabilityExecutionService (§29). No arbitrary shell/command/path passthrough exists here (§23) — a
caller may only name a {capability_id, operation} that resolves through the server-owned allowlist.

Dormant unless KAI_CAPABILITY_EXECUTION_ENABLED — main.py includes this router only when the flag
is on, so a disabled deployment has ZERO new surface.
"""
from __future__ import annotations

import time
from collections import deque

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.routers.admin_chat import require_kai_ultra          # reuse the owner-only gate (no parallel auth)
from app.services.capability.seed import seed_registry, seed_graph
from app.services.capability.risk import Principal
from app.services.capability.execution import (CapabilityExecutionService, OPERATIONS, Status,
                                               default_adapter_resolver)
from app.services.capability.brain import CapabilityBrain
from app.services.capability.command import plan_and_execute

router = APIRouter(prefix="/admin/capabilities", tags=["capabilities"],
                   dependencies=[Depends(require_kai_ultra)])   # OWNER-ONLY, all routes (§6)

# ── one process-wide execution plane (the SAME service the Brain flow uses, §29) ──
_recent: deque = deque(maxlen=50)   # §32 invocation history (no secrets/bodies)


def _audit_sink(rec: dict) -> None:
    """Best-effort audit → App B AuditLog (fail-open). Only policy metadata, never secrets (§20)."""
    try:
        from app.database import SessionLocal
        from app.models.admin import AuditLog
        s = SessionLocal()
        try:
            safe = {k: rec.get(k) for k in ("capability", "operation", "status", "decision",
                                            "action_class", "role", "mission_id", "correlation_id")}
            s.add(AuditLog(action=rec.get("event", "capability.event"), actor_type="owner",
                           event_metadata=safe))
            s.commit()
        finally:
            s.close()
    except Exception:
        pass


_registry = seed_registry()
_graph = seed_graph()
_service = CapabilityExecutionService(_registry, audit=_audit_sink)
_brain = CapabilityBrain(_registry, _graph)

_HTTP = {
    Status.OK: 200, Status.APPROVAL_REQUIRED: 202, Status.DENIED: 403,
    Status.OPERATION_NOT_ENABLED: 403, Status.CAPABILITY_UNKNOWN: 404,
    Status.OPERATION_UNKNOWN: 404, Status.CAPABILITY_UNAVAILABLE: 503,
    Status.INPUT_REJECTED: 400, Status.RATE_LIMITED: 429, Status.TIMEOUT: 504,
    Status.FAILED: 502,
}


def _owner() -> Principal:
    """Only an owner reaches here (require_kai_ultra). Build the principal from that fact, never
    from the request body — a forged role/scope in JSON can never grant anything (§4/§6)."""
    return Principal(id="kai-owner", role="owner", scopes=set())


def _server_state(m, adapter) -> str:
    """§33: truthful runtime state for the Nexus market."""
    try:
        healthy = adapter.health().get("state") == "READY"
    except Exception:
        healthy = False
    if m.availability.value == "AVAILABLE" and healthy:
        return "KAI_SERVER_READY"
    if m.certification.value == "CERTIFIED":
        return "CLAUDE_LOCAL"          # certified, but not live in THIS runtime
    if m.certification.value == "PARTIAL":
        return "PARTIAL"
    if m.certification.value in ("EXTERNAL_BLOCKED", "UPSTREAM_UNRESOLVED", "REJECTED"):
        return "EXTERNAL_BLOCKED" if m.certification.value == "EXTERNAL_BLOCKED" else "CATALOG_ONLY"
    return "CATALOG_ONLY"


def _record(er) -> None:
    _recent.appendleft({"capability": er.capability_id, "operation": er.operation, "status": er.status,
                        "duration_ms": er.duration_ms, "provenance": er.provenance,
                        "correlation_id": er.correlation_id, "ts": time.time()})


class InvokeBody(BaseModel):
    """§4: the client submits ONLY these. Authoritative fields (role/scopes/risk/approved/…) are
    not modeled and are ignored — the server derives principal/risk/runtime itself."""
    model_config = {"extra": "ignore"}
    operation: str
    input: dict = Field(default_factory=dict)
    mission_id: str = ""
    context: dict = Field(default_factory=dict)
    idempotency_key: str = ""
    timeout_ms: int | None = None


@router.get("")
def list_capabilities():
    """Executable/known capabilities + their truthful state + allowed operations (§33)."""
    out = []
    for cap_id, ops in OPERATIONS.items():
        m = _registry.get(cap_id)
        adapter = default_adapter_resolver(cap_id)
        out.append({"capability_id": cap_id, "name": m.name, "availability": m.availability.value,
                    "certification": m.certification.value, "server_state": _server_state(m, adapter),
                    "operations": [{"operation": op, "action_class": s.action_class.value,
                                    "v1_eligible": s.v1_eligible, "network": s.network_profile,
                                    "safe_test": s.safe_test is not None} for op, s in ops.items()]})
    return {"capabilities": out, "envelope": "V1 read-only/compute · owner-only", "money_mode": "MOCK"}


@router.get("/{capability_id}/status")
def capability_status(capability_id: str):
    if not _registry.has(capability_id):
        return JSONResponse(status_code=404, content={"error": "unknown capability"})
    m = _registry.get(capability_id)
    adapter = default_adapter_resolver(capability_id)
    try:
        health = adapter.health()
    except Exception:
        health = {"state": "UNKNOWN"}
    last = next((r for r in _recent if r["capability"] == capability_id), None)
    return {"capability_id": capability_id, "server_state": _server_state(m, adapter),
            "availability": m.availability.value, "certification": m.certification.value,
            "health": health, "operations": _service.operations(capability_id), "last_invocation": last}


@router.post("/{capability_id}/invoke")
def invoke_capability(capability_id: str, body: InvokeBody):
    er = _service.invoke(capability_id, body.operation, body.input, _owner(),
                         mission_id=body.mission_id, context=body.context,
                         idempotency_key=body.idempotency_key, timeout_ms=body.timeout_ms)
    _record(er)
    return JSONResponse(status_code=_HTTP.get(er.status, 200), content=er.to_dict())


@router.post("/{capability_id}/test")
def test_capability(capability_id: str):
    """§31: run the capability's SERVER-OWNED safe test (client supplies no parameters)."""
    ops = OPERATIONS.get(capability_id, {})
    op = next((o for o, s in ops.items() if s.safe_test is not None), None)
    if op is None:
        return JSONResponse(status_code=404, content={"error": "no safe test declared for this capability"})
    er = _service.invoke(capability_id, op, dict(ops[op].safe_test), _owner(), mission_id="nexus-safe-test")
    _record(er)
    return JSONResponse(status_code=_HTTP.get(er.status, 200), content=er.to_dict())


@router.post("/command")
def kai_command(payload: dict = Body(default={})):
    """§27/§28: KAI selects a capability via the Brain and runs it through the SAME service.
    Body: {utterance, input, mission_id}. No capability id is named by the caller — the Brain routes."""
    out = plan_and_execute(_brain, _service, str(payload.get("utterance", "")), _owner(),
                           payload.get("input") or {}, mission_id=str(payload.get("mission_id", "")))
    if out.get("result") is not None:
        _record(out["result"])
        out = {**out, "result": out["result"].to_dict()}
    return out


@router.get("/invocations")
def invocation_history():
    """§32: recent invocations (no request bodies, no secrets). GET /admin/capabilities/invocations."""
    return {"recent": list(_recent)}
