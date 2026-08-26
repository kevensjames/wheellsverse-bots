"""KAI Capability Fabric — the capability adapter boundary (§21/§22).

KAI does NOT fork every repository. Each external capability sits behind ONE adapter that
speaks a transport (MCP / HTTP / subprocess / library / CLI / agent-skill / files / event
stream). The adapter's ``invoke`` returns a NormalizedResult — UNTRUSTED data (§24) — and it
NEVER calls another capability directly: all cross-capability orchestration goes back through
the Capability Brain (§22), which keeps KAI the authority and prevents an uncontrolled mesh.

Because nothing external is installed in this environment, the concrete adapter shipped here
is ``ExternalBlockedAdapter`` — it reports OFFLINE honestly and its invoke returns a Failure,
never a fabricated success. Real per-transport adapters plug in later behind this same ABC.
Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from .results import NormalizedResult, ResultKind, Provenance, normalize


class Transport(str, Enum):
    MCP = "MCP"
    HTTP = "HTTP"
    SUBPROCESS = "SUBPROCESS"
    LIBRARY = "LIBRARY"
    CLI = "CLI"
    AGENT_SKILL = "AGENT_SKILL"
    FILES = "FILES"
    EVENT_STREAM = "EVENT_STREAM"


class CapabilityAdapter(ABC):
    """One capability behind one transport. Concrete adapters implement these six methods."""

    def __init__(self, cap_id: str, transport: Transport) -> None:
        self.id = cap_id
        self.transport = transport

    @abstractmethod
    def discover(self) -> list[str]:
        """The concrete sub-capabilities/tools the transport actually exposes (verified, not assumed)."""

    @abstractmethod
    def health(self) -> dict:
        """{'state': 'READY'|'OFFLINE'|'DEGRADED'|'UNKNOWN', 'reason': str}."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def invoke(self, request: dict) -> NormalizedResult:
        """Run one request and return a NormalizedResult (always UNTRUSTED data)."""

    @abstractmethod
    def cancel(self, invocation_id: str) -> None: ...


class ExternalBlockedAdapter(CapabilityAdapter):
    """The honest default for a capability that is verified but NOT installed/reachable here.

    Reports OFFLINE and returns a Failure on invoke — it never fabricates a result (§73/§74).
    Every uninstalled capability uses this until a real adapter is built and certified.
    """

    def __init__(self, cap_id: str, reason: str = "not installed in this environment",
                 transport: Transport = Transport.MCP) -> None:
        super().__init__(cap_id, transport)
        self.reason = reason

    def discover(self) -> list[str]:
        return []

    def health(self) -> dict:
        return {"state": "OFFLINE", "reason": f"EXTERNAL_BLOCKED: {self.reason}"}

    def start(self) -> None:
        raise RuntimeError(f"{self.id}: cannot start — EXTERNAL_BLOCKED ({self.reason})")

    def stop(self) -> None:
        return None

    def invoke(self, request: dict) -> NormalizedResult:
        return normalize(
            self.id, ResultKind.FAILURE,
            summary=f"{self.id} is EXTERNAL_BLOCKED: {self.reason}",
            provenance=Provenance.UNAVAILABLE,
            data={"request": request},
        )

    def cancel(self, invocation_id: str) -> None:
        return None
