"""KAI Capability Fabric — normalized capability manifest + taxonomy (§13/§14).

Every capability (MCP server, Agent Skill, knowledge pack, model runtime, coding
worker, memory provider, security router, geospatial tool, collaboration adapter,
native KAI tool) is described by ONE normalized manifest so the Capability Brain can
reason over a uniform shape. Pure stdlib — no external deps, no network, no runtime —
so it is testable as a plain ``python3`` script (the reasoning_sanitizer pattern).

The manifest is DATA. It never carries executable authority: a capability's declared
permissions are a *ceiling the governance layer enforces*, never a grant the capability
can widen for itself (§22/§24).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class CapabilityType(str, Enum):
    """Canonical plugin taxonomy (§13). Every integration MUST use one of these."""
    MCP = "MCP"
    AGENT_SKILL = "AGENT_SKILL"
    KNOWLEDGE_PACK = "KNOWLEDGE_PACK"
    MODEL_RUNTIME = "MODEL_RUNTIME"
    AGENT_RUNTIME = "AGENT_RUNTIME"
    WORKSPACE_ADAPTER = "WORKSPACE_ADAPTER"
    MEMORY_PROVIDER = "MEMORY_PROVIDER"
    SECURITY_ROUTER = "SECURITY_ROUTER"
    BROWSER_TOOL = "BROWSER_TOOL"
    CODE_TOOL = "CODE_TOOL"
    GEOSPATIAL_TOOL = "GEOSPATIAL_TOOL"
    COLLABORATION_TOOL = "COLLABORATION_TOOL"
    NATIVE_KAI_TOOL = "NATIVE_KAI_TOOL"
    # ── expansion-pack subtypes (§5/§17/§22) ──
    SECURITY_KNOWLEDGE_PACK = "SECURITY_KNOWLEDGE_PACK"   # PayloadsAllTheThings, reference guides
    SECURITY_DATA_PACK = "SECURITY_DATA_PACK"             # SecLists (wordlists/fuzzing data)
    OSINT_RESOURCE_PACK = "OSINT_RESOURCE_PACK"           # Awesome OSINT
    AGENT_BEHAVIOR_POLICY = "AGENT_BEHAVIOR_POLICY"       # HERO (proportional engineering)
    SECURITY_EXECUTION_FRAMEWORK = "SECURITY_EXECUTION_FRAMEWORK"   # Empire (adversary emulation)
    # ── coding agent pool (§1) ──
    CODING_WORKER = "CODING_WORKER"                       # Codex, Cline, Claude Code (general worker)
    CODING_CLI = "CODING_CLI"                             # Gemini CLI (CLI-only worker)
    CODING_IDE_ADAPTER = "CODING_IDE_ADAPTER"             # Windsurf (interactive IDE)
    CODING_CLOUD_AGENT = "CODING_CLOUD_AGENT"             # cloud-delegated coding


class RiskClass(str, Enum):
    """Plugin security class (§25). Higher classes tighten policy + approval."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    RESTRICTED = "RESTRICTED"


class ActionClass(str, Enum):
    """Per-action impact (§25). Governs approval + whether it is ever allowed."""
    READ_ONLY = "READ_ONLY"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    HIGH_IMPACT = "HIGH_IMPACT"
    FINANCIAL = "FINANCIAL"
    DESTRUCTIVE = "DESTRUCTIVE"
    PROHIBITED = "PROHIBITED"


class ActivationMode(str, Enum):
    """How the Brain is allowed to bring a capability online (§18)."""
    ALWAYS_AVAILABLE = "ALWAYS_AVAILABLE"
    ON_DEMAND = "ON_DEMAND"
    BACKGROUND = "BACKGROUND"
    MANUAL_ONLY = "MANUAL_ONLY"
    DISABLED = "DISABLED"


class Certification(str, Enum):
    """Ledger/certification state (§74). NEVER force PASS — honest state only."""
    CERTIFIED = "CERTIFIED"
    PARTIAL = "PARTIAL"
    EXPERIMENTAL = "EXPERIMENTAL"
    EXTERNAL_BLOCKED = "EXTERNAL_BLOCKED"
    REJECTED = "REJECTED"
    UPSTREAM_UNRESOLVED = "UPSTREAM_UNRESOLVED"


class Availability(str, Enum):
    """Whether the capability can be selected at all right now (§14 status)."""
    AVAILABLE = "AVAILABLE"          # installed + healthy, may be selected
    DISCOVERED = "DISCOVERED"        # known but not installed/verified
    DISABLED = "DISABLED"            # explicitly off
    QUARANTINED = "QUARANTINED"      # policy-blocked after a violation (§52)
    EXTERNAL_BLOCKED = "EXTERNAL_BLOCKED"   # cannot run in this environment (no net / no asset)


@dataclass
class ResourceProfile:
    """What a capability is expected to consume (§26). Inputs to the Resource Brain."""
    ram_mb: int = 0
    vram_mb: int = 0
    gpu: bool = False
    disk_mb: int = 0
    network: bool = False
    est_latency_ms: int = 0
    heavy: bool = False              # a long-lived runtime that must be explicitly torn down


