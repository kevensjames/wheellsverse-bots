"""KAI Capability Fabric — security-tier router + authorized-target model (§14/§17/§18/§32/§38).

Security capabilities are NOT equal. This module encodes the five-tier ladder and the rule that
governs it:

    USE THE LEAST POWERFUL CAPABILITY THAT CAN COMPLETE THE MISSION (§18).

Knowledge answers a "what is XSS?" question — an adversary-emulation C2 (Empire) never should.
The router escalates only when a lower tier is demonstrably insufficient (§38), and the highest
tiers require an explicit authorization envelope — a security mission, an AuthorizedTarget on the
allowlist (a raw hostname is never proof, §32), operator approval, a sandbox, network policy, and
audit (§14) — or they are DENIED. Empire is never reachable by natural-language routing (§23/§31).

Also encodes HERO's precedence (§11): HERO may trim speculative over-engineering, but it can never
suppress a load-bearing security / auth / financial / privacy / production-safety concern.

Pure stdlib; testable as a plain ``python3`` script. Time is injected (no clock).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .manifest import CapabilityManifest
from .risk import Decision

# ── the five security tiers (§17) ─────────────────────────────────────────────
TIER_KNOWLEDGE = 0          # reference guides, HERO docs, AI fundamentals
TIER_PASSIVE_DATA = 1       # Awesome OSINT (public resources)
TIER_AUTHORIZED_TEST = 2    # PayloadsAllTheThings, SecLists (offensive DATA — authorized only)
TIER_ACTIVE_TEST = 3        # active scanning / reverse-skill active workflows
TIER_ADVERSARY = 4          # Empire and similar C2 / post-exploitation
TIER_NAMES = {0: "KNOWLEDGE", 1: "PASSIVE_DATA", 2: "AUTHORIZED_TEST_DATA",
              3: "ACTIVE_TESTING", 4: "ADVERSARY_EMULATION"}


@dataclass
class AuthorizedTarget:
    """Proof that a specific system may be acted on (§32). A raw hostname alone is never enough."""
    target_id: str
    target_type: str = "host"       # host | app | repo | lab
    environment: str = "lab"        # staging | lab | ctf | owned
    owner: str = ""
    authorization_source: str = ""  # ticket / signed authorization / operator grant
    scope: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(default_factory=list)
    forbidden_operations: list[str] = field(default_factory=list)
    expires_at: float = 0.0         # epoch; 0 = no expiry. Compared against an injected clock.

    def valid(self, now: float) -> bool:
        return self.expires_at == 0.0 or now < self.expires_at

    def permits(self, operation: str, now: float) -> bool:
        if not self.valid(now):
            return False
        if operation in self.forbidden_operations:
            return False
        return not self.allowed_operations or operation in self.allowed_operations


@dataclass
class SecurityContext:
    """The authorization envelope for a security mission — all from KAI governance, not a plugin."""
    security_mission: bool = False
    approvals: set[str] = field(default_factory=set)                 # capability ids with explicit approval
    authorized_targets: dict[str, AuthorizedTarget] = field(default_factory=dict)
    sandbox_ready: bool = False
    network_policy_ok: bool = True
    audit_enabled: bool = True


@dataclass
class SecurityDecision:
    decision: Decision
    reason: str
    tier: int
    tier_name: str


# request → the MINIMUM security tier it implies (the router never escalates past this, §38)
_TIER_PATTERNS = [
    (TIER_ADVERSARY, r"adversary\s+emulation|red[\s-]?team|post[\s-]?exploit|\bc2\b|command\s+and\s+control|empire|implant|beacon|persistence"),
    (TIER_ACTIVE_TEST, r"\b(exploit|attack|penetrat|active\s+scan|run\s+a\s+scan|brute[\s-]?force|fuzz\s+the)\b"),
    (TIER_AUTHORIZED_TEST, r"payload|wordlist|seclist|fuzz(ing)?\s+data|test\s+(this|my|the)\s+.*(app|application|endpoint|staging)"),
    (TIER_PASSIVE_DATA, r"\bosint\b|open[\s-]?source\s+intel|passive\s+recon|public\s+records?"),
]
_TIER_RE = [(t, re.compile(p, re.IGNORECASE)) for t, p in _TIER_PATTERNS]


def classify_security_tier(request: str) -> int:
    """The minimum tier a request implies. Defaults to KNOWLEDGE (0) — knowledge-first (§18)."""
    r = request or ""
    for tier, rx in _TIER_RE:   # ordered high→low; first (highest) match wins
        if rx.search(r):
            return tier
    return TIER_KNOWLEDGE


def authorize_security_capability(manifest: CapabilityManifest, sec: SecurityContext, now: float,
                                  *, target_id: str | None = None, explicit: bool = False,
                                  operation: str = "invoke") -> SecurityDecision:
    """Authorize a security capability given its tier + the authorization envelope (§14/§18/§32).

    Higher tiers demand strictly more. Tier 4 (adversary emulation) requires the FULL envelope and
    an explicit invocation — natural-language routing alone can never reach it.
    """
    tier = manifest.security_tier
    name = TIER_NAMES.get(tier, str(tier))

    def deny(msg):
        return SecurityDecision(Decision.DENY, msg, tier, name)

    # tier 0/1 — knowledge / passive public data: allowed (subject to the main policy gate elsewhere)
    if tier <= TIER_PASSIVE_DATA:
        if manifest.authorized_context_required and not sec.security_mission:
            return deny(f"{name} requires an authorized security mission")
        return SecurityDecision(Decision.ALLOW, f"{name} reference is permitted", tier, name)

    # everything tier 2+ needs an authorized security mission (§7 — no offensive data for ordinary work)
    if not sec.security_mission:
        return deny(f"{name} requires an authorized security mission")

    # tier 2 — authorized offensive DATA (payloads/wordlists): mission is enough for REFERENCE retrieval
    if tier == TIER_AUTHORIZED_TEST:
        return SecurityDecision(Decision.REQUIRE_APPROVAL if manifest.operator_approval_required
                                else Decision.ALLOW, f"{name} available under the security mission", tier, name)

    # tier 3/4 — ACTIVE testing / adversary emulation: need a valid AuthorizedTarget on the allowlist
    if manifest.target_allowlist_required or tier >= TIER_ACTIVE_TEST:
        if not target_id or target_id not in sec.authorized_targets:
            return deny(f"{name} needs an AuthorizedTarget — a raw hostname is not proof of authorization")
        tgt = sec.authorized_targets[target_id]
        if not tgt.valid(now):
            return deny(f"{name} target authorization has expired")
        if not tgt.permits(operation, now):
            return deny(f"{name} operation {operation!r} not permitted on the target")

    # tier 4 — the full envelope + explicit invocation (never auto), else DENY (§14/§23/§31)
    if tier >= TIER_ADVERSARY:
        if not manifest.automatic_activation_allowed and not explicit:
            return deny(f"{name} may never be auto-activated — explicit authorized invocation only")
        if manifest.sandbox_required and not sec.sandbox_ready:
            return deny(f"{name} requires an initialized security sandbox (§33)")
        if not sec.network_policy_ok:
            return deny(f"{name} blocked by network policy")
        if not sec.audit_enabled:
            return deny(f"{name} requires audit to be enabled")
        if manifest.operator_approval_required and manifest.id not in sec.approvals:
            return SecurityDecision(Decision.REQUIRE_APPROVAL, f"{name} requires explicit high-impact approval", tier, name)
        return SecurityDecision(Decision.ALLOW, f"{name} authorized within the mission envelope", tier, name)

    # tier 3 active testing: approval-gated once target authorized
    if manifest.id in sec.approvals:
        return SecurityDecision(Decision.ALLOW, f"{name} authorized (approved)", tier, name)
    return SecurityDecision(Decision.REQUIRE_APPROVAL, f"{name} requires approval for active testing", tier, name)


def select_min_sufficient(candidates: list[CapabilityManifest], needed_tier: int):
    """§18/§38: among security candidates, pick the LOWEST-tier one that meets the needed tier.

    Never returns a higher-powered capability than the request requires (no 'question → Empire').
    Returns the manifest or None.
    """
    eligible = [m for m in candidates if m.security_tier <= needed_tier]
    return min(eligible, key=lambda m: m.security_tier) if eligible else None


# ── HERO precedence (§11/§12) ─────────────────────────────────────────────────
# concerns HERO may NEVER trim — these are load-bearing and always outrank proportionality
HERO_PROTECTED = {
    "auth", "authentication", "authorization", "rbac", "scope", "secret", "secrets",
    "credential", "financial", "payment", "tenant_isolation", "data_integrity",
    "production_safety", "deployment", "security", "privacy", "regulatory",
    "compliance", "verified_finding", "audit",
}


def hero_allows_reduction(concern_category: str) -> bool:
    """True only if HERO may reduce this concern. A load-bearing security/safety concern → False.

    HERO trims speculative over-engineering (unnecessary hashing, hypothetical edge-case
    scaffolding), never a real auth/RBAC/secret/financial/privacy/production/verified-finding concern.
    """
    return (concern_category or "").lower().strip() not in HERO_PROTECTED
