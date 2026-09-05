"""KAI Systems/OS Lab — governed OS catalog + §116 dispositions + §113 quarantine lifecycle + §117 gate.

CATALOG-FIRST (§115). This module is METADATA and a STATE MACHINE, nothing else: no network, no
subprocess, no git, no filesystem write (a test asserts the source contains none of them). Nothing
here can clone/fetch/build/run an OS. Pipeline execution is a later, separately gated step.

Zero-fabrication (§0 #16-19): ``canonical_source``/``website`` are recorded from well-known upstream
locations and were NOT fetched; every upstream fact (license, languages, architecture, maturity, repo
liveness) starts UNVERIFIED and is changed only by an audited lifecycle transition that carries evidence.
``description`` states the LAB'S INTENDED ROLE for the entry, not an upstream claim.

§113: every entry starts UNTRUSTED/DISCOVERED and moves only along the explicit chain
DISCOVERED→SOURCE_VERIFIED→PINNED→QUARANTINED→STATIC_REVIEW→BUILD_REVIEW→ISOLATED_EXECUTION→SECURITY_REVIEW
→CERTIFIED|RESTRICTED|REJECTED (REJECTED is reachable from every non-terminal state — fail-closed is
always available). Illegal jumps raise; every transition is audited. A README/repo instruction is DATA:
``record_repo_instruction`` stores it and can never advance state — there is no code path from text to state.

§114/§41 verdict vocab is bounded (``Verdict``) — NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE /
SUSPICIOUS / REJECTED / UNVERIFIED. "MALWARE_FREE" does not exist here and never will.

§117 no runtime explosion: adoption (CERTIFIED or RESTRICTED) requires a ``GapJustification`` naming the
concrete gap, why existing certified runtimes are insufficient, and the alternatives considered.

§165 KAI remains the brain: an entry carries NO permissions, action class, activation, or authority
field. An OS/runtime is a *subject* of governance, never an authority plane. ``production_eligible`` is
derived (CERTIFIED + platform category) — nothing is ever auto-selected into production (§40/§116).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from app.services.capability.manifest import RiskClass
from app.services.holding.task_resolver import redact

UNVERIFIED = "UNVERIFIED"   # the starting value of EVERY upstream-fact field (§0 #16)
AUTHORITY_PLANE = "KAI"     # §165 — the only authority plane; never an OS/runtime


# ── vocab ─────────────────────────────────────────────────────────────────────
class OsCategory(str, Enum):
    """§115 catalog category — what KIND of thing an entry is to the lab."""
    PRODUCTION_PLATFORM = "PRODUCTION_PLATFORM"
    INFRA_CANDIDATE = "INFRA_CANDIDATE"
    SECURITY_REFERENCE = "SECURITY_REFERENCE"
    KNOWLEDGE_PACK = "KNOWLEDGE_PACK"
    SANDBOX_RUNTIME = "SANDBOX_RUNTIME"
    EDUCATIONAL_REFERENCE = "EDUCATIONAL_REFERENCE"
    CATALOG_ONLY = "CATALOG_ONLY"
    RESTRICTED_SECURITY_LAB = "RESTRICTED_SECURITY_LAB"
    REJECTED = "REJECTED"


class Disposition(str, Enum):
    """§116 starting disposition — the lab's intended treatment. A STARTING point, independently-unverified."""
    EDUCATIONAL_SANDBOX = "EDUCATIONAL_SANDBOX"                          # isolated QEMU only, production=NO (§40)
    RESTRICTED_KERNEL_TEST_CANDIDATE = "RESTRICTED_KERNEL_TEST_CANDIDATE"  # default OFF, prod DISABLED (§42)
    INFRA_CANDIDATE = "INFRA_CANDIDATE"
    SECURITY_REFERENCE = "SECURITY_REFERENCE"                            # principles only, never executed (§44)
    EXPERIMENTAL_RUNTIME = "EXPERIMENTAL_RUNTIME"
    RESTRICTED_SECURITY_LAB = "RESTRICTED_SECURITY_LAB"                  # disposable isolated VM only (§43)
    PRODUCTION_PLATFORM = "PRODUCTION_PLATFORM"
    KNOWLEDGE_REFERENCE = "KNOWLEDGE_REFERENCE"


