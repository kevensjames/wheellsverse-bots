"""SelfImprovementEngine (Part B, §15-53) — evidence-driven, PREPARE-only self-repair, never release.

Role: identify a measurable internal defect → gather independent evidence → decide a code change is
actually warranted (not deployment/config) → prepare it in an isolated worktree via the A2 framework →
independently verify → leave it READY_FOR_REVIEW for the owner. It NEVER merges/deploys/rotates secrets/
disables controls/changes MONEY_MODE (§35). No improvement originates from "I think this'd be better"
(§16/§18): a candidate must cite evidence and support a measurable value outcome.

The engine composes the CERTIFIED spine (health/repo/log/deployment/test) — passed in as diagnosis
inputs so this is deterministic and DB-free — and drives the limited A2 framework for preparation. It
adds the grant-specific diff limits (§25) and dependency-file denial (§26) on top of A2's authority gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum

from app.services.holding.a2_framework import A2Grant, A2ActionType, A2State
from app.services.holding.deployment_status import MATCH, DEPLOYMENT_BEHIND, UNCOMPARABLE


class ImprovementStatus(str, Enum):
    DETECTED = "DETECTED"; EVIDENCE_GATHERING = "EVIDENCE_GATHERING"; CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"; PLANNED = "PLANNED"; PREPARING = "PREPARING"; VERIFYING = "VERIFYING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"; BLOCKED = "BLOCKED"; BLOCKED_EVIDENCE = "BLOCKED_EVIDENCE"
    FAILED = "FAILED"; SUPERSEDED = "SUPERSEDED"; OWNER_REQUIRED = "OWNER_REQUIRED"


# §18 measurable value outcomes — a candidate must support at least one (no cosmetic self-work).
VALUE_OUTCOMES = frozenset({
    "RELIABILITY", "SECURITY", "PERFORMANCE", "COST", "TEST_COVERAGE", "CORRECTNESS",
    "OBSERVABILITY", "MAINTAINABILITY", "DOCUMENTATION_ACCURACY", "OPERATOR_EFFICIENCY"})

# §8/§41 diagnosis this engine decides before any code change.
DIAG_SOURCE_DEFECT = "SOURCE_DEFECT"; DIAG_DEPLOYMENT_STALE = "DEPLOYMENT_STALE"
DIAG_CONFIG = "CONFIG"; DIAG_INSUFFICIENT = "INSUFFICIENT"

# §25 diff limits (conservative, versioned) — exceeded → OWNER_REQUIRED.
DIFF_POLICY_VERSION = "1.0.0"
MAX_FILES_CHANGED = 10
MAX_BINARY_FILES = 0

# §26 dependency/build files an A2 self-improvement change must NOT touch autonomously → OWNER_REQUIRED.
_DEPENDENCY_FILES = re.compile(
    r"(requirements[^/]*\.txt|pyproject\.toml|poetry\.lock|package(-lock)?\.json|yarn\.lock|"
    r"pnpm-lock\.yaml|dockerfile|\.dockerfile|docker-compose|\.github/workflows/|pipfile|"
    r"go\.mod|go\.sum|cargo\.(toml|lock)|gemfile)", re.I)


def is_dependency_file(path: str) -> bool:
    return bool(path) and bool(_DEPENDENCY_FILES.search(str(path).lower()))


@dataclass
class SelfImprovementCandidate:
    improvement_id: str
    subsystem: str
    problem_type: str
    problem: str
    desired_outcome: str                 # must be in VALUE_OUTCOMES (§18)
    company_id: str = ""
    evidence_refs: list = field(default_factory=list)
    baseline: str = ""
    measurement: str = ""
    risk: str = "LOW"
    affected_paths: list = field(default_factory=list)
    required_capabilities: list = field(default_factory=list)
    proposed_action_class: str = "A2_REVERSIBLE_INTERNAL_WRITE"
    created_at: str = ""
    status: str = ImprovementStatus.DETECTED.value
    diagnosis: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# §21 the FIRST narrow A2 grant — non-production, one approved repo, source+test+doc edits only.
def self_improvement_grant_v1(company_id: str = "kai") -> A2Grant:
    return A2Grant(action_type=A2ActionType.EDIT_CODE_IN_WORKTREE.value, capability="coding",
                   company_id=company_id, environment="development")


GRANT_NAME = "SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1"


class SelfImprovementEngine:
    def __init__(self, *, a2_framework, reviewer: str = "kai-independent-reviewer"):
        self._a2 = a2_framework
        self._reviewer = reviewer

    # ── §16-20 diagnosis + confirmation ──────────────────────────────────────────────────────────
    def confirm(self, cand: SelfImprovementCandidate, *, deployment_comparison: str = UNCOMPARABLE,
                test_before_fails: bool = False, is_config_issue: bool = False) -> SelfImprovementCandidate:
        """Decide whether a SOFTWARE change is warranted. §18 value gate, §41 deployment-stale, §42
        config, §20/§30 code-change requires a reproducing test. Mutates + returns the candidate."""
        if cand.desired_outcome not in VALUE_OUTCOMES:      # §18 no cosmetic self-work
            cand.status = ImprovementStatus.REJECTED.value; cand.diagnosis = "NO_VALUE_OUTCOME"; return cand
        if deployment_comparison == DEPLOYMENT_BEHIND:      # §41 CRITICAL — source may already be fixed
            cand.status = ImprovementStatus.BLOCKED.value; cand.diagnosis = DIAG_DEPLOYMENT_STALE; return cand
        if is_config_issue:                                 # §42 no autonomous config write
            cand.status = ImprovementStatus.OWNER_REQUIRED.value; cand.diagnosis = DIAG_CONFIG; return cand
        if not test_before_fails:                           # §20/§30/§40 need a reproducing test
            cand.status = ImprovementStatus.BLOCKED_EVIDENCE.value; cand.diagnosis = DIAG_INSUFFICIENT; return cand
        cand.status = ImprovementStatus.CONFIRMED.value; cand.diagnosis = DIAG_SOURCE_DEFECT; return cand

    # ── §27-36 prepare via the A2 framework, then apply grant-specific diff limits ────────────────
    def prepare(self, cand: SelfImprovementCandidate, task) -> dict:
        """Prepare the fix (isolated worktree → worker → git-diff authority gate → tests → independent
        review) via the A2 framework, then enforce §25 diff limits + §26 dependency denial + §33 test-
        cheating heuristic. Returns {status, diagnosis, prepared, review_package}. Never merges (§35)."""
        if cand.status != ImprovementStatus.CONFIRMED.value:
            return {"status": cand.status, "diagnosis": cand.diagnosis, "prepared": None}
        prep = self._a2.prepare(task)                       # A2 does worktree/worker/authority/tests/review
        if not prep.ready_for_review:
            # A2 already fails closed (OWNER_REQUIRED / BLOCKED / NEEDS_CERTIFICATION) — carry it through
            cand.status = (ImprovementStatus.OWNER_REQUIRED.value if prep.state == A2State.OWNER_REQUIRED.value
                           else ImprovementStatus.FAILED.value if prep.state == A2State.BLOCKED.value
                           else ImprovementStatus.BLOCKED.value)
            return {"status": cand.status, "diagnosis": cand.diagnosis, "prepared": prep.as_dict()}
        files = list(prep.files_changed or [])
        # §26 dependency/build files → OWNER_REQUIRED (no autonomous dependency introduction)
        deps = [f for f in files if is_dependency_file(f)]
        if deps:
            cand.status = ImprovementStatus.OWNER_REQUIRED.value
            return {"status": cand.status, "diagnosis": "DEPENDENCY_CHANGE", "prepared": prep.as_dict(),
                    "reason": f"dependency/build files require owner review: {deps[:5]}"}
        # §25 diff bounds
        if len(files) > MAX_FILES_CHANGED:
            cand.status = ImprovementStatus.OWNER_REQUIRED.value
            return {"status": cand.status, "diagnosis": "DIFF_TOO_LARGE", "prepared": prep.as_dict(),
                    "reason": f"{len(files)} files > {MAX_FILES_CHANGED} (policy {DIFF_POLICY_VERSION})"}
        # §33 test-cheating heuristic: a CORRECTNESS/RELIABILITY fix that changes ONLY test files (no
        # source) is suspicious (the defect should be fixed in source) → OWNER_REQUIRED.
        non_test = [f for f in files if "test" not in str(f).lower()]
        if cand.desired_outcome in ("CORRECTNESS", "RELIABILITY") and files and not non_test:
            cand.status = ImprovementStatus.OWNER_REQUIRED.value
            return {"status": cand.status, "diagnosis": "POSSIBLE_TEST_CHEATING", "prepared": prep.as_dict(),
                    "reason": "change touches only test files for a source-defect fix"}
        cand.status = ImprovementStatus.READY_FOR_REVIEW.value
        return {"status": cand.status, "diagnosis": cand.diagnosis, "prepared": prep.as_dict(),
                "review_package": self.owner_review_package(cand, prep)}

    # ── §36 owner review package (ONE review action, KAI already did the rest) ─────────────────────
    def owner_review_package(self, cand: SelfImprovementCandidate, prep) -> dict:
        return {
            "problem": cand.problem, "evidence": cand.evidence_refs, "root_cause": cand.diagnosis,
            "files_changed": prep.files_changed, "branch": prep.branch,
            "tests_before": "FAIL (reproduced)", "tests_after": f"{prep.tests_passed} passed/{prep.tests_failed} failed",
            "security_review": "independent reviewer certified; authority-immutable gate clean",
            "diff_summary": (prep.evidence or {}).get("diff_summary", ""),
            "expected_impact": cand.desired_outcome, "rollback": "discard the isolated worktree/branch",
            "known_limitations": "prepared only — NOT merged or deployed (owner action required)",
            "owner_action": "REVIEW + approve the next higher-class action (merge) if acceptable"}


if __name__ == "__main__":
    from app.services.holding.test_self_improvement import run
    run()
