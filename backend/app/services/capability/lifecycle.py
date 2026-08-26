"""KAI Capability Fabric — plugin lifecycle manager (§19/§20/§51/§52).

Explicit state machine per capability. Two hard rules encoded here:
  - No capability reports READY until its health check actually succeeds (§20/§51) — a
    STARTING capability whose health fails goes to FAILED, never to a fake READY.
  - Nothing runs forever: deactivate() maps every §19 trigger (task done, timeout, mission
    cancelled, context change, permission revoked, dependency failed, unhealthy, resource
    pressure, security block) to a real STOPPING→OFFLINE transition. Heavy runtimes
    (model servers, coding workers) must be torn down, not left resident.

Transitions are validated against an explicit allow-list; an illegal transition raises
rather than silently corrupting state. Pure stdlib; time is injected for testability.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable


class State(str, Enum):
    DISCOVERED = "DISCOVERED"
    DISABLED = "DISABLED"
    STARTING = "STARTING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    OFFLINE = "OFFLINE"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


# explicit allowed transitions (§20 "Transitions must be explicit")
_ALLOWED: dict[State, set[State]] = {
    State.DISCOVERED: {State.STARTING, State.DISABLED, State.QUARANTINED},
    State.DISABLED: {State.STARTING, State.DISCOVERED},
    State.STARTING: {State.READY, State.FAILED, State.STOPPING},
    State.READY: {State.ACTIVE, State.IDLE, State.DEGRADED, State.STOPPING},
    State.ACTIVE: {State.IDLE, State.READY, State.DEGRADED, State.STOPPING},
    State.IDLE: {State.ACTIVE, State.DEGRADED, State.STOPPING},
    State.DEGRADED: {State.READY, State.STOPPING, State.FAILED, State.QUARANTINED},
    State.STOPPING: {State.OFFLINE},
    State.OFFLINE: {State.STARTING, State.DISCOVERED},
    State.FAILED: {State.STOPPING, State.QUARANTINED, State.DISCOVERED},
    State.QUARANTINED: {State.DISCOVERED},   # only via an explicit clear
}

# §19 deactivation triggers → all end in a stop
DEACTIVATION_TRIGGERS = {
    "task_complete", "timeout", "mission_cancelled", "context_changed",
    "permission_revoked", "dependency_failed", "unhealthy", "resource_pressure",
    "security_block",
}


class PluginLifecycle:
    def __init__(self, cap_id: str, now: Callable[[], float]) -> None:
        self.cap_id = cap_id
        self.state = State.DISCOVERED
        self._now = now
        self.reason = ""
        self.last_change = now()
        self.health: dict = {}
        self.history: list[tuple[State, str]] = [(State.DISCOVERED, "registered")]

    def _to(self, new: State, reason: str) -> None:
        if new not in _ALLOWED.get(self.state, set()):
            raise ValueError(f"{self.cap_id}: illegal transition {self.state.value} → {new.value}")
        self.state = new
        self.reason = reason
        self.last_change = self._now()
        self.history.append((new, reason))


class PluginLifecycleManager:
    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now or (lambda: 0.0)
        self._lc: dict[str, PluginLifecycle] = {}

    def track(self, cap_id: str) -> PluginLifecycle:
        lc = self._lc.get(cap_id)
        if lc is None:
            lc = self._lc[cap_id] = PluginLifecycle(cap_id, self._now)
        return lc

    def state(self, cap_id: str) -> State:
        return self.track(cap_id).state

    def start(self, cap_id: str) -> State:
        self.track(cap_id)._to(State.STARTING, "start requested")
        return State.STARTING

    def mark_ready(self, cap_id: str, health_ok: bool, health: dict | None = None) -> State:
        """Only a PASSING health check yields READY; a failing one yields FAILED (§20/§51)."""
        lc = self.track(cap_id)
        lc.health = dict(health or {})
        if health_ok:
            lc._to(State.READY, "health check passed")
        else:
            lc._to(State.FAILED, "health check failed")
        return lc.state

    def activate(self, cap_id: str) -> State:
        self.track(cap_id)._to(State.ACTIVE, "invoked")
        return State.ACTIVE

    def idle(self, cap_id: str) -> State:
        self.track(cap_id)._to(State.IDLE, "task complete")
        return State.IDLE

    def degrade(self, cap_id: str, reason: str = "degraded") -> State:
        self.track(cap_id)._to(State.DEGRADED, reason)
        return State.DEGRADED

    def deactivate(self, cap_id: str, trigger: str, teardown: Callable[[], None] | None = None) -> State:
        """Map a §19 trigger to a real teardown. Unknown triggers are rejected (no silent stops).

        ``teardown`` (e.g. ``adapter.stop`` / a cancel token) runs during STOPPING so deactivation
        actually releases the runtime instead of only flipping an enum — best-effort, never raises.
        """
        if trigger not in DEACTIVATION_TRIGGERS:
            raise ValueError(f"unknown deactivation trigger {trigger!r}")
        lc = self.track(cap_id)
        if lc.state in (State.OFFLINE, State.STOPPING, State.DISCOVERED, State.DISABLED):
            return lc.state
        lc._to(State.STOPPING, trigger)
        if teardown is not None:
            try:
                teardown()
            except Exception:   # noqa: BLE001 — a teardown failure must not block the stop
                pass
        lc._to(State.OFFLINE, trigger)
        return State.OFFLINE

    def fail(self, cap_id: str, reason: str = "error") -> State:
        self.track(cap_id)._to(State.FAILED, reason)
        return State.FAILED

    def quarantine(self, cap_id: str, reason: str = "policy violation") -> State:
        lc = self.track(cap_id)
        # reachable from DISCOVERED / DEGRADED / FAILED per the allow-list
        lc._to(State.QUARANTINED, reason)
        return State.QUARANTINED