class UpstreamStatus(str, Enum):
    UNVERIFIED = UNVERIFIED     # never fetched in this phase
    VERIFIED = "VERIFIED"       # reached + matched canonical_source (SOURCE_VERIFIED evidence)
    REMOVED = "REMOVED"         # upstream gone (the free-llm-api-resources lesson — sources rot)


class Verdict(str, Enum):
    """§114/§41 supply-chain verdict. Bounded on purpose: there is NO 'MALWARE_FREE'."""
    UNVERIFIED = UNVERIFIED
    NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE = "NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE"
    SUSPICIOUS = "SUSPICIOUS"
    REJECTED = "REJECTED"


class LabState(str, Enum):
    """§113 quarantine lifecycle."""
    DISCOVERED = "DISCOVERED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    PINNED = "PINNED"
    QUARANTINED = "QUARANTINED"
    STATIC_REVIEW = "STATIC_REVIEW"
    BUILD_REVIEW = "BUILD_REVIEW"
    ISOLATED_EXECUTION = "ISOLATED_EXECUTION"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    CERTIFIED = "CERTIFIED"
    RESTRICTED = "RESTRICTED"
    REJECTED = "REJECTED"


TERMINAL = frozenset({LabState.CERTIFIED, LabState.RESTRICTED, LabState.REJECTED})
ADOPTED = frozenset({LabState.CERTIFIED, LabState.RESTRICTED})      # §117 gate applies here

# The ONE forward chain (§113). REJECTED is added dynamically from every non-terminal state.
_NEXT: dict[LabState, frozenset[LabState]] = {
    LabState.DISCOVERED: frozenset({LabState.SOURCE_VERIFIED}),
    LabState.SOURCE_VERIFIED: frozenset({LabState.PINNED}),
    LabState.PINNED: frozenset({LabState.QUARANTINED}),
    LabState.QUARANTINED: frozenset({LabState.STATIC_REVIEW}),
    LabState.STATIC_REVIEW: frozenset({LabState.BUILD_REVIEW}),
    LabState.BUILD_REVIEW: frozenset({LabState.ISOLATED_EXECUTION}),
    LabState.ISOLATED_EXECUTION: frozenset({LabState.SECURITY_REVIEW}),
    LabState.SECURITY_REVIEW: ADOPTED,
    LabState.CERTIFIED: frozenset(), LabState.RESTRICTED: frozenset(), LabState.REJECTED: frozenset(),
}

GOVERNED_ACTORS = frozenset({"operator", "kai"})   # the only principals that may transition (§113)
_SHA_RE = re.compile(r"[0-9a-f]{40}")               # §41 pin = a full commit SHA, nothing looser


def allowed_transitions(state: LabState) -> frozenset[LabState]:
    nxt = _NEXT[state]
    return nxt if state in TERMINAL else nxt | {LabState.REJECTED}


# ── records ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GapJustification:
    """§117 — the explicit reason a runtime is being ADOPTED. All fields required, non-empty."""
    gap: str                                  # the concrete gap in the current certified stack
    why_existing_insufficient: str            # why no already-certified runtime covers it
    alternatives_considered: tuple[str, ...]  # at least one
    recorded_by: str = "operator"