@dataclass
class WorkerProfile:
    """Coding-worker attributes the CodingWorkerRouter reasons over (§1). Data, not authority."""
    coding_modes: list[str] = field(default_factory=list)   # implement / review / test / debug
    headless_support: bool = False       # can KAI drive it programmatically (not GUI-only)?
    workspace_support: bool = False
    git_support: bool = False
    browser_support: bool = False
    tool_support: bool = False           # supports tool/function calling
    parallel_support: bool = False       # safe to run bounded-parallel instances
    cloud_execution: bool = False
    local_execution: bool = True
    context_window: int = 0
    model_provider: str = ""             # anthropic / openai / google / github — never a credential
    approval_model: str = "governed"     # all writes/merges/deploys governed by KAI, never autonomous
    interactive_only: bool = False       # true → cannot satisfy an unattended mission (Windsurf)


@dataclass
class Provenance:
    """Supply-chain record (§53). Verified, never assumed."""
    upstream: str = ""
    owner: str = ""
    license: str = ""
    ref: str = ""                   # release tag or commit
    install_method: str = ""
    verified: bool = False
    verified_at: str = ""           # caller stamps an absolute timestamp (no clock in tests)


@dataclass
class CapabilityManifest:
    """The normalized description of one capability (§14)."""
    id: str
    name: str
    type: CapabilityType
    version: str = ""
    availability: Availability = Availability.DISCOVERED
    certification: Certification = Certification.EXPERIMENTAL
    capabilities: list[str] = field(default_factory=list)     # what it can do (verbs/nouns)
    triggers: list[str] = field(default_factory=list)         # intent keywords the Brain matches on
    dependencies: list[str] = field(default_factory=list)     # other capability ids REQUIRED
    conflicts: list[str] = field(default_factory=list)        # ids it must not run alongside
    permissions: list[str] = field(default_factory=list)      # scoped grants it may request (ceiling)
    risk_class: RiskClass = RiskClass.MEDIUM
    default_action_class: ActionClass = ActionClass.READ_ONLY
    activation: ActivationMode = ActivationMode.ON_DEMAND
    timeout_ms: int = 0
    resource_profile: ResourceProfile = field(default_factory=ResourceProfile)
    worker_profile: WorkerProfile | None = None               # set for CODING_* capabilities (§1)
    provenance: Provenance = field(default_factory=Provenance)
    fallback: str | None = None                               # capability id to fall back to (§30)
    notes: str = ""
    # ── security-tier governance (§17/§37) ──
    security_tier: int = 0                    # 0 knowledge · 1 passive data · 2 authorized test data · 3 active testing · 4 adversary emulation
    authorized_context_required: bool = False  # needs an authorized security mission before activation
    target_allowlist_required: bool = False    # needs an AuthorizedTarget (§32) — a raw hostname is never enough
    operator_approval_required: bool = False   # explicit high-impact approval (§14)
    sandbox_required: bool = False             # must run in an isolated runtime (§33)
    automatic_activation_allowed: bool = True  # false → the Brain may NEVER auto-select it (§23/§31, e.g. Empire)

    def selectable(self) -> bool:
        """A capability may be invoked at all only if it is genuinely usable now."""
        return (
            self.availability == Availability.AVAILABLE
            and self.activation != ActivationMode.DISABLED
        )

    def auto_selectable(self) -> bool:
        """A capability the Brain may AUTO-route to (natural language alone). A manual/approval or
        restricted capability (Empire) is selectable-by-explicit-invocation but never auto-selected."""
        return self.selectable() and self.automatic_activation_allowed

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # asdict already stringifies via Enum(str) subclassing; normalize enums to their values
        for k in ("type", "availability", "certification", "risk_class", "default_action_class", "activation"):
            v = getattr(self, k)
            d[k] = v.value if isinstance(v, Enum) else v
        return d


_ENUM_FIELDS = {
    "type": CapabilityType,
    "availability": Availability,
    "certification": Certification,
    "risk_class": RiskClass,
    "default_action_class": ActionClass,
    "activation": ActivationMode,
}


def manifest_from_dict(d: dict[str, Any]) -> CapabilityManifest:
    """Build a manifest from plain data (seed files / adapter discovery), coercing enums.

    Raises ValueError on a missing id/name/type or an invalid enum value — a malformed
    manifest must fail loudly, never silently register a half-capability.
    """
    if not d.get("id"):
        raise ValueError("manifest requires an id")
    if not d.get("name"):
        raise ValueError(f"manifest {d.get('id')!r} requires a name")
    kwargs: dict[str, Any] = {}
    for key, enum_cls in _ENUM_FIELDS.items():
        if key in d and d[key] is not None:
            try:
                kwargs[key] = enum_cls(d[key])
            except ValueError as exc:
                raise ValueError(f"manifest {d['id']!r}: invalid {key}={d[key]!r}") from exc
    for key in ("id", "name", "version", "capabilities", "triggers", "dependencies",
                "conflicts", "permissions", "timeout_ms", "fallback", "notes",
                "security_tier", "authorized_context_required", "target_allowlist_required",
                "operator_approval_required", "sandbox_required", "automatic_activation_allowed"):
        if key in d and d[key] is not None:
            kwargs[key] = d[key]
    if isinstance(d.get("resource_profile"), dict):
        kwargs["resource_profile"] = ResourceProfile(**d["resource_profile"])
    if isinstance(d.get("worker_profile"), dict):
        kwargs["worker_profile"] = WorkerProfile(**d["worker_profile"])
    if isinstance(d.get("provenance"), dict):
        kwargs["provenance"] = Provenance(**d["provenance"])
    return CapabilityManifest(**kwargs)
