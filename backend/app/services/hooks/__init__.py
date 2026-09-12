"""KAI Hook Foundation — Phase 1 (inert).

The governed event-and-hook layer from docs/kai/plans/KAI_HOOKS_MASTER_BUILD_PLAN.md.
Phase 1 is the DECLARATIVE contract only: versioned event + hook-definition
schemas that fail closed. No event bus, no worker, no registry wiring, nothing
executes. KAI remains the sole authority; a hook definition existing here can
never mean a hook runs.

Reuses the existing `app.services.governance` authority (scope/approval/audit)
and `app.services.capability_exchange` registry rather than introducing a second
policy engine, mission state machine, or registry.
"""
from app.services.hooks.registry import Handler, HookError, HookRegistry
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
    "Handler",
    "HookDefinition",
    "HookError",
    "HookMode",
    "HookRegistry",
    "HookStatus",
    "payload_digest",
]