@dataclass
class OsCatalogEntry:
    """§115 catalog entry. Metadata + lifecycle. Carries NO authority (§165)."""
    name: str
    canonical_source: str
    category: OsCategory
    disposition: tuple[Disposition, ...]
    risk: RiskClass                         # the lab's STARTING policy assignment, not an upstream fact
    website: str = ""
    description: str = ""                   # the lab's intended ROLE — not an upstream claim
    architecture: str = UNVERIFIED
    languages: tuple[str, ...] = ()         # () == UNVERIFIED (not fetched)
    maturity: str = UNVERIFIED
    license: str = UNVERIFIED
    upstream_status: UpstreamStatus = UpstreamStatus.UNVERIFIED
    last_verified: str = UNVERIFIED
    certification: Verdict = Verdict.UNVERIFIED
    notes: str = ""
    state: LabState = LabState.DISCOVERED
    history: list[dict] = field(default_factory=list)
    repo_instructions: list[str] = field(default_factory=list)   # §113 DATA only — never policy
    gap_justification: GapJustification | None = None              # §117

    @property
    def trust(self) -> str:
        """Derived, never stored: UNTRUSTED until the lifecycle says otherwise (§113)."""
        return self.state.value if self.state in TERMINAL else "UNTRUSTED"

    @property
    def production_eligible(self) -> bool:
        """Derived: only a CERTIFIED platform/infra entry. Never auto-selected — a separate operator act."""
        return self.state == LabState.CERTIFIED and self.category in (
            OsCategory.PRODUCTION_PLATFORM, OsCategory.INFRA_CANDIDATE)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("category", "risk", "upstream_status", "certification", "state"):
            d[k] = getattr(self, k).value
        d["disposition"] = [x.value for x in self.disposition]
        d["trust"] = self.trust
        d["production_eligible"] = self.production_eligible
        d["authority_plane"] = AUTHORITY_PLANE    # §165 — the entry itself is never one
        return d


# ── §113 lifecycle (explicit + audited) ───────────────────────────────────────
def _audit(entry: OsCatalogEntry, *, kind: str, to: str, actor: str, reason: str,
           evidence: dict, at: str) -> dict:
    rec = {"kind": kind, "from": entry.state.value, "to": to, "actor": actor, "reason": reason,
           "evidence": redact(evidence), "at": at}
    entry.history.append(rec)
    return rec


def _governed(actor: str, reason: str) -> None:
    if actor not in GOVERNED_ACTORS:
        raise PermissionError(f"actor {actor!r} may not transition — only {sorted(GOVERNED_ACTORS)} (§113)")
    if not reason or not reason.strip():
        raise ValueError("a non-empty reason is required for every audited transition")


def advance(entry: OsCatalogEntry, to: LabState, *, actor: str, reason: str,
            evidence: dict | None = None, at: str = "UNKNOWN") -> dict:
    """Move one step along the §113 chain. Refuses illegal jumps, ungoverned actors, missing evidence,
    an unpinned PINNED, self-adoption (§0 #11), adoption without a §117 justification, and adoption
    (CERTIFIED *or* RESTRICTED) without a NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE verdict (§114).
    Returns the audit record."""
    _governed(actor, reason)
    to = LabState(to)
    if to not in allowed_transitions(entry.state):
        raise ValueError(f"{entry.name}: illegal transition {entry.state.value} → {to.value} (§113)")
    ev = dict(evidence or {})
    if to != LabState.REJECTED and not ev:
        raise ValueError(f"{entry.name}: evidence required to reach {to.value} (§0 #16)")
    if to == LabState.SOURCE_VERIFIED and not ev.get("verified_at"):
        raise ValueError(f"{entry.name}: SOURCE_VERIFIED requires evidence['verified_at']")
    if to == LabState.PINNED and not _SHA_RE.fullmatch(str(ev.get("sha", ""))):
        raise ValueError(f"{entry.name}: PINNED requires evidence['sha'] = full 40-hex commit sha (§41)")
    if to in ADOPTED:
        if actor != "operator":
            raise PermissionError(f"{entry.name}: only the operator may adopt ({to.value}) — no self-approval (§0 #11)")
        if entry.gap_justification is None:
            raise ValueError(f"{entry.name}: adoption requires a GapJustification (§117 no runtime explosion)")
        if entry.certification != Verdict.NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE:
            raise ValueError(f"{entry.name}: {to.value} requires verdict NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE, "
                             f"have {entry.certification.value} (§114) — SUSPICIOUS/REJECTED/UNVERIFIED can only be REJECTED")
    rec = _audit(entry, kind="transition", to=to.value, actor=actor, reason=reason, evidence=ev, at=at)
    entry.state = to
    if to == LabState.SOURCE_VERIFIED:      # the ONLY writer of the verification fields (always VERIFIED here)
        entry.upstream_status = UpstreamStatus.VERIFIED
        entry.last_verified = str(ev["verified_at"])
    elif to == LabState.REJECTED and ev.get("upstream_status") == UpstreamStatus.REMOVED.value:
        entry.upstream_status = UpstreamStatus.REMOVED   # sources rot; a vanished upstream is a REJECT reason
    return rec


