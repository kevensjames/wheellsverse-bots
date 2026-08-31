"""KAI Capability Fabric — governed invocation + principal propagation (§17/§18/§21).

Two guarantees that keep KAI the authority at *call* time (the Brain plans; this executes):

  §17 — every invocation carries the full principal/mission/correlation context. There are no
        anonymous privileged calls, and a capability can never invent scopes: policy reads the
        InvocationContext's principal, never the request payload.
  §18 — a capability may PROPOSE another capability, but it can never invoke it directly. The
        proposal is routed back through the policy gate (route_capability_proposal); the action
        TIER is derived from the TRUSTED manifest (never the untrusted proposal's label), so a
        malicious plugin cannot downgrade a destructive action to READ_ONLY to escape approval.

The fabric — never the adapter — owns the trust fields of a result (§24): every adapter output
is forced UNTRUSTED + unauthorized and re-scanned, so a hostile capability can neither
self-authorize nor suppress the injection signal. Crashes are caught + redacted, timeouts are
enforced, oversized results are clamped, and a quarantined/failed capability cannot be invoked.

Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .manifest import ActionClass
from .risk import Principal, Decision, evaluate_policy, PolicyResult
from .results import NormalizedResult, ResultKind, Provenance, normalize, sanitize_external_result
from .registry import CapabilityRegistry

MAX_RESULT_CHARS = 20000   # §38: an oversized capability result is clamped, not passed through whole

# action-class severity ranking — a proposal may RAISE the tier, never LOWER it (§18)
_ACTION_RANK = {
    ActionClass.READ_ONLY: 0, ActionClass.REVERSIBLE_WRITE: 1, ActionClass.HIGH_IMPACT: 2,
    ActionClass.FINANCIAL: 3, ActionClass.DESTRUCTIVE: 3, ActionClass.PROHIBITED: 4,
}

# runtime states in which a capability must NOT be invoked (§52/§20)
_BLOCKED_STATES = {"QUARANTINED", "FAILED", "STOPPING", "OFFLINE"}


def _more_severe(a: ActionClass, b: ActionClass) -> ActionClass:
    return a if _ACTION_RANK.get(a, 4) >= _ACTION_RANK.get(b, 4) else b


def _trusted_action_class(manifest, proposed_label) -> ActionClass:
    """The action tier the policy evaluates, sourced from the TRUSTED manifest.

    The proposer (untrusted) may name an action, but it can only ESCALATE severity, never
    reduce it below the capability's declared class. A missing label uses the declared class;
    an INVALID label fails CLOSED to PROHIBITED (never the permissive READ_ONLY default).
    """
    base = manifest.default_action_class
    if proposed_label is None:
        return base
    try:
        proposed = ActionClass(proposed_label)
    except ValueError:
        return ActionClass.PROHIBITED   # unknown/forged action string → deny
    return _more_severe(base, proposed)


@dataclass
class InvocationContext:
    """The principal + mission lineage carried through every capability call (§17)."""
    principal: Principal
    mission_id: str = ""
    procedure_id: str = ""
    agent_id: str = ""
    correlation_id: str = ""

    def __post_init__(self):
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


def _emit(audit, event, cap_id, action, decision, status, ctx) -> None:
    if audit is None:
        return
    audit(AuditEvent(event=event, capability=cap_id, action_class=action.value,
                     decision=decision, status=status, context=ctx.audit_fields()))


def _clamp(text: str) -> tuple[str, bool]:
    if isinstance(text, str) and len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + "…[truncated]", True
    return text, False


def _bound(result: NormalizedResult) -> NormalizedResult:
    """Clamp EVERY oversized field (summary/data/evidence), not just summary (§38)."""
    truncated = False
    result.summary, t = _clamp(result.summary if isinstance(result.summary, str) else str(result.summary)); truncated |= t
    if result.data is not None:
        s = result.data if isinstance(result.data, str) else repr(result.data)
        if len(s) > MAX_RESULT_CHARS:
            result.data = s[:MAX_RESULT_CHARS] + "…[truncated]"; truncated = True
    if result.evidence:
        ev = repr(result.evidence)
        if len(ev) > MAX_RESULT_CHARS:
            result.evidence = [ev[:MAX_RESULT_CHARS] + "…[truncated]"]; truncated = True
    if truncated and "oversized_result_truncated" not in result.injection_flags:
        result.injection_flags = result.injection_flags + ["oversized_result_truncated"]
    return result


def _invoke_bounded(adapter, request: dict, timeout_ms: int):
    """Run adapter.invoke under a deadline. ponytail: a hung adapter can't be force-killed in
    pure Python, so the worker is a daemon thread we abandon on expiry (best-effort) and raise
    TimeoutError — governance returns a failure + deactivates rather than blocking forever."""
    if not timeout_ms or timeout_ms <= 0:
        return adapter.invoke(request)
    box: dict = {}

    def run():
        try:
            box["r"] = adapter.invoke(request)
        except BaseException as exc:   # noqa: BLE001 — captured to re-raise on the caller thread
            box["e"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout_ms / 1000.0)
    if t.is_alive():
        raise TimeoutError(f"adapter timed out after {timeout_ms}ms")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def governed_invoke(registry: CapabilityRegistry, adapter, cap_id: str, action_class: ActionClass,
                    request: dict, ctx: InvocationContext, *, target: str | None = None,
                    lifecycle=None, audit: Callable[[AuditEvent], None] | None = None,
                    timeout_ms: int | None = None) -> NormalizedResult:
    """Policy-gated invocation. A DENY never executes; a REQUIRE_APPROVAL returns an inert
    ActionProposal; an ALLOW runs the adapter under a timeout, catches crashes (redacted), and
    RE-OWNS the result's trust (UNTRUSTED + unauthorized + re-scanned). The action tier is
    floored to the manifest's declared class so a caller can never under-classify it.

    ``timeout_ms`` is a caller-requested deadline that may only TIGHTEN the manifest ceiling,
    never exceed it (§15): the effective timeout is min(requested, manifest) when both are set."""
    m = registry.get(cap_id)
    # the manifest's declared class is the FLOOR — never evaluate below it (defense in depth §18)
    action_class = _more_severe(m.default_action_class, action_class)
    # §15: a request may only tighten the manifest's ceiling, never widen it
    ceiling = m.timeout_ms
    if timeout_ms is None:
        eff_timeout = ceiling
    elif ceiling and ceiling > 0:
        eff_timeout = min(timeout_ms, ceiling)
    else:
        eff_timeout = timeout_ms

    # a quarantined/failed/stopping/offline runtime is never invoked (§52) — lifecycle is authoritative
    if lifecycle is not None:
        state = getattr(lifecycle.state(cap_id), "value", str(lifecycle.state(cap_id)))
        if state in _BLOCKED_STATES:
            _emit(audit, "capability.denied", cap_id, action_class, "DENY", f"lifecycle:{state}", ctx)
            return normalize(cap_id, ResultKind.FAILURE, summary=f"denied: capability {state}",
                             provenance=Provenance.UNAVAILABLE, correlation_id=ctx.correlation_id)

    pol = evaluate_policy(m, action_class, ctx.principal, target=target)

    if pol.decision == Decision.DENY:
        _emit(audit, "capability.denied", cap_id, action_class, pol.decision.value, "denied", ctx)
        return normalize(cap_id, ResultKind.FAILURE, summary=f"denied: {pol.reason}",
                         provenance=Provenance.UNAVAILABLE, correlation_id=ctx.correlation_id)

    if pol.decision == Decision.REQUIRE_APPROVAL:
        _emit(audit, "capability.denied", cap_id, action_class, pol.decision.value, "approval_required", ctx)
        return normalize(cap_id, ResultKind.ACTION_PROPOSAL, summary=f"approval required: {pol.reason}",
                         proposed_action={"cap": cap_id, "action": action_class.value, "request": request},
                         correlation_id=ctx.correlation_id)

    _emit(audit, "capability.invoked", cap_id, action_class, pol.decision.value, "invoking", ctx)
    try:
        result = _invoke_bounded(adapter, request, eff_timeout)
    except TimeoutError:
        if lifecycle is not None:
            try:
                lifecycle.deactivate(cap_id, "timeout", teardown=getattr(adapter, "stop", None))
            except Exception:   # noqa: BLE001
                pass
        _emit(audit, "capability.failed", cap_id, action_class, pol.decision.value, "timeout", ctx)
        return normalize(cap_id, ResultKind.FAILURE, summary=f"timeout after {eff_timeout}ms",
                         provenance=Provenance.UNAVAILABLE, correlation_id=ctx.correlation_id)
    except BaseException as exc:   # noqa: BLE001 — a crashing adapter must fail safe
        # REDACT: never interpolate the exception message (it may carry a secret) — type only
        _emit(audit, "capability.failed", cap_id, action_class, pol.decision.value, "crashed", ctx)
        return normalize(cap_id, ResultKind.FAILURE, summary=f"adapter error: {type(exc).__name__}",
                         provenance=Provenance.UNAVAILABLE, correlation_id=ctx.correlation_id)

    # a misbehaving adapter that returns None / a non-NormalizedResult must fail safe, never crash
    # the gate (defense in depth §24 — adapter output is untrusted, including its very shape)
    if not isinstance(result, NormalizedResult):
        _emit(audit, "capability.failed", cap_id, action_class, pol.decision.value, "malformed_result", ctx)
        return normalize(cap_id, ResultKind.FAILURE, summary="adapter returned a malformed result",
                         provenance=Provenance.UNAVAILABLE, correlation_id=ctx.correlation_id)

    # the FABRIC owns trust — the adapter cannot self-authorize or hide injection (§24)
    result = sanitize_external_result(result)
    result.correlation_id = ctx.correlation_id
    result = _bound(result)
    status = "failed" if result.kind == ResultKind.FAILURE else "completed"
    _emit(audit, "capability." + status, cap_id, action_class, pol.decision.value, status, ctx)
    return result


def route_capability_proposal(registry: CapabilityRegistry, proposal: NormalizedResult,
                              ctx: InvocationContext, *, target: str | None = None) -> PolicyResult:
    """§18: a capability proposed another capability — the policy gate (not the proposer) decides.

    The action TIER comes from the TRUSTED target manifest (a proposal can only escalate, never
    downgrade), so a malicious plugin cannot label a destructive proposal READ_ONLY to skip the
    authorized-target / approval gate. Raises if not an ActionProposal or the capability is unknown.
    """
    if proposal.kind != ResultKind.ACTION_PROPOSAL or not proposal.proposed_action:
        raise ValueError("route_capability_proposal requires an ActionProposal with a proposed_action")
    cap_id = proposal.proposed_action.get("cap")
    if not cap_id:
        raise ValueError("proposal missing target capability id")
    m = registry.get(cap_id)   # KeyError if the proposed capability is unknown
    action = _trusted_action_class(m, proposal.proposed_action.get("action"))
    return evaluate_policy(m, action, ctx.principal, target=target)
