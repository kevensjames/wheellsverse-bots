"""KAI Capability Fabric — governed invocation + principal propagation (§17/§18/§21).

Two guarantees that keep KAI the authority at *call* time (the Brain plans; this executes):

  §17 — every invocation carries the full principal/mission/correlation context. There are no
        anonymous privileged calls, and a capability can never invent scopes: policy reads the
        InvocationContext's principal, never the request payload.
  §18 — a capability may PROPOSE another capability, but it can never invoke it directly. The
        proposal is routed back through the policy gate (route_capability_proposal); only the
        Brain/governance decides B, so A→B is never a direct grant of authority.

Every step emits a redacted audit event (§21) — never a credential, cookie, token, or private
reasoning. Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .manifest import ActionClass
from .risk import Principal, Decision, evaluate_policy, PolicyResult
from .results import NormalizedResult, ResultKind, Provenance, normalize
from .registry import CapabilityRegistry

MAX_RESULT_CHARS = 20000   # §38: an oversized capability result is clamped, not passed through whole


@dataclass
class InvocationContext:
    """The principal + mission lineage carried through every capability call (§17)."""
    principal: Principal
    mission_id: str = ""
    procedure_id: str = ""
    agent_id: str = ""
    correlation_id: str = ""

    def __post_init__(self):
        # no anonymous privileged calls — a real principal is mandatory
        if self.principal is None or not getattr(self.principal, "id", ""):
            raise ValueError("InvocationContext requires a principal with an id (no anonymous calls)")

    def audit_fields(self) -> dict:
        # role + scopes are policy metadata (safe to audit); NEVER credentials/secrets
        return {"principal": self.principal.id, "role": self.principal.role,
                "mission_id": self.mission_id, "procedure_id": self.procedure_id,
                "agent_id": self.agent_id, "correlation_id": self.correlation_id}


@dataclass
class AuditEvent:
    event: str
    capability: str
    action_class: str
    decision: str
    status: str
    context: dict = field(default_factory=dict)


def _emit(audit: Callable[[AuditEvent], None] | None, event: str, cap_id: str,
          action: ActionClass, decision: str, status: str, ctx: InvocationContext) -> None:
    if audit is None:
        return
    audit(AuditEvent(event=event, capability=cap_id, action_class=action.value,
                     decision=decision, status=status, context=ctx.audit_fields()))


def _bound(result: NormalizedResult) -> NormalizedResult:
    """Clamp an oversized result so a hostile/huge payload can't blow up context (§38)."""
    if isinstance(result.summary, str) and len(result.summary) > MAX_RESULT_CHARS:
        result.summary = result.summary[:MAX_RESULT_CHARS] + "…[truncated]"
        result.injection_flags = result.injection_flags + ["oversized_result_truncated"]
    return result


def governed_invoke(registry: CapabilityRegistry, adapter, cap_id: str, action_class: ActionClass,
                    request: dict, ctx: InvocationContext, *, target: str | None = None,
                    audit: Callable[[AuditEvent], None] | None = None) -> NormalizedResult:
    """Policy-gated invocation. A DENY never executes; a REQUIRE_APPROVAL returns an inert
    ActionProposal (governance must authorize before any run); an ALLOW runs the adapter and
    stamps the correlation id. The result is always UNTRUSTED and bounded."""
    m = registry.get(cap_id)
    pol = evaluate_policy(m, action_class, ctx.principal, target=target)

    if pol.decision == Decision.DENY:
        _emit(audit, "capability.denied", cap_id, action_class, pol.decision.value, "denied", ctx)
        return normalize(cap_id, ResultKind.FAILURE, summary=f"denied: {pol.reason}",
                         provenance=Provenance.UNAVAILABLE, correlation_id=ctx.correlation_id)

    if pol.decision == Decision.REQUIRE_APPROVAL:
        _emit(audit, "capability.denied", cap_id, action_class, pol.decision.value, "approval_required", ctx)
        # inert proposal — NOT executed; authorize_action() through governance is the only run path
        return normalize(cap_id, ResultKind.ACTION_PROPOSAL, summary=f"approval required: {pol.reason}",
                         proposed_action={"cap": cap_id, "action": action_class.value, "request": request},
                         correlation_id=ctx.correlation_id)

    _emit(audit, "capability.invoked", cap_id, action_class, pol.decision.value, "invoking", ctx)
    result = adapter.invoke(request)
    result.correlation_id = ctx.correlation_id
    result = _bound(result)
    status = "failed" if result.kind == ResultKind.FAILURE else "completed"
    _emit(audit, "capability." + ("failed" if status == "failed" else "completed"),
          cap_id, action_class, pol.decision.value, status, ctx)
    return result


def route_capability_proposal(registry: CapabilityRegistry, proposal: NormalizedResult,
                              ctx: InvocationContext, *, target: str | None = None) -> PolicyResult:
    """§18: a capability proposed another capability — the policy gate (not the proposer) decides.

    Returns the PolicyResult for the PROPOSED capability. The proposer never invokes it; the
    Brain calls governed_invoke only if this is ALLOW (or after approval). Raises if the input
    is not an ActionProposal or names an unknown/typeless capability.
    """
    if proposal.kind != ResultKind.ACTION_PROPOSAL or not proposal.proposed_action:
        raise ValueError("route_capability_proposal requires an ActionProposal with a proposed_action")
    cap_id = proposal.proposed_action.get("cap")
    if not cap_id:
        raise ValueError("proposal missing target capability id")
    try:
        action = ActionClass(proposal.proposed_action.get("action", "READ_ONLY"))
    except ValueError:
        action = ActionClass.READ_ONLY
    m = registry.get(cap_id)   # KeyError if the proposed capability is unknown
    return evaluate_policy(m, action, ctx.principal, target=target)