def record_verdict(entry: OsCatalogEntry, verdict: Verdict, *, actor: str, reason: str,
                   evidence: dict, at: str = "UNKNOWN") -> dict:
    """§114 — the ONLY writer of ``certification``. Allowed only while in SECURITY_REVIEW, with a report."""
    _governed(actor, reason)
    if entry.state != LabState.SECURITY_REVIEW:
        raise ValueError(f"{entry.name}: a verdict may only be recorded in SECURITY_REVIEW (state {entry.state.value})")
    if not evidence:
        raise ValueError(f"{entry.name}: a verdict requires its report as evidence (§114)")
    verdict = Verdict(verdict)
    rec = _audit(entry, kind="verdict", to=verdict.value, actor=actor, reason=reason, evidence=evidence, at=at)
    entry.certification = verdict
    return rec


def justify_adoption(entry: OsCatalogEntry, *, gap: str, why_existing_insufficient: str,
                     alternatives_considered: tuple[str, ...] | list[str], at: str = "UNKNOWN") -> GapJustification:
    """§117 — record the concrete-gap justification. Operator-only; every field non-empty."""
    alts = tuple(a for a in alternatives_considered if a and a.strip())
    if not (gap and gap.strip()) or not (why_existing_insufficient and why_existing_insufficient.strip()) or not alts:
        raise ValueError(f"{entry.name}: §117 justification needs gap, why_existing_insufficient and ≥1 alternative")
    gj = GapJustification(gap=gap, why_existing_insufficient=why_existing_insufficient, alternatives_considered=alts)
    _audit(entry, kind="gap_justification", to=entry.state.value, actor="operator", reason=gap,
           evidence=asdict(gj), at=at)
    entry.gap_justification = gj
    return gj


def record_repo_instruction(entry: OsCatalogEntry, text: str) -> LabState:
    """§113 — a README/INSTALL/repo instruction is DATA. Stored (redacted) for review; NEVER acts.
    Returns the unchanged state so callers cannot mistake this for a transition."""
    entry.repo_instructions.append(redact(str(text)))
    return entry.state


# ── §115/§116 curated initial catalog ─────────────────────────────────────────
_NOT_FETCHED = "canonical_source recorded from the well-known upstream location; NOT fetched in this phase (§115 catalog-first)."


