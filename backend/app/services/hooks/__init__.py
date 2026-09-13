"""KAI Hook Foundation — Phase 1 (inert).

The governed event-and-hook layer from docs/kai/plans/KAI_HOOKS_MASTER_BUILD_PLAN.md.
Phase 1 is the DECLARATIVE contract only: versioned event + hook-definition
schemas that fail closed. No event bus, no worker, no registry wiring, nothing
executes. KAI remains the sole authority; a hook definition existing here can
never mean a hook runs.

By design, when a FUTURE runtime is built it will reuse the existing
`app.services.governance` authority (scope/approval/audit) and the
`app.services.capability_exchange` catalog pattern rather than spinning up a
second policy engine or mission state machine. Phase 1 itself imports neither: it
adds only the inert `HookRegistry` catalog (a read-only inventory that mirrors the
capability_exchange catalog shape — it is not a policy engine or executor).
"""
from app.services.hooks.registry import HookError, HookRegistry
from app.services.hooks.schemas import (
    SUPPORTED_SCHEMA_VERSIONS,
    DataSensitivity,
    EventEnvelope,
    HookDefinition,
    HookMode,
    HookStatus,
    payload_digest,
)

__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "DataSensitivity",
    "EventEnvelope",
    "HookDefinition",
    "HookError",
    "HookMode",
    "HookRegistry",
    "HookStatus",
    "payload_digest",
]
