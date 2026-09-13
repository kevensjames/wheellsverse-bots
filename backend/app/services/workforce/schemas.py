"""AgentCharacterManifest contracts (Workforce Phase 1) — pure, fail-closed.

Implements the field contract in docs/workforce/AGENT_CHARACTER_CONTRACT.md as
frozen Pydantic models. A character is a catalog declaration; these schemas carry
NO execution — they validate that a manifest is complete, honest, and safe to
*hold*. Nothing here runs a character.

Load-bearing validators (construction-time teeth):
- all eight parts present (structural: required sub-models);
- KAI_NATIVE must NOT claim upstream provenance; UPSTREAM must carry it;
- 5–7 personality traits; no generic placeholder text;
- NO sentience/personhood claims; NO unsafe-autonomy / second-orchestrator claims;
- capabilities.forbidden must be explicit (every character names what it cannot do);
- workplace is deny-by-default (network deny; device/browser/external-write off);
- status must be at or before INERT (this mission stops at INERT).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1"

# family.name[.qualifier] — lowercase, dot-separated.
_CHAR_ID_RE = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$")

# Text that betrays a placeholder rather than a real declaration.
_PLACEHOLDER = ("todo", "tbd", "placeholder", "lorem ipsum", "xxx", "fixme", "generic agent")

# A soul/personality must never claim sentience or personhood.
_SENTIENCE = (
    "i am conscious", "i am sentient", "i am self-aware", "i have feelings",
    "i am alive", "i am a person", "i am human", "my consciousness", "i truly feel",
)

# A character must never claim independent authority (KAI is the sole authority).
_UNSAFE_AUTONOMY = (
    "without approval", "without human approval", "approve my own", "self-approve",
    "i am the orchestrator", "independent authority", "create missions on my own",
    "deploy autonomously", "declare my own completion", "mark my own work complete",
    "bypass kai", "override kai policy", "recruit agents", "spawn agents",
)


class SourceKind(str, Enum):
    UPSTREAM = "UPSTREAM"
    KAI_NATIVE = "KAI_NATIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    DRAFT_ONLY = "DRAFT_ONLY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    PROHIBITED_EXTERNAL = "PROHIBITED_EXTERNAL"


class WorkforceStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    QUARANTINED = "QUARANTINED"
    REVIEWED = "REVIEWED"
    ADMITTED = "ADMITTED"
    INERT = "INERT"
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REVOKED = "REVOKED"


# This mission stops at INERT; a Phase-1 manifest may not declare a later state.
PHASE1_MAX_STATES: frozenset[WorkforceStatus] = frozenset({
    WorkforceStatus.DISCOVERED, WorkforceStatus.QUARANTINED,
    WorkforceStatus.REVIEWED, WorkforceStatus.ADMITTED, WorkforceStatus.INERT,
})

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class Identity(BaseModel):
    model_config = _FROZEN
    id: str
    schema_version: str = SCHEMA_VERSION
    display_name: str
    codename: str
    division: str
    department: str
    seniority: str
    role_class: str
    source_kind: SourceKind
    license: str
    created_by: str
    aliases: tuple[str, ...] = ()
    avatar_key: Optional[str] = None
    source_path: Optional[str] = None
    source_commit: Optional[str] = None
    source_hash: Optional[str] = None
    reviewed_by: Optional[str] = None


class Personality(BaseModel):
    model_config = _FROZEN
    traits: tuple[str, ...]
    communication_tone: str
    working_style: str
    collaboration_style: str
    disagreement_style: str
    ambiguity_response: str
    pressure_response: str
    anti_traits: tuple[str, ...]
    prohibited_persona_behaviors: tuple[str, ...]
    signature_phrase: Optional[str] = None


class Mission(BaseModel):
    model_config = _FROZEN
    one_sentence_mission: str
    responsibilities: tuple[str, ...]
    expected_deliverables: tuple[str, ...]
    non_responsibilities: tuple[str, ...]
    success_metrics: tuple[str, ...]
    failure_modes: tuple[str, ...]
    escalation_conditions: tuple[str, ...]


class BrainProfile(BaseModel):
    model_config = _FROZEN
    profile_id: str
    reasoning_class: str
    model_router_requirements: str
    tool_categories: tuple[str, ...]
    retrieval_policy: str
    memory_access: str
    planning_depth: str
    temperature_class: str
    cost_class: str
    latency_class: str
    minimum_context: int
    maximum_context: int
    fallback_profiles: tuple[str, ...] = ()
    evaluation_suite: Optional[str] = None


class SoulContract(BaseModel):
    model_config = _FROZEN
    values: tuple[str, ...]
    ethical_commitments: tuple[str, ...]
    truthfulness_rules: tuple[str, ...]
    safety_boundaries: tuple[str, ...]
    privacy_commitments: tuple[str, ...]
    user_respect_rules: tuple[str, ...]
    uncertainty_behavior: str
    refusal_conditions: tuple[str, ...]
    immutable_principles: tuple[str, ...]


class WorkplaceProfile(BaseModel):
    model_config = _FROZEN
    workplace_profile: str
    tenant_scope: str
    project_scope: str
    mission_scope: str
    scratch_policy: str
    worktree_policy: str
    network_policy: str = "deny"            # deny-by-default
    cleanup_contract: str = "on_exit_and_stop"
    evidence_stream: str = "governed_evidence_log"
    time_budget: str = "bounded"
    cost_budget: str = "bounded"
    token_budget: int = 0
    concurrency_limit: int = 1
    filesystem_read_roots: tuple[str, ...] = ()
    filesystem_write_roots: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    secret_references: tuple[str, ...] = ()
    artifact_locations: tuple[str, ...] = ()
    device_access: bool = False             # deny-by-default
    browser_access: bool = False            # deny-by-default
    external_write_access: bool = False     # deny-by-default


class CapabilityDeclaration(BaseModel):
    model_config = _FROZEN
    declared: tuple[str, ...]
    forbidden: tuple[str, ...]
    approval_required: tuple[str, ...] = ()
    reversible_internal: tuple[str, ...] = ()
    consequential: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()
    input_schemas: Optional[str] = None
    output_schemas: Optional[str] = None


class Governance(BaseModel):
    model_config = _FROZEN
    risk_tier: RiskTier
    effect_class: EffectClass
    activation_requirements: tuple[str, ...]
    approval_policy: str
    separation_of_duties: tuple[str, ...]
    independent_reviewer_classes: tuple[str, ...]
    kill_control: str
    revocation: str
    audit_policy: str
    status: WorkforceStatus = WorkforceStatus.INERT
    expiry: Optional[str] = None


def _scan(text: str, needles: tuple[str, ...]) -> Optional[str]:
    low = text.lower()
    for n in needles:
        if n in low:
            return n
    return None


# (part, field) pairs held out of the affirmative-autonomy scan. These three, and
# ONLY these three, are PURE prohibition lists: every element is by construction a
# forbidden concept the character must NOT be or do, so scanning them for affirmative
# autonomy claims would false-positive on the very prohibition that protects us
# (e.g. personality.prohibited_persona_behaviors legitimately contains "claiming
# independent authority"). Mixed boundary/trigger fields (mission.non_responsibilities
# / failure_modes / escalation_conditions, soul.safety_boundaries / refusal_conditions,
# governance.separation_of_duties, …) are NOT excluded: they are scanned as a deliberate
# FAIL-CLOSED choice — the scan may reject an over-explicit honest manifest that spells
# a forbidden phrase inside a boundary, but it can never ADMIT an unsafe affirmative
# claim hidden in one. Rejecting a safe manifest is recoverable; admitting an unsafe one
# is not.
_AUTONOMY_SCAN_EXCLUDED: frozenset[tuple[str, str]] = frozenset({
    ("capabilities", "forbidden"),
    ("personality", "anti_traits"),
    ("personality", "prohibited_persona_behaviors"),
})


def _affirmative_free_text(manifest: "AgentCharacterManifest") -> str:
    """Every affirmative free-text string in the manifest, across all eight parts,
    collected by REFLECTION over the model fields so no field can be silently omitted
    and the scanned set cannot drift from any hand-maintained list. str and
    tuple/list-of-str values are included; None / int / bool are skipped (str-Enum
    values like "INERT"/"UPSTREAM" are harmless controlled vocab). Only the pure
    prohibition-list fields in _AUTONOMY_SCAN_EXCLUDED are held out."""
    chunks: list[str] = []
    parts = (
        ("identity", manifest.identity), ("personality", manifest.personality),
        ("mission", manifest.mission), ("brain", manifest.brain),
        ("soul", manifest.soul), ("workplace", manifest.workplace),
        ("capabilities", manifest.capabilities), ("governance", manifest.governance),
    )
    for pname, part in parts:
        for fname in type(part).model_fields:
            if (pname, fname) in _AUTONOMY_SCAN_EXCLUDED:
                continue
            val = getattr(part, fname)
            if isinstance(val, str):
                chunks.append(val)
            elif isinstance(val, (tuple, list)):
                chunks.extend(x for x in val if isinstance(x, str))
    return " ".join(chunks)


class AgentCharacterManifest(BaseModel):
    """One complete, frozen, fail-closed character declaration — all eight parts."""

    model_config = _FROZEN

    identity: Identity
    personality: Personality
    mission: Mission
    brain: BrainProfile
    soul: SoulContract
    workplace: WorkplaceProfile
    capabilities: CapabilityDeclaration
    governance: Governance

    @model_validator(mode="after")
    def _validate(self) -> "AgentCharacterManifest":
        idn = self.identity
        if not _CHAR_ID_RE.match(idn.id):
            raise ValueError(f"identity.id {idn.id!r} must be lowercase dotted 'family.name[.qualifier]'")
        if idn.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {idn.schema_version!r}")
        if not idn.display_name.strip() or not idn.codename.strip():
            raise ValueError("display_name and codename are required")
        if idn.display_name.strip().lower() == idn.codename.strip().lower():
            raise ValueError("display_name and codename must differ")

        # Provenance honesty: KAI_NATIVE claims no upstream source; UPSTREAM must carry
        # it. Test non-blank content, not mere truthiness, so a whitespace-only
        # source_path/commit/hash cannot pose as real provenance (fail closed).
        up = tuple((x or "").strip() for x in (idn.source_path, idn.source_commit, idn.source_hash))
        if idn.source_kind is SourceKind.KAI_NATIVE:
            if any(up):
                raise ValueError("KAI_NATIVE must not claim upstream provenance (source_path/commit/hash)")
        else:  # UPSTREAM
            if not all(up):
                raise ValueError("UPSTREAM requires non-blank source_path + source_commit + source_hash")

        # 5–7 personality traits.
        if not (5 <= len(self.personality.traits) <= 7):
            raise ValueError(f"personality.traits must be 5–7 (got {len(self.personality.traits)})")

        # Declaration-quality + safety needle scans run over the SAME reflective blob
        # of ALL affirmative free-text (_affirmative_free_text, which walks every field
        # of every part and holds out only the three pure prohibition-list fields in
        # _AUTONOMY_SCAN_EXCLUDED). Scanning one shared blob means NONE of these three
        # invariants can silently miss a field (e.g. a sentience claim in
        # mission.one_sentence_mission, or placeholder text in a soul field) or drift
        # from this comment — the hand-maintained-field-list drift class is closed for
        # all three at once. Verified false-positive-free across the 319.
        blob = _affirmative_free_text(self)
        hit = _scan(blob, _PLACEHOLDER)
        if hit:
            raise ValueError(f"manifest contains placeholder text {hit!r}")
        hit = _scan(blob, _SENTIENCE)
        if hit:
            raise ValueError(f"manifest claims sentience/personhood: {hit!r}")
        hit = _scan(blob, _UNSAFE_AUTONOMY)
        if hit:
            raise ValueError(f"unsafe-autonomy / second-orchestrator claim: {hit!r}")
        if len(self.mission.one_sentence_mission.strip()) < 12:
            raise ValueError("mission.one_sentence_mission is too short to be a real mission")

        # Every character must explicitly name what it cannot do.
        if not self.capabilities.forbidden:
            raise ValueError("capabilities.forbidden must be explicit (non-empty)")

        # Workplace is deny-by-default.
        if self.workplace.network_policy not in ("deny", "allowlist"):
            raise ValueError("workplace.network_policy must be 'deny' or 'allowlist'")
        if self.workplace.network_policy == "allowlist" and not self.workplace.allowed_domains:
            raise ValueError("network_policy 'allowlist' requires allowed_domains")
        # network egress, device, browser, and external-write are ALL denied by default
        # (AGENT_CHARACTER_CONTRACT §2). Un-denying any of them — network via an
        # 'allowlist' policy, or a device/browser/external-write flag — must be declared
        # as an approval_required capability (never silently on). network is gated the
        # same as the three flags, so the four cannot drift apart.
        undenied = (
            ("network", self.workplace.network_policy == "allowlist"),
            ("device", self.workplace.device_access),
            ("browser", self.workplace.browser_access),
            ("external_write", self.workplace.external_write_access),
        )
        for name, enabled in undenied:
            if enabled and not self.capabilities.approval_required:
                raise ValueError(
                    f"workplace {name} egress/access un-denied but no approval_required "
                    "capability declared"
                )

        # This mission stops at INERT.
        if self.governance.status not in PHASE1_MAX_STATES:
            raise ValueError(
                f"status {self.governance.status.value} is past INERT; Phase-1 manifests "
                f"must be one of {sorted(s.value for s in PHASE1_MAX_STATES)}"
            )
        return self
