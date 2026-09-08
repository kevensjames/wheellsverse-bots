"""Operator surface for KAI Computer Operations.

Owner-only, via the SAME `require_kai_ultra` gate the rest of the governed KAI surface
uses. No parallel auth is introduced: a second way to prove you are the owner is a second
thing that can be wrong.

Deliberately absent from this router: any route that accepts a shell command, a raw
harness configuration, an arbitrary filesystem path, or a plugin name. The operator
composes missions in terms the system already understands -- device, autonomy mode,
workspace, allowed applications -- and everything else is derived server-side. A console
that can express "run this string" is a console that can express anything.

Dormant unless KAI_COMPUTER_OPS_ENABLED, so a disabled deployment has zero new surface.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.admin_chat import require_kai_ultra
from app.services.holding import device_identity as di
from app.services.holding import computer_ops_dispatch as dispatch
from app.services.holding.device_identity import (ALL_SCOPES, BASELINE_SCOPES,
                                                  ELEVATED_SCOPES, EnrollmentError)

router = APIRouter(prefix="/admin/kai/computer-operations", tags=["computer-operations"],
                   dependencies=[Depends(require_kai_ultra)])

#: Workspace roots an operator may never authorise, whatever they type. Checked against
#: the RESOLVED path, so `~/x/../..` and a symlink to `/` are caught too.
FORBIDDEN_WORKSPACE_PREFIXES = (
    "/", "/Users", "/System", "/Library", "/etc", "/var", "/private/etc", "/Applications",
)
FORBIDDEN_WORKSPACE_SUBSTRINGS = (
    "/.ssh", "/.aws", "/.gnupg", "/Library/Keychains", "/Library/Application Support/Google/Chrome",
    "/Library/Application Support/Firefox", "/Library/Safari", "/Library/Messages", "/.git",
)


def _store():
    from app.services.holding.device_store import PgDeviceStore
    return PgDeviceStore()


def _missions():
    from app.services.holding.mission_store import PgMissionStore
    return PgMissionStore()


def validate_workspace(path: str) -> str:
    """Resolve and refuse dangerous authorised workspaces.

    Resolution happens BEFORE the checks: an unresolved path is a different string from
    the directory it names, and accepting one means the check and the effect disagree.
    """
    if not path or not path.startswith("/"):
        raise HTTPException(400, "workspace must be an absolute path")
    resolved = os.path.realpath(path)
    if resolved in FORBIDDEN_WORKSPACE_PREFIXES or resolved == os.path.expanduser("~"):
        raise HTTPException(400, f"{resolved!r} is too broad to authorise as a workspace")
    for frag in FORBIDDEN_WORKSPACE_SUBSTRINGS:
        if frag in resolved:
            raise HTTPException(400, f"workspace resolves into a protected location ({frag})")
    if resolved != os.path.normpath(resolved):
        raise HTTPException(400, "workspace path did not normalise")
    return resolved


# ------------------------------------------------------------------ devices

class EnrollBody(BaseModel):
    model_config = {"extra": "ignore"}
    device_name: str = Field(min_length=1, max_length=120)


class ConfirmBody(BaseModel):
    model_config = {"extra": "ignore"}
    fingerprint: str


class ScopeBody(BaseModel):
    model_config = {"extra": "ignore"}
    scopes: list[str]


def _device_json(d) -> dict[str, Any]:
    return {
        "device_id": d.device_id, "name": d.name, "status": d.status,
        "fingerprint": d.fingerprint, "os": d.os, "arch": d.arch,
        "granted_scopes": sorted(d.granted_scopes),
        "elevated_granted": sorted(d.granted_scopes & ELEVATED_SCOPES),
        "credential_age_seconds": int(d.credential_age.total_seconds()),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "confirmed_at": d.confirmed_at.isoformat() if d.confirmed_at else None,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "revoked_at": d.revoked_at.isoformat() if d.revoked_at else None,
        "revocation_reason": d.revocation_reason,
    }


@router.get("/devices")
def list_devices():
    return {"devices": [_device_json(d) for d in _store().list_devices()],
            "baseline_scopes": sorted(BASELINE_SCOPES),
            "elevated_scopes": sorted(ELEVATED_SCOPES)}


@router.get("/devices/{device_id}")
def get_device(device_id: str):
    d = _store().get_device(device_id)
    if d is None:
        raise HTTPException(404, "unknown device")
    return _device_json(d)


@router.post("/devices/enroll")
def create_enrollment(body: EnrollBody):
    """Returns the pairing code ONCE. It is stored only as a hash."""
    code = di.begin_enrollment(_store(), owner_id="owner", device_name=body.device_name)
    return {"pairing_code": code, "expires_in_seconds": int(di.PAIRING_TTL.total_seconds()),
            "next": "run the connector's `enroll` command with this code within the window"}


@router.post("/devices/{device_id}/confirm")
def confirm_device(device_id: str, body: ConfirmBody):
    try:
        d = di.confirm_enrollment(_store(), device_id=device_id,
                                  fingerprint_shown=body.fingerprint, owner_id="owner")
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _device_json(d)


@router.post("/devices/{device_id}/scopes/grant")
def grant_device_scopes(device_id: str, body: ScopeBody):
    """Each elevated scope is a separate operator decision; this route grants only what
    is named, and never expands a request into a bundle."""
    requested = set(body.scopes)
    unknown = requested - ALL_SCOPES
    if unknown:
        raise HTTPException(400, f"unknown scopes: {sorted(unknown)}")
    try:
        d = di.grant_scopes(_store(), device_id=device_id, scopes=requested, owner_id="owner")
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _device_json(d)


@router.post("/devices/{device_id}/scopes/revoke")
def revoke_device_scopes(device_id: str, body: ScopeBody):
    return _device_json(di.revoke_scopes(_store(), device_id=device_id, scopes=set(body.scopes)))


@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: str, body: dict | None = None):
    reason = (body or {}).get("reason", "revoked by operator")
    return _device_json(di.revoke_device(_store(), device_id=device_id, reason=str(reason)[:200]))


# ----------------------------------------------------------------- missions

class MissionBody(BaseModel):
    model_config = {"extra": "ignore"}
    device_id: str
    objective: str = Field(min_length=1, max_length=2000)
    autonomy_mode: str
    workspace: str
    allowed_apps: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    # NO Pydantic bounds. clamp_mission_seconds() is the single enforcement point:
    # a `le=` here rejected an over-large request with 422 BEFORE the clamp ran, which
    # made the clamp dead code and meant two rules disagreed about the same field.
    max_duration_seconds: int = 900
    model_policy: str = "LOCAL_ONLY"
    data_egress: str = "NONE"


@router.get("/missions")
def list_missions(limit: int = 50):
    return {"missions": [_missions().to_json(m) for m in _missions().list_recent(limit)]}


@router.get("/missions/{mission_id}")
def get_mission(mission_id: str):
    m = _missions().get(mission_id)
    if m is None:
        raise HTTPException(404, "unknown mission")
    return _missions().to_json(m, full=True)


@router.post("/missions")
def create_mission(body: MissionBody):
    if body.autonomy_mode not in ("OBSERVE", "ASSIST", "EXECUTE_SCOPED"):
        raise HTTPException(400, f"unknown autonomy mode {body.autonomy_mode!r}")
    if body.model_policy != "LOCAL_ONLY":
        raise HTTPException(400, "only LOCAL_ONLY has been verified end to end; "
                                 "CLOUD_APPROVED requires its own overlay and recorded egress consent")
    workspace = validate_workspace(body.workspace)
    device = _store().get_device(body.device_id)
    if device is None:
        raise HTTPException(404, "unknown device")
    if device.status != di.DeviceStatus.ACTIVE:
        raise HTTPException(400, f"device is {device.status}; only an ACTIVE device may receive work")
    # A mission cannot require more than the device has been separately granted.
    needed = {"EXECUTE_SCOPED": "computer.workspace.write"}.get(body.autonomy_mode)
    if needed and needed not in device.granted_scopes:
        raise HTTPException(403, f"device lacks {needed!r}; grant it explicitly before "
                                 "creating an EXECUTE_SCOPED mission")
    from app.services.holding.computer_ops_limits import clamp_mission_seconds
    m = _missions().create(tenant="default", device_id=body.device_id, objective=body.objective,
                           autonomy_mode=body.autonomy_mode, workspace=workspace,
                           allowed_apps=body.allowed_apps, allowed_domains=body.allowed_domains,
                           max_duration_seconds=clamp_mission_seconds(body.max_duration_seconds),
                           actor="owner")
    return _missions().to_json(m, full=True)


@router.post("/missions/{mission_id}/cancel")
def cancel_mission(mission_id: str, body: dict | None = None):
    reason = (body or {}).get("reason", "cancelled by operator")
    return _missions().to_json(
        dispatch.cancel_mission(_missions(), mission_id, actor="owner", reason=str(reason)[:200]))


@router.post("/missions/{mission_id}/pause")
def pause_mission(mission_id: str):
    return _missions().to_json(_missions().pause(mission_id, actor="owner"))


class ApprovalBody(BaseModel):
    model_config = {"extra": "ignore"}
    approved: bool


@router.post("/missions/{mission_id}/approvals/{approval_id}")
def resolve_approval(mission_id: str, approval_id: str, body: ApprovalBody):
    try:
        a = dispatch.resolve_approval(_missions(), mission_id, approval_id,
                                      approved=body.approved, owner_id="owner")
    except dispatch.DispatchError as exc:
        raise HTTPException(400, str(exc)) from exc
    return a


@router.get("/missions/{mission_id}/evidence")
def mission_evidence(mission_id: str):
    m = _missions().get(mission_id)
    if m is None:
        raise HTTPException(404, "unknown mission")
    return {"mission_id": mission_id, "evidence": m.evidence, "history": m.history}


# ------------------------------------------------------------------ runtime

@router.post("/missions/sweep")
def sweep_overdue():
    """Fail missions past their deadline. Called by the panel on load and available to an
    operator directly; a wedged worker cannot be relied on to time itself out."""
    return {"expired": _missions().expire_overdue()}


@router.get("/runtime")
def runtime_status():
    """Truthful runtime and containment state. Every field is probed or read, never a
    constant, so the panel cannot render READY for something that is not."""
    from app.services.holding.computer_ops_runtime import runtime_report
    return runtime_report()


@router.post("/stop")
def stop_computer_control(body: dict | None = None):
    """STOP COMPUTER CONTROL. Independent of any mission page or worker being alive."""
    reason = (body or {}).get("reason", "STOP invoked by operator")
    store = _missions()
    stopped = dispatch.stop_all(store, store.list_active(), actor="owner")
    store.set_stop(True, reason=str(reason)[:200])
    return {"stopped_missions": [m.mission_id for m in stopped],
            "stop_engaged": True, "reason": reason}


@router.post("/stop/release")
def release_stop(body: dict | None = None):
    _missions().set_stop(False, reason=str((body or {}).get("reason", "released"))[:200])
    return {"stop_engaged": False}
