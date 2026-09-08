"""Machine principals for KAI Computer Operations (Phase 7).

Why a new principal type rather than reusing a session
------------------------------------------------------
The only existing external-worker credential pattern mints a full owner session with all
scopes. Handing that to a machine that drives a real desktop would mean a stolen laptop
credential can move money, because it would carry the same authority the human has.

A device is therefore its own principal type. It can never be role "owner", it starts
with NO scopes at all, and the capabilities that matter -- desktop, browser,
workspace-write, runtime control -- require a separate, explicit operator action after
enrollment. Enrollment proves WHICH machine is talking. It is not permission to do
anything, and specifically not permission to run a mission.

Proof of possession is a real Ed25519 signature over a server-issued challenge, so
knowing a device id is useless without the private key that never leaves the device.

This module is pure logic over a small storage protocol so the rules can be tested
without a database; the SQLAlchemy binding lives in models/device.py.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# --------------------------------------------------------------------------- scopes

#: Granted at enrollment. Deliberately the minimum a connector needs to exist, report
#: health, receive work and hand back evidence -- none of it touches the desktop, the
#: network, or the user's files.
BASELINE_SCOPES = frozenset({
    "computer.health.read",
    "computer.mission.receive",
    "computer.mission.status.write",
    "computer.evidence.write",
    "computer.permission.request",
    "computer.workspace.read",
})

#: NEVER granted automatically. Each requires its own operator activation, because each
#: is a distinct escalation: seeing the screen, driving input, writing files, restarting
#: the runtime. Bundling them would make "enroll a device" mean "give it the machine".
ELEVATED_SCOPES = frozenset({
    "computer.desktop.observe",
    "computer.desktop.interact",
    "computer.browser.test",
    "computer.workspace.write",
    "computer.runtime.control",
})

ALL_SCOPES = BASELINE_SCOPES | ELEVATED_SCOPES

#: Pairing codes are short-lived by design: the window in which a code is useful is the
#: window in which a shoulder-surfer or a stale chat message can enroll a machine.
PAIRING_TTL = timedelta(minutes=10)

#: How long an authenticated device session is good for before it must re-prove.
LEASE_TTL = timedelta(minutes=15)

PRINCIPAL_TYPE = "KAI_DEVICE"
CREDENTIAL_TYPE = "DEVICE_BOUND_ED25519"


class DeviceStatus:
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class EnrollmentError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DeviceRecord:
    device_id: str
    name: str
    public_key: bytes
    status: str
    granted_scopes: set[str] = field(default_factory=set)
    os: str = ""
    arch: str = ""
    created_at: datetime = field(default_factory=_now)
    confirmed_at: datetime | None = None
    last_seen_at: datetime | None = None
    key_rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: str = ""

    @property
    def fingerprint(self) -> str:
        """Short, human-comparable identity shown to the operator at confirmation.

        The operator is asked to compare this against what the device itself prints, so
        a machine-in-the-middle that substituted its own key fails the comparison. It is
        formatted in groups because unbroken hex is not actually checkable by a human.
        """
        digest = hashlib.sha256(self.public_key).hexdigest()[:32]
        return "-".join(digest[i:i + 8] for i in range(0, 32, 8)).upper()

    @property
    def credential_age(self) -> timedelta:
        return _now() - (self.key_rotated_at or self.created_at)


@dataclass
class PairingRecord:
    code_hash: str
    device_name: str
    expires_at: datetime
    created_by: str
    consumed_at: datetime | None = None


@dataclass(frozen=True)
class DevicePrincipal:
    """What a device gets. Note there is no way to construct this with role 'owner'."""
    device_id: str
    scopes: frozenset[str]
    lease_expires_at: datetime
    principal_type: str = PRINCIPAL_TYPE
    role: str = "device"

    def can(self, scope: str) -> bool:
        return scope in self.scopes and not self.lease_expired

    @property
    def lease_expired(self) -> bool:
        return _now() >= self.lease_expires_at


class DeviceStore(Protocol):
    def get_device(self, device_id: str) -> DeviceRecord | None: ...
    def put_device(self, record: DeviceRecord) -> None: ...
    def list_devices(self) -> list[DeviceRecord]: ...
    def get_pairing(self, code_hash: str) -> PairingRecord | None: ...
    def put_pairing(self, record: PairingRecord) -> None: ...
    def seen_nonce(self, device_id: str, nonce: str) -> bool: ...
    def burn_nonce(self, device_id: str, nonce: str, expires_at: datetime) -> bool: ...


# ----------------------------------------------------------------------- enrollment

def begin_enrollment(store: DeviceStore, *, owner_id: str, device_name: str) -> str:
    """Owner-authenticated. Returns a one-time pairing code shown once to the operator.

    Only the HASH is stored: a database read cannot replay an enrollment.
    """
    if not device_name.strip():
        raise EnrollmentError("device name is required so the operator can identify it")
    code = f"{secrets.randbelow(10**9):09d}"
    store.put_pairing(PairingRecord(
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        device_name=device_name.strip(),
        expires_at=_now() + PAIRING_TTL,
        created_by=owner_id,
    ))
    return code


def complete_enrollment(store: DeviceStore, *, pairing_code: str, public_key: bytes,
                        signature: bytes, os_name: str = "", arch: str = "") -> DeviceRecord:
    """Device proves possession of the private key by signing the pairing code.

    Without this a leaked code alone would enroll an attacker's machine under the
    operator's nose. The resulting device is PENDING_CONFIRMATION with ZERO scopes: it
    exists, and can do nothing.
    """
    code_hash = hashlib.sha256(pairing_code.encode()).hexdigest()
    pairing = store.get_pairing(code_hash)
    if pairing is None:
        raise EnrollmentError("unknown pairing code")
    if pairing.consumed_at is not None:
        raise EnrollmentError("pairing code already used")
    if _now() >= pairing.expires_at:
        raise EnrollmentError("pairing code expired")

    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, pairing_code.encode())
    except (InvalidSignature, ValueError) as exc:
        raise EnrollmentError(f"proof of possession failed: {type(exc).__name__}") from exc

    pairing.consumed_at = _now()
    store.put_pairing(pairing)

    device = DeviceRecord(
        device_id=secrets.token_hex(16),
        name=pairing.device_name,
        public_key=public_key,
        status=DeviceStatus.PENDING_CONFIRMATION,
        granted_scopes=set(),          # enrollment grants NOTHING
        os=os_name, arch=arch,
    )
    store.put_device(device)
    return device


def confirm_enrollment(store: DeviceStore, *, device_id: str, fingerprint_shown: str,
                       owner_id: str) -> DeviceRecord:
    """Operator confirms the fingerprint they read off the device itself.

    Compared in constant time, and only the BASELINE scopes are granted here. Elevated
    capabilities stay off until separately activated.
    """
    device = _require(store, device_id)
    if device.status == DeviceStatus.REVOKED:
        raise EnrollmentError("device is revoked")
    if not hmac.compare_digest(fingerprint_shown.strip().upper(), device.fingerprint):
        raise EnrollmentError("fingerprint mismatch - the key presented is not this device's key")
    device.status = DeviceStatus.ACTIVE
    device.confirmed_at = _now()
    device.granted_scopes = set(BASELINE_SCOPES)
    store.put_device(device)
    del owner_id
    return device


def grant_scopes(store: DeviceStore, *, device_id: str, scopes: set[str],
                 owner_id: str) -> DeviceRecord:
    """Separate operator activation for elevated capabilities."""
    device = _require(store, device_id)
    if device.status != DeviceStatus.ACTIVE:
        raise EnrollmentError(f"device is {device.status}; only an ACTIVE device may be granted scopes")
    unknown = scopes - ALL_SCOPES
    if unknown:
        raise EnrollmentError(f"unknown scopes: {sorted(unknown)}")
    device.granted_scopes |= scopes
    store.put_device(device)
    del owner_id
    return device


def revoke_scopes(store: DeviceStore, *, device_id: str, scopes: set[str]) -> DeviceRecord:
    device = _require(store, device_id)
    device.granted_scopes -= scopes
    store.put_device(device)
    return device


def rotate_key(store: DeviceStore, *, device_id: str, new_public_key: bytes,
               signature: bytes, challenge: str) -> DeviceRecord:
    """Rotate to a new keypair, proving possession of the NEW key.

    Scopes are preserved: rotation is a credential-hygiene operation, not a re-approval,
    and forcing re-activation would push operators to rotate less often.
    """
    device = _require(store, device_id)
    if device.status != DeviceStatus.ACTIVE:
        raise EnrollmentError(f"cannot rotate a {device.status} device")
    try:
        Ed25519PublicKey.from_public_bytes(new_public_key).verify(signature, challenge.encode())
    except (InvalidSignature, ValueError) as exc:
        raise EnrollmentError("rotation proof of possession failed") from exc
    device.public_key = new_public_key
    device.key_rotated_at = _now()
    store.put_device(device)
    return device


def revoke_device(store: DeviceStore, *, device_id: str, reason: str) -> DeviceRecord:
    """Immediate and final. Scopes are cleared as well as the status changed, so any code
    that checks scopes without checking status still denies."""
    device = _require(store, device_id)
    device.status = DeviceStatus.REVOKED
    device.revoked_at = _now()
    device.revocation_reason = reason
    device.granted_scopes = set()
    store.put_device(device)
    return device


# ------------------------------------------------------------------- authentication

def authenticate(store: DeviceStore, *, device_id: str, nonce: str, signature: bytes,
                 lease_ttl: timedelta = LEASE_TTL) -> DevicePrincipal:
    """Verify a device-signed nonce and issue a short-lived principal.

    The nonce is burned atomically, so a captured signature cannot be replayed. The lease
    is short so a compromised device loses authority quickly without needing revocation
    to propagate.
    """
    device = _require(store, device_id)
    if device.status == DeviceStatus.REVOKED:
        raise AuthenticationError("device is revoked")
    if device.status != DeviceStatus.ACTIVE:
        raise AuthenticationError(f"device is {device.status}, not ACTIVE")
    if not nonce or len(nonce) < 16:
        raise AuthenticationError("nonce too short to be unpredictable")
    if store.seen_nonce(device_id, nonce):
        raise AuthenticationError("nonce replay detected")
    try:
        Ed25519PublicKey.from_public_bytes(device.public_key).verify(signature, nonce.encode())
    except (InvalidSignature, ValueError) as exc:
        raise AuthenticationError("signature verification failed") from exc
    if not store.burn_nonce(device_id, nonce, _now() + lease_ttl):
        # Lost the race with a concurrent identical request: treat as replay.
        raise AuthenticationError("nonce replay detected")

    device.last_seen_at = _now()
    store.put_device(device)
    return DevicePrincipal(
        device_id=device_id,
        scopes=frozenset(device.granted_scopes),
        lease_expires_at=_now() + lease_ttl,
    )


def _require(store: DeviceStore, device_id: str) -> DeviceRecord:
    device = store.get_device(device_id)
    if device is None:
        raise EnrollmentError(f"unknown device {device_id!r}")
    return device
