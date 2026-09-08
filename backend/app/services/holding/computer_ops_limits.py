"""Resource limits and back-pressure for KAI Computer Operations.

Every limit here exists because the alternative is unbounded. A remote worker is a
program: it can retry in a tight loop, hand back a gigabyte of "evidence", or hold a
mission open forever, and none of that requires malice -- a crash loop does it by
accident. Without ceilings the failure mode is the backend, not the worker.

The limits are enforced at BOTH boundaries deliberately:

  * HTTP  -- because the backend must survive a worker that ignores its own limits, and
             the server is the only side an attacker does not control.
  * connector -- because failing fast locally avoids sending a request that will only be
             rejected, and because the connector is where a runaway mission is actually
             stopped rather than merely refused.

Enforcing in one place only would mean either a trusting server or a chatty client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# --- byte ceilings -----------------------------------------------------------

#: Largest device request body accepted. Generous for JSON control messages, far below
#: anything that pressures memory. Enforced by reading a capped number of bytes rather
#: than trusting Content-Length, which a client controls.
MAX_REQUEST_BYTES = 256 * 1024

#: Largest single evidence payload. Evidence is a summary plus references, not a
#: transport for artefacts: large output belongs on the mission volume, which is already
#: size-capped, with a reference recorded here.
MAX_EVIDENCE_BYTES = 64 * 1024

#: Largest response the panel will be handed for one mission. Bounds both the database
#: read and the browser's parse.
MAX_RESPONSE_BYTES = 512 * 1024

#: Sanitised output kept per progress note.
MAX_NOTE_CHARS = 2000

# --- concurrency and time ----------------------------------------------------

#: Concurrent leased missions per device. One machine runs one mission at a time: the
#: jail gives each mission its own APFS volume and harness process, so concurrency here
#: multiplies real resources on the operator's Mac rather than just rows in a table.
MAX_CONCURRENT_MISSIONS_PER_DEVICE = 1

#: Concurrent leased missions across all devices, so a fleet cannot collectively saturate
#: the backend even while each device respects its own limit.
MAX_CONCURRENT_MISSIONS_GLOBAL = 4

#: Hard ceiling on a mission's wall-clock life, whatever the composer requested.
MAX_MISSION_SECONDS = 3600
DEFAULT_MISSION_SECONDS = 900

#: Requests per device per minute, across all device routes. A crash-looping connector
#: is the expected cause, so the response is 429 with Retry-After rather than a ban.
MAX_DEVICE_REQUESTS_PER_MINUTE = 120

#: Evidence entries retained per mission. Beyond this the oldest are dropped and the drop
#: is RECORDED, because silently discarding evidence would make the record dishonest.
MAX_EVIDENCE_ENTRIES = 200


class LimitExceeded(Exception):
    """Carries the HTTP status the boundary should return."""

    def __init__(self, message: str, *, status: int = 413, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class Deadline:
    started_at: datetime
    seconds: int

    @property
    def expires_at(self) -> datetime:
        return self.started_at + timedelta(seconds=self.seconds)

    def expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    def remaining(self, now: datetime | None = None) -> float:
        return max(0.0, (self.expires_at - (now or datetime.now(timezone.utc))).total_seconds())


def clamp_mission_seconds(requested: int | None) -> int:
    """A composer may ask for less than the ceiling, never more."""
    if not requested or requested <= 0:
        return DEFAULT_MISSION_SECONDS
    return min(int(requested), MAX_MISSION_SECONDS)


def assert_request_size(body: bytes) -> None:
    if len(body) > MAX_REQUEST_BYTES:
        raise LimitExceeded(
            f"request body is {len(body)} bytes; the limit is {MAX_REQUEST_BYTES}", status=413)


def assert_evidence_size(payload: bytes | str) -> None:
    n = len(payload if isinstance(payload, bytes) else payload.encode("utf-8", "replace"))
    if n > MAX_EVIDENCE_BYTES:
        raise LimitExceeded(
            f"evidence payload is {n} bytes; the limit is {MAX_EVIDENCE_BYTES}. "
            "Write large output to the mission volume and record a reference instead.",
            status=413)


def assert_capacity(*, device_active: int, global_active: int) -> None:
    """Back-pressure. 429 with Retry-After, so a well-behaved connector waits rather than
    hammering, and a badly-behaved one is still bounded by the rate limiter."""
    if device_active >= MAX_CONCURRENT_MISSIONS_PER_DEVICE:
        raise LimitExceeded(
            f"device already has {device_active} mission(s) in flight "
            f"(limit {MAX_CONCURRENT_MISSIONS_PER_DEVICE})", status=429, retry_after=10)
    if global_active >= MAX_CONCURRENT_MISSIONS_GLOBAL:
        raise LimitExceeded(
            f"{global_active} missions in flight across all devices "
            f"(limit {MAX_CONCURRENT_MISSIONS_GLOBAL})", status=429, retry_after=30)


def truncate_note(note: str) -> str:
    if len(note) <= MAX_NOTE_CHARS:
        return note
    # Marked, not silently cut: a reader must be able to tell the difference between a
    # short note and a truncated one.
    return note[:MAX_NOTE_CHARS] + f" …[truncated, {len(note)} chars]"


def trim_evidence(entries: list) -> tuple[list, int]:
    """Keep the newest entries; report how many were dropped so the caller can record it."""
    if len(entries) <= MAX_EVIDENCE_ENTRIES:
        return entries, 0
    dropped = len(entries) - MAX_EVIDENCE_ENTRIES
    return entries[-MAX_EVIDENCE_ENTRIES:], dropped


class RateLimiter:
    """Fixed-window per-device counter.

    Deliberately simple and in-process: it is a back-pressure signal, not a security
    control. The security controls are the signature, the nonce burn and the scope check,
    all of which are enforced in the database and hold across workers.
    """

    def __init__(self, per_minute: int = MAX_DEVICE_REQUESTS_PER_MINUTE):
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = {}

    def check(self, device_id: str, *, now: float) -> None:
        window = self._hits.setdefault(device_id, [])
        cutoff = now - 60.0
        window[:] = [t for t in window if t > cutoff]
        if len(window) >= self.per_minute:
            raise LimitExceeded(
                f"device exceeded {self.per_minute} requests/minute", status=429, retry_after=15)
        window.append(now)
