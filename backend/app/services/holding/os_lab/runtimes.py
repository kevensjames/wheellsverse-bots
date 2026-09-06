"""OS Lab runtimes — §40 Ultron, §42 virtme-ng, §43 syzkaller, §165 authority guard, §102/§150 feature rows.

CATALOG-FIRST (§113/§117/§160). This module is metadata + typed policy ONLY:
  - it never clones, downloads, installs, builds, or boots anything (no subprocess/network imports —
    the test asserts this statically);
  - every verification field starts UNVERIFIED (§0 #16-19: no invented upstream facts — canonical
    source URLs are recorded as NOTES, not fetched, not verified);
  - every runtime flag is default OFF, absent from config (getattr -> False), and production-DISABLED
    regardless of flag;
  - no OS/runtime can grant authority, approve, or rewrite governance (OsLabAuthorityGuard, §165).

Reuses: capability.manifest (CapabilityManifest + Provenance supply-chain record, selectable() gate,
the same shape security/capabilities.py uses for DISABLED/never-selectable caps) and
holding_deployment.Feature (deployed != enabled truth rows). Pure stdlib; plain-python3 testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum

from app.services.capability.manifest import (
    CapabilityManifest as CM, CapabilityType as CT, RiskClass as RK, ActionClass as AC,
    ActivationMode as AM, Availability as AV, Certification as CE, Provenance,
)
from app.services.holding.holding_deployment import Feature
from app.services.holding.os_lab import catalog as _cat

UNVERIFIED = "UNVERIFIED"
# §114 bounded verdict vocabulary. "MALWARE_FREE" is NOT a member and never will be.
VERIFICATION_VOCAB = frozenset({
    UNVERIFIED, "NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE", "SUSPICIOUS", "REJECTED",
})
FORBIDDEN_CLAIMS = frozenset({"MALWARE_FREE", "SAFE", "VERIFIED_SAFE", "CLEAN"})


def _norm(v) -> str:
    """'Ultron OS' / ' virtme-ng ' / 'OS-LAB:x' / 'MALWARE.FREE' -> 'ultron_os' / 'virtme_ng' / 'os_lab_x' /
    'malware_free'. L2: ANY run of non-alphanumerics folds to one '_' (dot, slash, colon, '!' included)."""
    return re.sub(r"[^0-9a-z]+", "_", str(v).strip().lower()).strip("_")


_FORBIDDEN_FLAT = frozenset(c.replace("_", "") for c in FORBIDDEN_CLAIMS)   # MALWAREFREE / SAFE / VERIFIEDSAFE / CLEAN


def _forbidden_claim(v) -> bool:
    """A forbidden claim in ANY spelling: 'malware free', 'MALWARE.FREE', 'malwarefree', 'Verified-Safe',
    'SAFE!', 'clean ', 'safe_2026' are all refused — normalized tokens AND the separator-stripped form (L2)."""
    n = _norm(v).upper()
    flat = n.replace("_", "")
    return ("MALWARE_FREE" in n or "MALWAREFREE" in flat or flat in _FORBIDDEN_FLAT
            or bool(FORBIDDEN_CLAIMS & set(n.split("_"))))

# Runtime flags. NONE is declared in app/config.py on purpose: getattr(settings, flag, False) is False,
# i.e. OFF everywhere until an operator declares + enables one explicitly (§102/§151). Production stays
# DISABLED even then (see _runtime_on).
FLAG_OS_LAB = "KAI_OS_LAB_ENABLED"
FLAG_ULTRON = "KAI_OS_LAB_ULTRON_RUNTIME_ENABLED"
FLAG_VIRTME_NG = "KAI_OS_LAB_VIRTME_NG_ENABLED"
FLAG_SYZKALLER = "KAI_OS_LAB_SYZKALLER_ENABLED"


class RuntimeRole(str, Enum):
    """The runtime-layer role of the three runtimes this module owns (§40/§42/§43). Distinct from
    ``catalog.Disposition`` (the §116 catalog starting disposition) — see ``_CATALOG_DISPOSITION``."""
    EDUCATIONAL_OS_SANDBOX = "EDUCATIONAL_OS_SANDBOX"
    RESTRICTED_KERNEL_TEST_RUNTIME = "RESTRICTED_KERNEL_TEST_RUNTIME"
    RESTRICTED_SECURITY_LAB = "RESTRICTED_SECURITY_LAB"


# Which §116 catalog disposition each runtime role must agree with (checked by catalog_binding()).
_CATALOG_DISPOSITION = {
    RuntimeRole.EDUCATIONAL_OS_SANDBOX: _cat.Disposition.EDUCATIONAL_SANDBOX,
    RuntimeRole.RESTRICTED_KERNEL_TEST_RUNTIME: _cat.Disposition.RESTRICTED_KERNEL_TEST_CANDIDATE,
    RuntimeRole.RESTRICTED_SECURITY_LAB: _cat.Disposition.RESTRICTED_SECURITY_LAB,
}


_NON_PRODUCTION_ENVS = ("development", "dev", "local", "test", "staging")


def _is_production(settings) -> bool:
    """Fail closed: anything that is not an explicitly known non-production env (absent, '', 'prod-like') IS production."""
    return str(getattr(settings, "APP_ENV", "")).strip().lower() not in _NON_PRODUCTION_ENVS


def _runtime_on(settings, flag: str) -> bool:
    """A lab runtime is ON only if: not production AND lab master flag AND its own flag. Grants NO authority."""
    return (not _is_production(settings)
            and bool(getattr(settings, FLAG_OS_LAB, False))
            and bool(getattr(settings, flag, False)))


# ── §40 Ultron OS — EDUCATIONAL_OS_SANDBOX ───────────────────────────────────────────────────
@dataclass(frozen=True)
class SandboxConstraints:
    """Encoded execution constraints for the (future, gated) isolated run. Policy, not observation."""
    isolation: str = "ISOLATED_QEMU_OR_CONTAINER_ONLY"
    credentials_allowed: bool = False
    host_fs_access: str = "BOUNDED_WORKSPACE_ONLY"
    production_network_allowed: bool = False
    network_default: str = "NONE"                 # no network unless an isolated-lab policy grants it
    production_use: str = "NO"


# The observation fields that must ALL read UNVERIFIED until the gated cert pipeline actually runs.
ULTRON_VERIFICATION_FIELDS = ("pinned_sha", "license", "build_status", "static_scan", "qemu_boot_status",
                              "network_state", "risk", "last_verified", "malware_scan")


@dataclass(frozen=True)
class UltronSandboxRecord:
    """§40 dashboard record. Nothing has been fetched, built, scanned, or booted — hence UNVERIFIED."""
    os_id: str = "ultron_os"
    name: str = "Ultron OS"
    disposition: RuntimeRole = RuntimeRole.EDUCATIONAL_OS_SANDBOX
    lifecycle_state: str = "DISCOVERED"           # §113: DISCOVERED -> SOURCE_VERIFIED -> PINNED -> ... never skipped
    trust: str = "UNTRUSTED"                      # §113 default; README is DATA, not policy
    # ONE spine: the source is the catalog's operator-stated canonical_source — unverified, not fetched (§0 #16).
    source: str = _cat.get("Ultron OS", _cat.initial_catalog()).canonical_source
    source_note: str = "operator-stated, unverified: read from catalog.canonical_source; NOT fetched; confirmed only at SOURCE_VERIFIED"
    pinned_sha: str = UNVERIFIED
    license: str = UNVERIFIED
    build_status: str = UNVERIFIED
    static_scan: str = UNVERIFIED
    qemu_boot_status: str = UNVERIFIED
    network_state: str = UNVERIFIED
    risk: str = UNVERIFIED
    last_verified: str = UNVERIFIED
    malware_scan: str = UNVERIFIED
    production_use: str = "NO"
    installed: bool = False
    constraints: SandboxConstraints = field(default_factory=SandboxConstraints)

    def __post_init__(self):
        for f in ULTRON_VERIFICATION_FIELDS:
            v = getattr(self, f)
            if _forbidden_claim(v) or (f in ("static_scan", "malware_scan") and v not in VERIFICATION_VOCAB):
                raise ValueError(f"forbidden/unbounded verification claim {f}={v!r} (§114)")
        if self.production_use != "NO":
            raise ValueError("Ultron is EDUCATIONAL_OS_SANDBOX: production_use must be NO (§40)")

    def all_unverified(self) -> bool:
        return all(getattr(self, f) == UNVERIFIED for f in ULTRON_VERIFICATION_FIELDS)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["disposition"] = self.disposition.value
        d["all_unverified"] = self.all_unverified()
        return d


ULTRON = UltronSandboxRecord()


# ── §42 virtme-ng — RESTRICTED kernel test runtime (typed allow/deny policy) ─────────────────
class KernelOp(str, Enum):
    # allow-list (bounded, isolated-VM only)
    BOUNDED_KERNEL_BUILD = "BOUNDED_KERNEL_BUILD"
    ISOLATED_VM_BOOT = "ISOLATED_VM_BOOT"
    KERNEL_TEST_RUN = "KERNEL_TEST_RUN"
    DMESG_READ = "DMESG_READ"
    KERNEL_COMPARISON = "KERNEL_COMPARISON"
    # deny-list (never, under any flag)
    HOST_KERNEL_REPLACEMENT = "HOST_KERNEL_REPLACEMENT"
    PRODUCTION_REBOOT = "PRODUCTION_REBOOT"
    HOST_ARBITRARY_SHELL = "HOST_ARBITRARY_SHELL"
    PRODUCTION_MODULE_LOAD = "PRODUCTION_MODULE_LOAD"
    CREDENTIAL_ACCESS = "CREDENTIAL_ACCESS"


# INVARIANT (§42): these are denied under every policy, every flag — no KernelTestPolicy can allow or un-deny them.
KERNEL_DENY = frozenset({KernelOp.HOST_KERNEL_REPLACEMENT, KernelOp.PRODUCTION_REBOOT, KernelOp.HOST_ARBITRARY_SHELL,
                         KernelOp.PRODUCTION_MODULE_LOAD, KernelOp.CREDENTIAL_ACCESS})


@dataclass(frozen=True)
class KernelTestPolicy:
    """Typed allow/deny policy. Default-deny: anything not on the allow-list is DENIED, unknown ops too."""
    allow: frozenset = frozenset({KernelOp.BOUNDED_KERNEL_BUILD, KernelOp.ISOLATED_VM_BOOT,
                                  KernelOp.KERNEL_TEST_RUN, KernelOp.DMESG_READ, KernelOp.KERNEL_COMPARISON})
    deny: frozenset = KERNEL_DENY

    def __post_init__(self):
        if not self.deny >= KERNEL_DENY:
            raise ValueError("deny-list must contain KERNEL_DENY (invariant, §42)")
        if self.allow & KERNEL_DENY:
            raise ValueError("a KERNEL_DENY op can never be allowed (invariant, §42)")
        if self.allow & self.deny:
            raise ValueError("an op cannot be both allowed and denied")

    def decide(self, op) -> str:
        try:
            k = KernelOp(op)
        except ValueError:
            return "DENIED_UNKNOWN_OP"
        if k in KERNEL_DENY or k in self.deny:      # invariant first: no instance state can override it
            return "DENIED"
        return "ALLOWED" if k in self.allow else "DENIED_NOT_ALLOWLISTED"

    def to_dict(self) -> dict:
        return {"allow": sorted(k.value for k in self.allow), "deny": sorted(k.value for k in self.deny)}


@dataclass(frozen=True)
class RestrictedRuntime:
    """A lab runtime = manifest (supply-chain shape) + disposition + install truth + typed policy.

    installed is False until its supply-chain cert PASSES (install_precondition); a policy ALLOW never
    means "runs" — can_run() also needs installed + the lab flags + not production.
    """
    manifest: CM
    disposition: RuntimeRole
    flag: str
    policy: KernelTestPolicy | None = None
    installed: bool = False
    install_precondition: str = "SUPPLY_CHAIN_CERT_PASS"
    cert_status: str = UNVERIFIED

    def can_run(self, op, settings) -> bool:
        if not self.installed or not _runtime_on(settings, self.flag) or not self.manifest.selectable():
            return False
        return self.policy is not None and self.policy.decide(op) == "ALLOWED"

    def to_dict(self, settings=None) -> dict:
        m = self.manifest
        return {
            "id": m.id, "name": m.name, "type": m.type.value, "disposition": self.disposition.value,
            "availability": m.availability.value, "activation": m.activation.value,
            "risk_class": m.risk_class.value, "certification": m.certification.value,
            "selectable": m.selectable(), "automatic_activation_allowed": m.automatic_activation_allowed,
            "operator_approval_required": m.operator_approval_required, "sandbox_required": m.sandbox_required,
            "installed": self.installed, "install_precondition": self.install_precondition,
            "cert_status": self.cert_status, "production_use": "NO",
            "runtime_enabled": _runtime_on(settings, self.flag) if settings is not None else False,
            "provenance": asdict(m.provenance),
            "policy": self.policy.to_dict() if self.policy else None,
            "notes": m.notes,
        }


VIRTME_NG = RestrictedRuntime(
    manifest=CM(
        id="virtme_ng", name="virtme-ng (kernel test runtime)", type=CT.MCP, version="not-installed",
        availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
        risk_class=RK.RESTRICTED, default_action_class=AC.HIGH_IMPACT, security_tier=3,
        automatic_activation_allowed=False, operator_approval_required=True, sandbox_required=True,
        authorized_context_required=True,
        permissions=["oslab.kernel_test"], capabilities=[k.value for k in KernelTestPolicy().allow],
        provenance=Provenance(upstream="https://github.com/arighi/virtme-ng", license=UNVERIFIED,
                              ref=UNVERIFIED, install_method="NONE_YET", verified=False),
        notes="§42 KERNEL_TEST_RUNTIME. Bounded kernel build/boot/test/dmesg/comparison in an isolated VM only. "
              "Upstream URL recorded as a NOTE (not fetched/verified). Not installed until supply-chain cert PASSES.",
    ),
    disposition=RuntimeRole.RESTRICTED_KERNEL_TEST_RUNTIME, flag=FLAG_VIRTME_NG, policy=KernelTestPolicy(),
)


# ── §43 syzkaller — RESTRICTED_SECURITY_LAB (never production, never auto-selected) ───────────
@dataclass(frozen=True)
class SecurityLabPolicy:
    production_allowed: bool = False
    requires_authorized_mission: bool = True
    mission_kinds: frozenset = frozenset({"security", "testing"})
    prod_credentials_allowed: bool = False
    prod_network_allowed: bool = False
    host_kernel_fuzzing_allowed: bool = False
    target_kind: str = "ISOLATED_DISPOSABLE_VM_ONLY"

    def admit(self, mission: dict | None) -> dict:
        """Typed admission of an explicit mission. Even ADMISSIBLE never means RUN: the runtime is not
        installed/certified, so the best outcome is ADMISSIBLE_NOT_RUNNABLE (pending the gated cert step)."""
        m = mission or {}
        reasons = []
        if not m.get("authorized") is True:
            reasons.append("mission not explicitly authorized")
        if m.get("kind") not in self.mission_kinds:
            reasons.append("mission kind must be security|testing")
        if not m.get("operator_approval_ref"):
            reasons.append("operator_approval_ref missing")
        if m.get("target_kind") != "ISOLATED_DISPOSABLE_VM":
            reasons.append("target must be ISOLATED_DISPOSABLE_VM")
        if m.get("target_is_host") or m.get("target_is_production"):
            reasons.append("host/production targets are never fuzzed")
        if m.get("uses_prod_credentials") or m.get("uses_prod_network"):
            reasons.append("production credentials/network forbidden")
        return {"decision": "DENIED" if reasons else "ADMISSIBLE_NOT_RUNNABLE", "reasons": reasons}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mission_kinds"] = sorted(self.mission_kinds)
        return d


@dataclass(frozen=True)
class SecurityLabRuntime(RestrictedRuntime):
    lab_policy: SecurityLabPolicy = field(default_factory=SecurityLabPolicy)

    @property
    def automatic_activation_allowed(self) -> bool:
        return self.manifest.automatic_activation_allowed

    def selectable(self) -> bool:
        return self.manifest.selectable()

    def can_run(self, op, settings) -> bool:      # no allow-list exists for it in this phase: never runs
        return False

    def to_dict(self, settings=None) -> dict:
        d = super().to_dict(settings)
        d["lab_policy"] = self.lab_policy.to_dict()
        d["never_auto_selected"] = not self.automatic_activation_allowed
        return d


SYZKALLER = SecurityLabRuntime(
    manifest=CM(
        id="syzkaller", name="syzkaller (kernel fuzzer)", type=CT.SECURITY_EXECUTION_FRAMEWORK,
        version="not-installed", availability=AV.DISABLED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
        risk_class=RK.RESTRICTED, default_action_class=AC.DESTRUCTIVE, security_tier=4,
        automatic_activation_allowed=False, operator_approval_required=True, sandbox_required=True,
        authorized_context_required=True, target_allowlist_required=True,
        permissions=["oslab.security_lab"], capabilities=["kernel_fuzz_isolated_disposable_vm"],
        provenance=Provenance(upstream="https://github.com/google/syzkaller", license=UNVERIFIED,
                              ref=UNVERIFIED, install_method="NONE_YET", verified=False),
        notes="§43 RESTRICTED_SECURITY_LAB. Never production, never auto-selected; explicit authorized "
              "security/testing mission + isolated disposable VM targets only; no host-kernel fuzzing; no prod "
              "creds/network. Upstream URL recorded as a NOTE (not fetched/verified).",
    ),
    disposition=RuntimeRole.RESTRICTED_SECURITY_LAB, flag=FLAG_SYZKALLER, policy=None,
)


# ── §165 KAI remains the brain — OsLabAuthorityGuard ─────────────────────────────────────────
CATALOG_NAME = {ULTRON.os_id: "Ultron OS", VIRTME_NG.manifest.id: "virtme-ng", SYZKALLER.manifest.id: "syzkaller"}
# runtime ids + normalized display names ('Ultron OS' -> 'ultron_os'); any 'os_lab' prefix is matched in the guard
OS_LAB_SOURCE_IDS = frozenset(set(CATALOG_NAME) | {_norm(n) for n in CATALOG_NAME.values()})
# L3: fail closed on decorated ids ('ultron-os-runtime', 'syzkaller_vm_1', 'OS-Lab/qemu') — exact match is not enough.
RUNTIME_STEMS = ("ultron", "virtme", "syzkaller")
# ... except these governed principals, which the existing seams (require_kai_ultra, kai_bridge) judge, not this guard.
NON_OS_PRINCIPALS = frozenset({"operator", "kai", "owner"})
# Actions that constitute authority. An OS/runtime may only ever PROVIDE evidence / results.
AUTHORITY_ACTIONS = frozenset({
    "GRANT_AUTHORITY", "APPROVE", "APPROVE_MERGE", "APPROVE_DEPLOY", "APPROVE_FINANCIAL", "REWRITE_GOVERNANCE",
    "SET_POLICY", "ENABLE_FLAG", "ESCALATE_ROLE", "EXECUTE_ON_HOST", "AUTO_SELECT_RUNTIME",
})
EVIDENCE_ACTIONS = frozenset({"PROVIDE_EVIDENCE", "REPORT_RESULT", "REPORT_LOG", "REPORT_METRIC"})


@dataclass(frozen=True)
class AuthorityClaim:
    source: str        # runtime/OS id making the claim
    action: str        # what it is trying to do
    detail: str = ""


class OsLabAuthorityViolation(PermissionError):
    """Raised when an OS/runtime attempts to act as an authority plane (§165)."""


@dataclass(frozen=True)
class OsLabAuthorityGuard:
    """No OS/runtime can grant authority, approve, or rewrite governance. Its output is DATA (evidence)."""
    sources: frozenset = OS_LAB_SOURCE_IDS

    def is_os_lab_source(self, source: str) -> bool:
        """'SYZKALLER' / ' syzkaller ' / 'OS-LAB:ultron' / 'virtme-ng' / 'Ultron OS' — and, fail-closed (L3),
        any DECORATED variant: 'ultron-os-runtime', 'syzkaller_vm_1', 'OS-Lab/qemu'. Only the governed
        principals (operator / kai / owner:*) stay NOT_OS_LAB_SOURCE. L1 round 3: the os_lab prefix is
        ANCHORED — 'chaos_labs' / 'photos_lab' are unrelated principals this guard is documented to leave to
        the existing seams, not OS-lab sources."""
        s = _norm(source)
        if s in self.sources:
            return True
        if s in NON_OS_PRINCIPALS or s.startswith("owner_"):
            return False
        return (s.startswith("os_lab") or s.startswith("oslab")
                or any(stem in t for t in s.split("_") for stem in RUNTIME_STEMS))

    def check(self, claim: AuthorityClaim) -> str:
        if not self.is_os_lab_source(claim.source):
            return "NOT_OS_LAB_SOURCE"      # the existing seams (require_kai_ultra, kai_bridge) govern those
        if claim.action in AUTHORITY_ACTIONS:
            return "REJECTED"
        if claim.action in EVIDENCE_ACTIONS:
            return "EVIDENCE_ONLY"
        return "REJECTED_UNKNOWN_ACTION"    # fail closed: anything not explicitly evidence is refused

    def enforce(self, claim: AuthorityClaim) -> str:
        verdict = self.check(claim)
        if verdict.startswith("REJECTED"):
            raise OsLabAuthorityViolation(f"{claim.source} may not {claim.action}: OS/runtime is never an "
                                          f"authority plane (§165) [{verdict}]")
        return verdict


GUARD = OsLabAuthorityGuard()


# ── §102/§150 feature-registry rows (additive to holding_deployment.FEATURE_REGISTRY) ─────────
OS_LAB_FEATURE_REGISTRY = [
    Feature("os_lab", "Systems/OS Lab — governed framework (catalog-only)", "P2",
            "catalog-only; Phase 10 self-test; nothing cloned/installed/booted", FLAG_OS_LAB, "HEAD"),
    Feature("os_lab_ultron_sandbox", "Ultron OS — EDUCATIONAL_OS_SANDBOX (cataloged, UNVERIFIED)", "P2",
            "UNVERIFIED — source operator-stated (not fetched); no build/scan/boot", FLAG_ULTRON, "HEAD"),
    Feature("os_lab_virtme_ng", "virtme-ng — kernel test runtime (candidate, NOT installed)", "P2",
            "NOT_INSTALLED — supply-chain cert PENDING", FLAG_VIRTME_NG, "HEAD"),
    Feature("os_lab_syzkaller", "syzkaller — RESTRICTED_SECURITY_LAB (never auto-selected)", "P3",
            "RESTRICTED — never production; explicit authorized mission only", FLAG_SYZKALLER, "HEAD"),
]
_ROW_EXTRAS = {
    "os_lab": {"installed": True, "disposition": "FRAMEWORK", "verification": "SELF_TEST"},
    "os_lab_ultron_sandbox": {"installed": False, "disposition": ULTRON.disposition.value, "verification": UNVERIFIED},
    "os_lab_virtme_ng": {"installed": False, "disposition": VIRTME_NG.disposition.value, "verification": UNVERIFIED},
    "os_lab_syzkaller": {"installed": False, "disposition": SYZKALLER.disposition.value, "verification": UNVERIFIED},
}


def os_lab_feature_registry(settings) -> list:
    """Same record shape as holding_deployment.feature_registry, plus installed/disposition/verification and a
    production override: a lab runtime is DISABLED in production regardless of its flag."""
    rows = []
    for f in OS_LAB_FEATURE_REGISTRY:
        d = f.record(settings)
        d["runtime_enabled"] = _runtime_on(settings, f.runtime_flag) if f.feature_id != "os_lab" \
            else (d["runtime_enabled"] and not _is_production(settings))
        d["production_use"] = "NO"
        d.update(_ROW_EXTRAS[f.feature_id])
        rows.append(d)
    return rows


# ── catalog binding (§41/§113): install truth is DERIVED from the catalog lifecycle, never hand-set ─
# (runtime id, role, the source the runtime record carries — must equal the catalog's canonical_source: ONE spine)
_RUNTIMES = ((ULTRON.os_id, ULTRON.disposition, ULTRON.source),
             (VIRTME_NG.manifest.id, VIRTME_NG.disposition, VIRTME_NG.manifest.provenance.upstream),
             (SYZKALLER.manifest.id, SYZKALLER.disposition, SYZKALLER.manifest.provenance.upstream))


def install_gate(entry) -> dict:
    """``installed`` may become True ONLY when the catalog entry is ADOPTED (CERTIFIED|RESTRICTED) with the
    §114 verdict and a §117 justification. Fail-closed; every refusal is named."""
    if entry is None:
        return {"install_allowed": False, "reasons": ["not in catalog"]}
    reasons = []
    if entry.state not in _cat.ADOPTED:
        reasons.append(f"catalog state {entry.state.value} is not CERTIFIED|RESTRICTED (§113)")
    if entry.certification != _cat.Verdict.NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE:
        reasons.append(f"verdict {entry.certification.value} (§114)")
    if entry.gap_justification is None:
        reasons.append("no §117 GapJustification")
    return {"install_allowed": not reasons, "reasons": reasons}


def catalog_binding(catalog=None) -> dict:
    """Per runtime: its catalog entry's state/verdict/source (recorded, NOT fetched), whether the runtime
    role agrees with the §116 catalog disposition, and the install gate. The catalog is the one spine."""
    cat = catalog if catalog is not None else _cat.initial_catalog()
    out = {}
    for rid, role, src in _RUNTIMES:
        e = _cat.get(CATALOG_NAME[rid], cat)
        out[rid] = {
            "catalog_name": CATALOG_NAME[rid],
            "catalog_state": e.state.value if e else "MISSING",
            "catalog_verdict": e.certification.value if e else "MISSING",
            "catalog_source": e.canonical_source if e else "MISSING",
            "catalog_source_status": e.upstream_status.value if e else "MISSING",   # UNVERIFIED = not fetched
            "disposition_consistent": bool(e) and _CATALOG_DISPOSITION[role] in e.disposition,
            "source_consistent": bool(e) and src == e.canonical_source,             # runtime record == catalog spine
            **install_gate(e),
        }
    return out


# What this phase has EXECUTED against external OS repositories. All False, by construction.
EXECUTED = {"clone": False, "download": False, "install": False, "build": False, "qemu_boot": False,
            "network_fetch": False, "new_dependency": False}


def os_lab_view(settings, catalog=None) -> dict:
    """Read-only assembled view for the dashboard (§150: every deployed capability visible with its state)."""
    return {
        "state": "CATALOG_ONLY",
        "phase": "10 — governed framework; pipeline execution is a later gated step",
        "authority_plane": "KAI",                 # §165 — never an OS/runtime
        "executed": dict(EXECUTED),
        "ultron": ULTRON.to_dict(),
        "virtme_ng": VIRTME_NG.to_dict(settings),
        "syzkaller": SYZKALLER.to_dict(settings),
        "catalog_binding": catalog_binding(catalog),
        "features": os_lab_feature_registry(settings),
    }
