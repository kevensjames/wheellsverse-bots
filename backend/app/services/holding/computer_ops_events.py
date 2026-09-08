"""Mission event stream for the panel.

Events are DERIVED from the append-only mission history and evidence rather than stored
in a second table. That is deliberate: a separate event log would be a second source of
truth about what happened, and the two would eventually disagree -- which is precisely
the situation an audit trail exists to prevent. History is already append-only, so its
index IS a monotonic per-mission sequence number.

Consequences, stated plainly:
  * sequence numbers are per mission, not global. A client tracks a cursor per mission.
  * an event is never mutated or renumbered, because history is only ever appended to.
  * replay is bounded: a client that has been away a long time gets the most recent
    window plus a truncation marker, never an unbounded backlog that would let one
    reconnect pull a mission's entire life into memory.

The stream is a PROJECTION. It carries no authority: a client cannot complete a mission,
resolve an approval or change state by receiving or replaying an event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: Largest replay a single reconnect may request. Beyond this the client is told it
#: missed events rather than being silently handed a partial view it cannot detect.
MAX_REPLAY_EVENTS = 200

#: Largest single event payload pushed to a browser.
MAX_EVENT_BYTES = 16 * 1024


@dataclass
class MissionEvent:
    seq: int
    mission_id: str
    correlation_id: str
    server_time: str
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        """SSE frame. `id:` carries the sequence so a browser's EventSource sends
        Last-Event-ID automatically on reconnect."""
        import json
        payload = json.dumps({
            "seq": self.seq, "mission_id": self.mission_id,
            "correlation_id": self.correlation_id, "server_time": self.server_time,
            "type": self.event_type, "data": self.data,
        }, default=str)
        if len(payload) > MAX_EVENT_BYTES:
            payload = json.dumps({
                "seq": self.seq, "mission_id": self.mission_id,
                "correlation_id": self.correlation_id, "server_time": self.server_time,
                "type": self.event_type,
                "data": {"_truncated": True, "_original_bytes": len(payload)},
            })
        return f"id: {self.seq}\nevent: mission\ndata: {payload}\n\n"


#: Keys never forwarded to a browser. Evidence and history are already redacted upstream,
#: but the stream is a second place they could escape, and a redaction that exists in only
#: one path is one refactor away from not existing.
_REDACT = ("signature", "public_key", "private", "token", "secret", "api_key",
           "password", "pairing_code", "nonce")


def _redact(d: dict) -> dict:
    out = {}
    for k, v in (d or {}).items():
        if any(frag in k.lower() for frag in _REDACT):
            out[k] = "<redacted>"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        elif isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + f" …[{len(v)} chars]"
        else:
            out[k] = v
    return out


def events_for(mission, *, after_seq: int = 0,
               limit: int = MAX_REPLAY_EVENTS) -> tuple[list[MissionEvent], bool]:
    """Events after `after_seq`, plus whether the reply was truncated.

    Truncation is returned rather than silently applied so the caller can tell the client
    it missed events. A client that believes it has a complete stream when it does not is
    worse than one that knows it must re-read the mission.
    """
    corr = getattr(mission, "correlation_id", "") or ""
    out: list[MissionEvent] = []
    for idx, entry in enumerate(mission.history or [], start=1):
        if idx <= after_seq:
            continue
        data = {k: v for k, v in entry.items() if k not in ("event", "at")}
        out.append(MissionEvent(
            seq=idx, mission_id=mission.mission_id, correlation_id=corr,
            server_time=entry.get("at") or datetime.now(timezone.utc).isoformat(),
            event_type=str(entry.get("event", "unknown")), data=_redact(data)))
    truncated = len(out) > limit
    if truncated:
        # Keep the OLDEST of the window: a client replaying from a cursor needs the next
        # contiguous events, not the newest ones, or its cursor would skip a gap.
        out = out[:limit]
    return out, truncated


def latest_seq(mission) -> int:
    return len(mission.history or [])


def status_event(mission) -> MissionEvent:
    """A synthetic snapshot sent on connect so a client is never blank while waiting.

    Marked seq 0 so it can never be mistaken for a history entry or advance a cursor.
    """
    return MissionEvent(
        seq=0, mission_id=mission.mission_id,
        correlation_id=getattr(mission, "correlation_id", "") or "",
        server_time=datetime.now(timezone.utc).isoformat(),
        event_type="snapshot",
        data={"status": mission.status, "autonomy_mode": mission.autonomy_mode,
              "lease_owner": mission.lease_owner,
              "worker_claimed_success": any(e.get("claim") == "succeeded"
                                            for e in (mission.evidence or [])),
              "kai_verified_complete": mission.status == "COMPLETED",
              "latest_seq": latest_seq(mission)})
