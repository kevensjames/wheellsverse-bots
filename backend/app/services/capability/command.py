"""KAI command → capability execution bridge (§27/§28/§29).

KAI selects a capability through the CapabilityBrain, then executes it through the SAME
``CapabilityExecutionService`` the owner-only HTTP admin route uses — ONE execution implementation
(§29), no second chat brain (§28), no direct frontend→plugin path. The Brain only SELECTS; the
service enforces operation allowlist + policy + health + governance. A capability whose policy
requires explicit activation (``automatic_activation_allowed=False``, e.g. yt-dlp) is never
auto-selected here — it stays an explicit invocation (§27).
"""
from __future__ import annotations

from .execution import OPERATIONS, ExecutionResult
from .manifest import ActionClass


def default_v1_operation(cap_id: str) -> str | None:
    """The capability's V1-executable (read-only) operation, if any — server-owned, never inferred."""
    for op, spec in OPERATIONS.get(cap_id, {}).items():
        if spec.v1_eligible and spec.action_class == ActionClass.READ_ONLY:
            return op
    return None


def plan_and_execute(brain, service, utterance: str, principal, input: dict, *,
                     mission_id: str = "", timeout_ms: int | None = None) -> dict:
    """Plan with the Brain, then execute the top auto-selectable capability through the shared service.

    Returns {selected, operation, result}. If the Brain selects nothing with a V1-executable operation
    (e.g. a greeting, or an explicit-only capability), returns result=None with a note — it never
    falls through to some default execution."""
    plan = brain.plan(utterance, principal)
    for cap in plan.selected_ids():
        op = default_v1_operation(cap)
        if op:
            r: ExecutionResult = service.invoke(cap, op, input, principal,
                                                mission_id=mission_id, timeout_ms=timeout_ms)
            return {"selected": cap, "operation": op, "result": r}
    return {"selected": None, "operation": None, "result": None,
            "note": "Brain selected no capability with a V1-executable operation"}
