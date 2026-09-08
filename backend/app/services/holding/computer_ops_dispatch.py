"""Dispatch contracts for KAI Computer Operations (Phase 8).

This is NOT a second mission system. It is the authorization and state layer that sits
over the existing pieces -- worker_jobs for the leased exactly-once channel,
action_confirmation for single-use owner approvals, brakes for STOP, mission for
lifecycle and evidence -- and adds the two things a remote machine changes:

  1. every operation is authorised against a DEVICE principal, not a human session;
  2. the worker is never trusted about outcomes.

The invariant that shapes the whole file: A WORKER CANNOT SET COMPLETED. It reports what
it did and hands back evidence; only KAI transitions a mission to COMPLETED, and only
after verifying that evidence itself. A worker that claims success while the verifier
disagrees produces a FAILED mission, not a completed one. Without this, "did the work
happen?" collapses into "did the machine say so?", which is precisely the question a
compromised or buggy worker answers wrongly.

Pure logic over injected stores so the rules are testable without a database.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from app.services.holding.device_identity import DevicePrincipal, DeviceStatus

# Mission states owned by KAI. A worker may move a mission only along the reporting
# path (LEASED -> RUNNING) and to FAILED; the rest are KAI's.
QUEUED, LEASED, RUNNING = "QUEUED", "LEASED", "RUNNING"
AWAITING_APPROVAL, VERIFYING = "AWAITING_APPROVAL", "VERIFYING"
COMPLETED, FAILED, CANCELLED, STOPPED = "COMPLETED", "FAILED", "CANCELLED", "STOPPED"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, STOPPED})

#: States a WORKER is permitted to report. COMPLETED is deliberately absent.
WORKER_REPORTABLE = frozenset({RUNNING, AWAITING_APPROVAL, FAILED})

DEFAULT_LEASE = timedelta(seconds=300)


class DispatchError(RuntimeError):
    pass


class NotAuthorised(DispatchError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parameter_digest(params: dict) -> str:
    """Stable digest of the parameters an approval is bound to.

    Sorted and separator-normalised so a semantically identical payload always digests
    the same, and any material change -- a different path, a different target, an extra
    field -- produces a different digest and therefore invalidates the approval.
    """
    return hashlib.sha256(
        json.dumps(params, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass
class Envelope:
    """Carried by every operation. Auditing a mission means replaying these."""
    actor: str
    tenant: str
    device_id: str
    mission_id: str
    correlation_id: str
    capability: str
    autonomy_mode: str
    target: str
    parameter_digest: str
    issued_at: datetime
    expires_at: datetime
    nonce: str
    policy_decision: str = ""
    evidence_refs: list[str] = field(default_factory=list)

    def expired(self) -> bool:
        return _now() >= self.expires_at


@dataclass
class Mission:
    mission_id: str
    tenant: str
    device_id: str
    autonomy_mode: str
    objective: str
    status: str = QUEUED
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    evidence: list[dict] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    attestation_digest: str = ""

    def log(self, event: str, **fields: Any) -> None:
        self.history.append({"event": event, "at": _now().isoformat(), **fields})


class MissionStore(Protocol):
    def get(self, mission_id: str) -> Mission | None: ...
    def put(self, m: Mission) -> None: ...
    def queued_for_device(self, device_id: str) -> list[Mission]: ...
    def burn(self, key: str, expires_at: datetime) -> bool: ...


# --------------------------------------------------------------------- authorization

def _authorise(principal: DevicePrincipal, mission: Mission, scope: str) -> None:
    """Every entry point runs this. Order matters: identity, then binding, then scope."""
    if principal.lease_expired:
        raise NotAuthorised("device lease expired; re-authenticate")
    if principal.device_id != mission.device_id:
        # Cross-device job theft: a valid device asking about another device's mission.
        raise NotAuthorised(
            f"device {principal.device_id} is not assigned mission {mission.mission_id}")
    if not principal.can(scope):
        raise NotAuthorised(f"device lacks scope {scope!r}")


def _require_running(mission: Mission) -> None:
    if mission.status in TERMINAL:
        raise DispatchError(f"mission is {mission.status} and accepts no further work")


# ------------------------------------------------------------------------ lifecycle

def create_mission(store: MissionStore, *, tenant: str, device_id: str, objective: str,
                   autonomy_mode: str, attestation_digest: str, actor: str) -> Mission:
    """Owner-initiated. A mission is bound to ONE device at creation.

    Binding here rather than at lease time is what makes cross-device theft checkable:
    there is never a moment when an unassigned mission is claimable by whoever asks first.
    """
    if not attestation_digest:
        raise DispatchError(
            "refusing to create a mission with no containment attestation; the startup "
            "gate must have run and recorded what the worker will be confined by")
    m = Mission(mission_id=secrets.token_hex(12), tenant=tenant, device_id=device_id,
                autonomy_mode=autonomy_mode, objective=objective,
                attestation_digest=attestation_digest)
    m.log("created", actor=actor, autonomy_mode=autonomy_mode,
          attestation=attestation_digest[:16])
    store.put(m)
    return m


def lease_next(store: MissionStore, principal: DevicePrincipal, *,
               stop_engaged: Callable[[], bool], lease: timedelta = DEFAULT_LEASE) -> Mission | None:
    """A device claims its next eligible mission.

    STOP is checked first and unconditionally: while stopped, no new work is handed out
    no matter how many missions are queued or how recently a lease was granted.
    """
    if stop_engaged():
        return None
    if principal.lease_expired:
        raise NotAuthorised("device lease expired; re-authenticate")
    if not principal.can("computer.mission.receive"):
        raise NotAuthorised("device lacks scope 'computer.mission.receive'")

    for m in store.queued_for_device(principal.device_id):
        if m.status != QUEUED:
            continue
        m.status = LEASED
        m.lease_owner = principal.device_id
        m.lease_expires_at = _now() + lease
        m.attempts += 1
        m.log("leased", device=principal.device_id, attempt=m.attempts)
        store.put(m)
        return m
    return None


def renew_lease(store: MissionStore, principal: DevicePrincipal, mission_id: str,
                *, lease: timedelta = DEFAULT_LEASE) -> Mission:
    m = _get(store, mission_id)
    _authorise(principal, m, "computer.mission.status.write")
    _require_running(m)
    if m.lease_owner != principal.device_id:
        raise NotAuthorised("device does not hold this mission's lease")
    if m.lease_expires_at is not None and _now() >= m.lease_expires_at:
        # An expired lease must be re-claimed, not silently extended: another worker may
        # legitimately have taken over in the interim.
        raise DispatchError("lease already expired; re-claim the mission instead of renewing")
    m.lease_expires_at = _now() + lease
    store.put(m)
    return m


def submit_progress(store: MissionStore, principal: DevicePrincipal, mission_id: str,
                    *, status: str, note: str = "", envelope: Envelope | None = None) -> Mission:
    """The worker reports progress. It may NOT report COMPLETED."""
    m = _get(store, mission_id)
    _authorise(principal, m, "computer.mission.status.write")
    _require_running(m)
    if m.lease_owner != principal.device_id:
        raise NotAuthorised("device does not hold this mission's lease")
    if status not in WORKER_REPORTABLE:
        raise NotAuthorised(
            f"a worker may not set status {status!r}; only KAI transitions a mission to "
            "COMPLETED, and only after verifying evidence itself")
    if envelope is not None and envelope.expired():
        raise NotAuthorised("envelope expired")
    m.status = status
    m.log("progress", status=status, note=note[:200], device=principal.device_id)
    store.put(m)
    return m


def attach_evidence(store: MissionStore, principal: DevicePrincipal, mission_id: str,
                    *, evidence: dict) -> Mission:
    m = _get(store, mission_id)
    _authorise(principal, m, "computer.evidence.write")
    _require_running(m)
    m.evidence.append({"at": _now().isoformat(), "device": principal.device_id, **evidence})
    m.log("evidence_attached", kind=evidence.get("kind", "?"))
    store.put(m)
    return m


# ------------------------------------------------------------------------ approvals

def request_approval(store: MissionStore, principal: DevicePrincipal, mission_id: str,
                     *, action: str, target: str, params: dict,
                     ttl: timedelta = timedelta(minutes=5)) -> dict:
    """The worker asks; it never answers its own question."""
    m = _get(store, mission_id)
    _authorise(principal, m, "computer.permission.request")
    _require_running(m)
    req = {
        "approval_id": secrets.token_hex(8),
        "action": action,
        "target": target,
        "parameter_digest": parameter_digest(params),
        "device_id": principal.device_id,
        "mission_id": mission_id,
        "requested_at": _now().isoformat(),
        "expires_at": (_now() + ttl).isoformat(),
        "state": "PENDING",
    }
    m.approvals.append(req)
    m.status = AWAITING_APPROVAL
    m.log("approval_requested", action=action, target=target)
    store.put(m)
    return req


def resolve_approval(store: MissionStore, mission_id: str, approval_id: str, *,
                     approved: bool, owner_id: str) -> dict:
    """Owner-only. Never reachable by a device principal -- note the signature takes no
    DevicePrincipal at all, so there is no code path by which a worker approves itself."""
    m = _get(store, mission_id)
    for a in m.approvals:
        if a["approval_id"] == approval_id:
            if a["state"] != "PENDING":
                raise DispatchError(f"approval already {a['state']}")
            a["state"] = "APPROVED" if approved else "DENIED"
            a["resolved_by"] = owner_id
            a["resolved_at"] = _now().isoformat()
            m.status = RUNNING if approved else FAILED
            m.log("approval_resolved", approval_id=approval_id, approved=approved)
            store.put(m)
            return a
    raise DispatchError("unknown approval")


def consume_approval(store: MissionStore, principal: DevicePrincipal, mission_id: str,
                     approval_id: str, *, action: str, target: str, params: dict) -> dict:
    """Single-use, and re-bound at the moment of use.

    Checking expiry and state is not enough: the worker must be doing the SAME thing that
    was approved. Re-deriving the digest here is what stops an approval for one target
    being spent on another.
    """
    m = _get(store, mission_id)
    _authorise(principal, m, "computer.permission.request")
    for a in m.approvals:
        if a["approval_id"] != approval_id:
            continue
        if a["state"] != "APPROVED":
            raise NotAuthorised(f"approval is {a['state']}, not APPROVED")
        if datetime.fromisoformat(a["expires_at"]) <= _now():
            raise NotAuthorised("approval expired")
        if a["device_id"] != principal.device_id:
            raise NotAuthorised("approval was issued to a different device")
        if a["action"] != action or a["target"] != target:
            raise NotAuthorised("approval does not cover this action/target")
        if a["parameter_digest"] != parameter_digest(params):
            raise NotAuthorised("parameters changed since approval; it is no longer valid")
        if not store.burn(f"approval:{approval_id}", datetime.fromisoformat(a["expires_at"])):
            raise NotAuthorised("approval already consumed (replay)")
        a["state"] = "CONSUMED"
        m.log("approval_consumed", approval_id=approval_id)
        store.put(m)
        return a
    raise NotAuthorised("unknown approval")


# ---------------------------------------------------------------- KAI-only outcomes

def verify_and_complete(store: MissionStore, mission_id: str, *,
                        verifier: Callable[[Mission], tuple[bool, str]], actor: str) -> Mission:
    """The ONLY path to COMPLETED, and it runs KAI's own verifier.

    A worker's claim of success is an input here, never a conclusion. If the verifier
    disagrees the mission FAILS -- which is the truthful outcome, and is what keeps
    "false COMPLETED states: zero" a property rather than an aspiration.
    """
    m = _get(store, mission_id)
    if m.status in TERMINAL:
        raise DispatchError(f"mission already {m.status}")
    m.status = VERIFYING
    ok, reason = verifier(m)
    m.status = COMPLETED if ok else FAILED
    m.log("verified", ok=ok, reason=reason, actor=actor)
    store.put(m)
    return m


def cancel_mission(store: MissionStore, mission_id: str, *, actor: str, reason: str) -> Mission:
    m = _get(store, mission_id)
    if m.status in TERMINAL:
        return m
    m.status = CANCELLED
    m.lease_owner, m.lease_expires_at = None, None
    m.log("cancelled", actor=actor, reason=reason)
    store.put(m)
    return m


def stop_all(store: MissionStore, missions: list[Mission], *, actor: str) -> list[Mission]:
    """STOP COMPUTER CONTROL. Revokes leases so nothing in flight can continue.

    Already-completed irreversible actions keep their evidence: STOP halts future work,
    it does not rewrite what happened.
    """
    stopped = []
    for m in missions:
        if m.status in TERMINAL:
            continue
        m.status = STOPPED
        m.lease_owner, m.lease_expires_at = None, None
        m.log("stopped", actor=actor)
        store.put(m)
        stopped.append(m)
    return stopped


# ------------------------------------------------------------------------ reconnect

@dataclass
class ReconnectDecision:
    resume: bool
    reason: str
    requires_reapproval: bool = False


def evaluate_reconnect(store: MissionStore, principal: DevicePrincipal, mission_id: str,
                       *, device_status: str, stop_engaged: bool) -> ReconnectDecision:
    """What a worker may do after a disconnect. The default is NOT to resume.

    Everything that made the work safe may have changed while the worker was away: the
    device could be revoked, STOP could be engaged, the lease could have been reclaimed,
    an approval could have expired. So state is revalidated rather than assumed, and
    desktop input specifically is never auto-resumed -- a queued keystroke replayed into
    whatever window is now focused is exactly the failure this prevents.
    """
    m = _get(store, mission_id)
    if stop_engaged:
        return ReconnectDecision(False, "STOP is engaged")
    if device_status != DeviceStatus.ACTIVE:
        return ReconnectDecision(False, f"device is {device_status}")
    if principal.lease_expired:
        return ReconnectDecision(False, "device lease expired; re-authenticate")
    if principal.device_id != m.device_id:
        return ReconnectDecision(False, "mission belongs to another device")
    if m.status in TERMINAL:
        return ReconnectDecision(False, f"mission is {m.status}")
    if m.lease_expires_at is None or _now() >= m.lease_expires_at:
        return ReconnectDecision(False, "mission lease expired; re-claim it rather than resuming")
    pending = [a for a in m.approvals if a["state"] == "PENDING"]
    if pending:
        return ReconnectDecision(False, "an approval was pending at disconnect; it must be re-requested",
                                 requires_reapproval=True)
    return ReconnectDecision(True, "device, mission, lease and policy revalidated")


def _get(store: MissionStore, mission_id: str) -> Mission:
    m = store.get(mission_id)
    if m is None:
        raise DispatchError(f"unknown mission {mission_id!r}")
    return m
