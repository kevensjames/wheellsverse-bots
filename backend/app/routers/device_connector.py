"""Device-facing surface for the KAI local connector.

A SEPARATE namespace and a SEPARATE authentication mechanism from the operator routes.
These routes never accept an owner browser cookie or a ROLE_OWNER token: a machine that
drives a desktop must not be able to present the human's credential, and the human's
browser must not be able to reach the device API by accident.

Authentication is a per-request Ed25519 signature over
`v1|METHOD|path|sha256(body)|timestamp|nonce|device_id`, so a captured request proves one
request happened and cannot be turned into another. See device_auth.py for why each
element is in the canonical string.

Authorisation runs the full ladder on EVERY request, in a fixed order, and every rung is
a documented rejection case: STOP, device known, device active, fingerprint confirmed,
signature fresh, signature valid, nonce unburned, scope granted, then -- for
mission-scoped routes -- tenant, mission ownership and lease.

A worker may report results. It may never set COMPLETED.

Dormant unless KAI_COMPUTER_OPS_ENABLED.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from app.services.holding import computer_ops_dispatch as dispatch
from app.services.holding import device_identity as di
from app.services.holding.device_auth import (DeviceAuthError, SignedRequest, parse_headers,
                                              verify_signature)
from app.services.holding.device_identity import DevicePrincipal, DeviceStatus

router = APIRouter(prefix="/api/kai/device", tags=["kai-device"])


def _stores():
    from app.services.holding.device_store import PgDeviceStore
    from app.services.holding.mission_store import PgMissionStore
    return PgDeviceStore(), PgMissionStore()


async def authenticate_device(request: Request, *, required_scope: str) -> tuple[DevicePrincipal, bytes]:
    """The full ladder. Raises 401/403 with a reason that never leaks a signature.

    Ordering is deliberate:
      * STOP first, so a stopped system stops answering before doing any crypto;
      * identity and status before signature, so a revoked device is cheap to refuse;
      * nonce burn AFTER signature verification, so an unauthenticated caller cannot
        burn nonces a real device is about to use (a denial-of-service otherwise).
    """
    devices, missions = _stores()

    if missions.stop_engaged():
        raise HTTPException(423, "STOP COMPUTER CONTROL is engaged")

    body = await request.body()
    try:
        device_id, timestamp, nonce, signature = parse_headers(dict(request.headers))
    except DeviceAuthError as exc:
        raise HTTPException(401, str(exc)) from exc

    device = devices.get_device(device_id)
    if device is None:
        raise HTTPException(401, "unknown device")
    if device.status == DeviceStatus.REVOKED:
        raise HTTPException(403, "device is revoked")
    if device.status != DeviceStatus.ACTIVE:
        raise HTTPException(403, f"device is {device.status}; fingerprint not confirmed")

    signed = SignedRequest(device_id=device_id, timestamp=timestamp, nonce=nonce,
                           signature=signature, method=request.method,
                           path=request.url.path, body=body)
    try:
        verify_signature(device.public_key, signed)
    except DeviceAuthError as exc:
        raise HTTPException(401, str(exc)) from exc

    if not devices.burn_nonce(device_id, nonce,
                              datetime.now(timezone.utc) + timedelta(minutes=10)):
        raise HTTPException(401, "nonce replay detected")

    if required_scope not in device.granted_scopes:
        raise HTTPException(403, f"device lacks scope {required_scope!r}")

    device.last_seen_at = datetime.now(timezone.utc)
    devices.put_device(device)
    return DevicePrincipal(device_id=device_id, scopes=frozenset(device.granted_scopes),
                           lease_expires_at=datetime.now(timezone.utc) + di.LEASE_TTL), body


def _mission_or_404(missions, mission_id: str):
    m = missions.get(mission_id)
    if m is None:
        raise HTTPException(404, "unknown mission")
    return m


# ----------------------------------------------------------------- enrollment

@router.post("/enroll/complete")
async def complete_enrollment(request: Request):
    """Unsigned by necessity -- the device has no accepted key yet. Authority comes from
    the one-time pairing code plus a signature over that code proving key possession, so
    a leaked code alone still enrolls nobody."""
    devices, _ = _stores()
    payload = await request.json()
    import base64
    try:
        device = di.complete_enrollment(
            devices,
            pairing_code=str(payload.get("pairing_code", "")),
            public_key=base64.b64decode(payload.get("public_key", ""), validate=True),
            signature=base64.b64decode(payload.get("signature", ""), validate=True),
            os_name=str(payload.get("os", ""))[:64],
            arch=str(payload.get("arch", ""))[:32])
    except di.EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"malformed enrollment: {type(exc).__name__}") from exc
    # The fingerprint is returned so the connector can PRINT it for the operator to
    # compare against what the panel shows. That comparison is what defeats a
    # machine-in-the-middle that substituted its own key.
    return {"device_id": device.device_id, "fingerprint": device.fingerprint,
            "status": device.status,
            "next": "an operator must confirm this fingerprint in Holding Command"}


# ------------------------------------------------------------------- runtime

@router.post("/heartbeat")
async def heartbeat(request: Request):
    principal, _ = await authenticate_device(request, required_scope="computer.health.read")
    _, missions = _stores()
    return {"ok": True, "device_id": principal.device_id,
            "stop_engaged": missions.stop_engaged(),
            "server_time": datetime.now(timezone.utc).isoformat()}


@router.post("/attestation")
async def report_attestation(request: Request):
    """The connector reports what the startup gate produced. KAI records it; it does not
    take the worker's word for containment being correct -- the digest is compared with
    what the operator surface shows, so a mismatch is visible rather than silent."""
    principal, body = await authenticate_device(request, required_scope="computer.health.read")
    import json
    payload = json.loads(body or b"{}")
    _, missions = _stores()
    mission_id = str(payload.get("mission_id", ""))
    if mission_id:
        m = _mission_or_404(missions, mission_id)
        if m.device_id != principal.device_id:
            raise HTTPException(403, "mission belongs to another device")
        m.attestation_digest = str(payload.get("attestation_digest", ""))[:128]
        m.log("attestation_reported", digest=m.attestation_digest[:16],
              containment=str(payload.get("containment", ""))[:80])
        missions.put(m)
    return {"recorded": True}


# ------------------------------------------------------------------ missions

@router.post("/lease")
async def lease_next(request: Request):
    principal, _ = await authenticate_device(request, required_scope="computer.mission.receive")
    _, missions = _stores()
    m = dispatch.lease_next(missions, principal, stop_engaged=missions.stop_engaged)
    if m is None:
        return {"mission": None}
    return {"mission": missions.to_json(m, full=True)}


@router.post("/missions/{mission_id}/renew")
async def renew(request: Request, mission_id: str):
    principal, _ = await authenticate_device(request, required_scope="computer.mission.status.write")
    _, missions = _stores()
    try:
        return missions.to_json(dispatch.renew_lease(missions, principal, mission_id))
    except dispatch.NotAuthorised as exc:
        raise HTTPException(403, str(exc)) from exc
    except dispatch.DispatchError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/missions/{mission_id}/progress")
async def progress(request: Request, mission_id: str):
    principal, body = await authenticate_device(request, required_scope="computer.mission.status.write")
    import json
    payload = json.loads(body or b"{}")
    _, missions = _stores()
    try:
        m = dispatch.submit_progress(missions, principal, mission_id,
                                     status=str(payload.get("status", "")),
                                     note=str(payload.get("note", ""))[:500])
    except dispatch.NotAuthorised as exc:
        # This is where a worker attempting COMPLETED lands.
        raise HTTPException(403, str(exc)) from exc
    except dispatch.DispatchError as exc:
        raise HTTPException(409, str(exc)) from exc
    return missions.to_json(m)


@router.post("/missions/{mission_id}/evidence")
async def evidence(request: Request, mission_id: str):
    principal, body = await authenticate_device(request, required_scope="computer.evidence.write")
    import json
    payload = json.loads(body or b"{}")
    _, missions = _stores()
    from app.services.capability.results import scan_for_injection
    note = json.dumps(payload)[:20000]
    findings = []
    try:
        findings = scan_for_injection(note) or []
    except Exception:  # noqa: BLE001 - scanning must never block evidence capture
        findings = []
    try:
        m = dispatch.attach_evidence(missions, principal, mission_id,
                                     evidence={**payload, "injection_findings": findings})
    except dispatch.NotAuthorised as exc:
        raise HTTPException(403, str(exc)) from exc
    return {"recorded": True, "injection_findings": findings,
            "evidence_count": len(m.evidence)}


@router.post("/missions/{mission_id}/permission")
async def request_permission(request: Request, mission_id: str):
    principal, body = await authenticate_device(request, required_scope="computer.permission.request")
    import json
    payload = json.loads(body or b"{}")
    _, missions = _stores()
    try:
        req = dispatch.request_approval(missions, principal, mission_id,
                                        action=str(payload.get("action", ""))[:80],
                                        target=str(payload.get("target", ""))[:400],
                                        params=payload.get("params") or {})
    except dispatch.NotAuthorised as exc:
        raise HTTPException(403, str(exc)) from exc
    return req


@router.post("/missions/{mission_id}/permission/{approval_id}/consume")
async def consume_permission(request: Request, mission_id: str, approval_id: str):
    """Re-binds the approval to what is actually about to happen."""
    principal, body = await authenticate_device(request, required_scope="computer.permission.request")
    import json
    payload = json.loads(body or b"{}")
    _, missions = _stores()
    try:
        a = dispatch.consume_approval(missions, principal, mission_id, approval_id,
                                      action=str(payload.get("action", "")),
                                      target=str(payload.get("target", "")),
                                      params=payload.get("params") or {})
    except dispatch.NotAuthorised as exc:
        raise HTTPException(403, str(exc)) from exc
    return a


@router.post("/missions/{mission_id}/ack-cancel")
async def ack_cancel(request: Request, mission_id: str):
    """The connector confirms it has released control. Recorded as evidence that STOP
    actually propagated rather than merely being requested."""
    principal, _ = await authenticate_device(request, required_scope="computer.mission.status.write")
    _, missions = _stores()
    m = _mission_or_404(missions, mission_id)
    if m.device_id != principal.device_id:
        raise HTTPException(403, "mission belongs to another device")
    m.log("cancellation_acknowledged", device=principal.device_id)
    missions.put(m)
    return {"acknowledged": True, "status": m.status}


@router.post("/missions/{mission_id}/reconnect")
async def reconnect(request: Request, mission_id: str):
    """Whether stale work may continue. Defaults to no."""
    principal, _ = await authenticate_device(request, required_scope="computer.mission.receive")
    devices, missions = _stores()
    device = devices.get_device(principal.device_id)
    decision = dispatch.evaluate_reconnect(
        missions, principal, mission_id,
        device_status=device.status if device else "UNKNOWN",
        stop_engaged=missions.stop_engaged())
    return {"resume": decision.resume, "reason": decision.reason,
            "requires_reapproval": decision.requires_reapproval}