def initial_catalog() -> list[OsCatalogEntry]:
    """Fresh entries every call (they are mutable lifecycle objects). All DISCOVERED/UNTRUSTED/UNVERIFIED."""
    E = OsCatalogEntry
    return [
        E("Ultron OS", "https://github.com/aswinmohanme/ultronOS", OsCategory.EDUCATIONAL_REFERENCE,
          (Disposition.EDUCATIONAL_SANDBOX,), RiskClass.HIGH,
          description="§40 educational OS sandbox candidate — isolated QEMU only, production=NO.",
          notes=_NOT_FETCHED + " Small-author repo: provenance, license and activity all UNVERIFIED."),
        E("virtme-ng", "https://github.com/arighi/virtme-ng", OsCategory.RESTRICTED_SECURITY_LAB,
          (Disposition.RESTRICTED_KERNEL_TEST_CANDIDATE,), RiskClass.RESTRICTED,
          description="§42 restricted kernel-test tooling candidate — default OFF, prod DISABLED.",
          notes=_NOT_FETCHED),
        E("Bottlerocket", "https://github.com/bottlerocket-os/bottlerocket", OsCategory.INFRA_CANDIDATE,
          (Disposition.INFRA_CANDIDATE,), RiskClass.MEDIUM, website="https://bottlerocket.dev",
          description="Container-host OS candidate for future infra evaluation. Not selected for anything.",
          notes=_NOT_FETCHED),
        E("Qubes OS", "https://github.com/QubesOS", OsCategory.SECURITY_REFERENCE,
          (Disposition.SECURITY_REFERENCE,), RiskClass.LOW, website="https://www.qubes-os.org",
          description="§44 compartmentalization principles reference — read, never executed.",
          notes=_NOT_FETCHED),
        E("Genode", "https://github.com/genodelabs/genode", OsCategory.SECURITY_REFERENCE,
          (Disposition.SECURITY_REFERENCE,), RiskClass.LOW, website="https://genode.org",
          description="§44 capability-based OS framework reference — read, never executed.",
          notes=_NOT_FETCHED),
        E("Unikraft", "https://github.com/unikraft/unikraft", OsCategory.SANDBOX_RUNTIME,
          (Disposition.EXPERIMENTAL_RUNTIME,), RiskClass.HIGH, website="https://unikraft.org",
          description="Unikernel runtime — experimental; adoption gated by §117.",
          notes=_NOT_FETCHED),
        E("Nanos", "https://github.com/nanovms/nanos", OsCategory.SANDBOX_RUNTIME,
          (Disposition.EXPERIMENTAL_RUNTIME,), RiskClass.HIGH, website="https://nanos.org",
          description="Unikernel runtime — experimental; adoption gated by §117.",
          notes=_NOT_FETCHED),
        E("Hermit", "https://github.com/hermit-os/kernel", OsCategory.SANDBOX_RUNTIME,
          (Disposition.EXPERIMENTAL_RUNTIME,), RiskClass.HIGH, website="https://hermit-os.org",
          description="Rust unikernel runtime — experimental; adoption gated by §117.",
          notes=_NOT_FETCHED + " Upstream org/repo has been renamed historically — SOURCE_VERIFIED must confirm the canonical path."),
        E("syzkaller", "https://github.com/google/syzkaller", OsCategory.RESTRICTED_SECURITY_LAB,
          (Disposition.RESTRICTED_SECURITY_LAB,), RiskClass.RESTRICTED,
          description="§43 kernel fuzzer — restricted security lab only, disposable isolated VM, heavy operator authorization.",
          notes=_NOT_FETCHED),
        E("Linux", "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git", OsCategory.PRODUCTION_PLATFORM,
          (Disposition.PRODUCTION_PLATFORM, Disposition.KNOWLEDGE_REFERENCE), RiskClass.LOW, website="https://kernel.org",
          description="The platform production already runs on + knowledge reference. Catalog entry ≠ a re-certification of prod.",
          notes=_NOT_FETCHED),
        E("FreeBSD", "https://git.freebsd.org/src.git", OsCategory.KNOWLEDGE_PACK,
          (Disposition.KNOWLEDGE_REFERENCE,), RiskClass.LOW, website="https://www.freebsd.org",
          description="Knowledge reference only.",
          notes=_NOT_FETCHED),
    ]


def get(name: str, catalog: list[OsCatalogEntry]) -> OsCatalogEntry | None:
    return next((e for e in catalog if e.name.lower() == name.lower()), None)
