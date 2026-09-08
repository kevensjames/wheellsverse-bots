"""Signed-request authentication for the KAI_DEVICE principal.

A device credential is not a bearer token. A bearer token authenticates the HOLDER of a
string, so anyone who captures it -- from a log, a proxy, a crash dump -- becomes the
device. Here the device signs each individual request, so a captured request proves only
that ONE request happened and cannot be turned into another.

The signature covers a canonical string binding, in order:

    v1 | METHOD | canonical-path | sha256(body) | timestamp | nonce | device_id

Every element is there because leaving it out permits a specific attack:

  * METHOD          without it, a captured GET replays as a DELETE on the same path.
  * canonical path  without it, a signature for /devices/x/revoke works on /devices/y/revoke.
  * body digest     without it, the body can be swapped while the signature still verifies.
  * timestamp       bounds how long a captured request stays usable at all.
  * nonce           makes it single-use inside that window.
  * device_id       stops one enrolled device presenting another's signature.

The nonce is burned in the database, so replay protection survives a restart and holds
across concurrent workers rather than living in one process's memory.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SIGNATURE_VERSION = "v1"

#: How far a request timestamp may be from server time. Small enough that a captured
#: request expires quickly; large enough to tolerate ordinary clock skew on a laptop
#: that has been asleep. The nonce, not this window, is what prevents replay -- the
#: window bounds how long the nonce table must remember.
MAX_CLOCK_SKEW = timedelta(seconds=120)

HDR_DEVICE = "X-KAI-Device-Id"
HDR_TIMESTAMP = "X-KAI-Timestamp"
HDR_NONCE = "X-KAI-Nonce"
HDR_SIGNATURE = "X-KAI-Signature"


class DeviceAuthError(Exception):
    """Authentication failure. The message is safe to log; it never contains a signature."""


@dataclass(frozen=True)
class SignedRequest:
    device_id: str
    timestamp: datetime
    nonce: str
    signature: bytes
    method: str
    path: str
    body: bytes

    def canonical_string(self) -> str:
        return canonical_string(self.method, self.path, self.body,
                                self.timestamp, self.nonce, self.device_id)


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def canonical_path(path: str) -> str:
    """Normalise the path so equivalent spellings produce the same signature input.

    A trailing slash and a doubled separator are the same resource to a router but
    different strings to a signer, and that mismatch would either break honest clients or
    -- worse -- be "fixed" by signing something looser than what is routed.
    """
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def canonical_string(method: str, path: str, body: bytes, timestamp: datetime,
                     nonce: str, device_id: str) -> str:
    return "|".join((
        SIGNATURE_VERSION,
        method.upper(),
        canonical_path(path),
        body_digest(body),
        str(int(timestamp.timestamp())),
        nonce,
        device_id,
    ))


def parse_headers(headers: dict) -> tuple[str, datetime, str, bytes]:
    """Extract and shape-check the signature headers before any crypto runs."""
    lower = {k.lower(): v for k, v in headers.items()}

    device_id = lower.get(HDR_DEVICE.lower(), "")
    if not device_id:
        raise DeviceAuthError(f"missing {HDR_DEVICE}")

    raw_ts = lower.get(HDR_TIMESTAMP.lower(), "")
    try:
        timestamp = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise DeviceAuthError(f"invalid {HDR_TIMESTAMP}") from exc

    nonce = lower.get(HDR_NONCE.lower(), "")
    if len(nonce) < 16:
        # A short nonce is guessable, which would let an attacker pre-burn the value a
        # device is about to use and deny it service.
        raise DeviceAuthError(f"{HDR_NONCE} must be at least 16 characters")

    try:
        signature = base64.b64decode(lower.get(HDR_SIGNATURE.lower(), ""), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise DeviceAuthError(f"invalid {HDR_SIGNATURE} encoding") from exc
    if len(signature) != 64:
        raise DeviceAuthError("signature is not a 64-byte Ed25519 signature")

    return device_id, timestamp, nonce, signature


def verify_signature(public_key: bytes, signed: SignedRequest, *,
                     now: datetime | None = None,
                     max_skew: timedelta = MAX_CLOCK_SKEW) -> None:
    """Verify freshness then the signature. Raises DeviceAuthError; never returns False.

    Freshness is checked first because it is cheap and because a stale request should
    not consume a signature verification.
    """
    now = now or datetime.now(timezone.utc)
    age = abs((now - signed.timestamp).total_seconds())
    if age > max_skew.total_seconds():
        raise DeviceAuthError(
            f"request timestamp is {age:.0f}s from server time (max {max_skew.total_seconds():.0f}s)")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signed.signature, signed.canonical_string().encode())
    except (InvalidSignature, ValueError) as exc:
        raise DeviceAuthError("signature verification failed") from exc


def sign_request(private_key, *, method: str, path: str, body: bytes,
                 timestamp: datetime, nonce: str, device_id: str) -> str:
    """Client-side helper, used by the connector and by tests.

    It lives beside the verifier deliberately: a signer and verifier that drift apart in
    separate files is a classic source of "works in tests, fails in production", and the
    canonical string must have exactly one definition.
    """
    payload = canonical_string(method, path, body, timestamp, nonce, device_id)
    return base64.b64encode(private_key.sign(payload.encode())).decode()
