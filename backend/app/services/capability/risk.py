"""KAI Capability Fabric — risk + action policy gate (§25, §44, §22).

Decides whether a capability invocation is ALLOWED, DENIED, or needs APPROVAL. Every input
comes from KAI's own governance (the principal's role/scopes, the operator-declared authorized
targets, the approval state) — NEVER from plugin output (§24). This is the choke point that
keeps KAI the authority: a capability can propose anything, but nothing high-impact runs
without passing this gate.

Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .manifest import CapabilityManifest, RiskClass, ActionClass


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


@dataclass
class Principal:
    """Who is asking — sourced from KAI identity/RBAC, not from any capability."""
    id: str
    role: str = "operator"                       # e.g. owner | operator | viewer
    scopes: set[str] = field(default_factory=set)
    authorized_targets: set[str] = field(default_factory=set)   # systems the user may act on (§4/§35)
    approvals: set[str] = field(default_factory=set)            # capability ids pre-approved this mission


@dataclass
class PolicyResult:
    decision: Decision
    reason: str
    action_class: ActionClass
    risk_class: RiskClass


def evaluate_policy(
    manifest: CapabilityManifest,
    action_class: ActionClass,
    principal: Principal,
    *,
    target: str | None = None,
) -> PolicyResult:
    """Authorize a specific (capability, action, principal, target) tuple.

    Order matters — deny the unconditional cases first, then scope, then approval tiers.
    """
    rc = manifest.risk_class

    # 1. PROHIBITED is never allowed, by anyone, ever (§25).
    if action_class == ActionClass.PROHIBITED:
        return PolicyResult(Decision.DENY, "action is PROHIBITED", action_class, rc)

    # 2. A quarantined/unavailable capability cannot be invoked (§52).
    if not manifest.selectable():
        return PolicyResult(Decision.DENY, f"capability not selectable ({manifest.availability.value})", action_class, rc)

    # 3. Missing a required permission the capability declares → deny (least privilege).
    missing = [p for p in manifest.permissions if p not in principal.scopes]
    if missing:
        return PolicyResult(Decision.DENY, f"principal lacks scope(s): {', '.join(missing)}", action_class, rc)

    # 4. RESTRICTED capabilities (e.g. active security testing) need an AUTHORIZED target —
    #    accessibility never implies authorization (§4/§35). Read-only stays gated but softer.
    if rc == RiskClass.RESTRICTED:
        if action_class in (ActionClass.HIGH_IMPACT, ActionClass.DESTRUCTIVE, ActionClass.FINANCIAL):
            if not target or target not in principal.authorized_targets:
                return PolicyResult(Decision.DENY, "RESTRICTED active action on an unauthorized target", action_class, rc)
            return PolicyResult(Decision.REQUIRE_APPROVAL, "RESTRICTED active action requires approval", action_class, rc)
        # read-only / reversible on a restricted capability: still require approval to arm it
        return PolicyResult(Decision.REQUIRE_APPROVAL, "RESTRICTED capability requires approval to activate", action_class, rc)

    # 5. High-impact / destructive / financial actions.
    if action_class in (ActionClass.DESTRUCTIVE, ActionClass.FINANCIAL, ActionClass.HIGH_IMPACT):
        # The authorized-target gate applies EVEN to a pre-approved capability (§25) — a mission
        # pre-approval of a capability is not a blank cheque to hit an arbitrary target. Financial
        # and destructive actions require an explicit authorized target; a high-impact action may
        # be targetless but must never run against a provided-but-unauthorized target.
        if action_class in (ActionClass.DESTRUCTIVE, ActionClass.FINANCIAL):
            if not target or target not in principal.authorized_targets:
                return PolicyResult(Decision.DENY, f"{action_class.value} action on an unauthorized target", action_class, rc)
        elif target is not None and target not in principal.authorized_targets:
            return PolicyResult(Decision.DENY, "HIGH_IMPACT action on an unauthorized target", action_class, rc)
        # ponytail: approvals is keyed by cap_id (per-mission). Per-(cap,action,target) keying would
        # be finer, but the authorized-target gate above already blocks the arbitrary-target exploit.
        if manifest.id in principal.approvals:
            return PolicyResult(Decision.ALLOW, "pre-approved this mission (authorized target)", action_class, rc)
        return PolicyResult(Decision.REQUIRE_APPROVAL, f"{action_class.value} action requires approval", action_class, rc)

    # 6. Reversible writes on a HIGH-risk capability get an approval tier; on LOW/MEDIUM they pass.
    if action_class == ActionClass.REVERSIBLE_WRITE and rc == RiskClass.HIGH:
        return PolicyResult(Decision.REQUIRE_APPROVAL, "reversible write on a HIGH-risk capability requires approval", action_class, rc)

    # 7. Read-only / reversible on LOW/MEDIUM → allow.
    return PolicyResult(Decision.ALLOW, "within policy", action_class, rc)
