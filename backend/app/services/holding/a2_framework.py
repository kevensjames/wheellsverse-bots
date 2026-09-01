"""Limited A2 framework (Part D, §34-41) — safe REVERSIBLE_INTERNAL_WRITE preparation, never release.

A2 is NOT broad write authority. It is granted PER (action_type, capability, company, environment) —
never globally (§34). The only allowed A2 actions prepare an isolated change: create-worktree,
feature-branch, edit-in-worktree, update-internal-doc, draft-PR-artifact (§35/§38). Merge, production
push/deploy, external publish, permission/credential change, and money are NOT A2 and never will be
here (§38/§41). Completion means PREPARED (READY_FOR_REVIEW), not released — the owner merges.

Two non-negotiable gates reuse the certified coding layer:
  • independent review — `certify_worker_result` refuses a worker certifying itself (§40 no self-approval);
  • authority immutability — a diff touching approval gates / risk policy / security kill switch / auth /
    financial / audit / credential scope / production-deploy authority is OWNER_REQUIRED, never A2 (§40).

Worker/worktree/test operations are injectable, so the whole flow is a deterministic self-test with no
real git mutation; the real ops (git worktree, CodingWorkerRouter, RUN_INTERNAL_TEST) plug in unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum

from app.services.capability.coding import certify_worker_result, WorkerResult, assign_worktrees


class A2ActionType(str, Enum):
    CREATE_ISOLATED_WORKTREE = "CREATE_ISOLATED_WORKTREE"
    CREATE_FEATURE_BRANCH = "CREATE_FEATURE_BRANCH"
    EDIT_CODE_IN_WORKTREE = "EDIT_CODE_IN_WORKTREE"
    UPDATE_INTERNAL_DOC = "UPDATE_INTERNAL_DOC"
    CREATE_DRAFT_PR_ARTIFACT = "CREATE_DRAFT_PR_ARTIFACT"


# Actions that are explicitly NOT A2 and must never be granted here (§38/§41) — belong to A3+/owner.
FORBIDDEN_A2_ACTIONS = frozenset({
    "MERGE", "PUSH_PRODUCTION", "DEPLOY", "DEPLOY_PRODUCTION", "EXTERNAL_PUBLISH",
    "PERMISSION_CHANGE", "CREDENTIAL_CHANGE", "ROTATE_SECRET", "DATABASE_PRODUCTION_WRITE",
    "DNS_CHANGE", "SCALE", "ROLLBACK", "MONEY", "TRADE", "PAYOUT", "AD_SPEND"})


class A2State(str, Enum):
    DETECTED = "DETECTED"; SPEC = "SPEC"; WORKTREE = "WORKTREE"; WORKER = "WORKER"
    TESTS = "TESTS"; REVIEW = "REVIEW"; EVIDENCE = "EVIDENCE"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"; BLOCKED = "BLOCKED"
    NEEDS_CERTIFICATION = "NEEDS_CERTIFICATION"; OWNER_REQUIRED = "OWNER_REQUIRED"


# §40 authority-immutable path fragments — an A2 diff touching any of these is OWNER_REQUIRED. KAI may
# not autonomously modify its own approval gates, risk classes, kill switches, auth, money, audit, creds.
_AUTHORITY_IMMUTABLE = (
    "config.py", "app/config", "services/capability/risk", "services/capability/security",
    "services/capability/manifest", "kai_bridge", "auth", "session", "require_kai_ultra",
    "financial", "money", "billing", "stripe", "dwolla", "audit", "credential", "secret",
    "kill_switch", "deploy", "railway", "resolve_principal", "a2_framework")


def touches_authority(files_changed: list) -> list:
    """Return the subset of changed files that touch authority-immutable surfaces (§40)."""
    hits = []
    for f in files_changed or []:
        low = str(f).lower()
        if any(frag in low for frag in _AUTHORITY_IMMUTABLE):
            hits.append(f)
    return hits


@dataclass(frozen=True)
class A2Grant:
    action_type: str
    capability: str
    company_id: str
    environment: str = "development"     # never "production" for A2 here


class A2GrantRegistry:
    """Explicit per-(action_type, capability, company, environment) grants (§34). Default: empty →
    everything NEEDS_CERTIFICATION. Grants are for non-production environments only."""
    def __init__(self, grants: list | None = None):
        self._g = set()
        for gr in (grants or []):
            self.grant(gr)

    def grant(self, gr: A2Grant) -> None:
        if gr.environment == "production":
            raise ValueError("A2 grants are never for production (§38/§41)")
        if gr.action_type in FORBIDDEN_A2_ACTIONS:
            raise ValueError(f"'{gr.action_type}' is not an A2 action")
        self._g.add((gr.action_type, gr.capability, gr.company_id, gr.environment))

    def is_granted(self, action_type: str, capability: str, company_id: str, environment: str) -> bool:
        return (action_type, capability, company_id, environment) in self._g


@dataclass
class A2Prepared:
    state: str
    action_type: str
    company_id: str
    reason: str = ""
    branch: str = ""
    worktree: str = ""
    files_changed: list = field(default_factory=list)
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    reviewed: bool = False
    certified: bool = False
    reviewer: str = ""
    evidence: dict = field(default_factory=dict)
    ready_for_review: bool = False
    merged: bool = False            # ALWAYS False — A2 never merges (invariant, asserted by tests)
    deployed: bool = False          # ALWAYS False — A2 never deploys

    def as_dict(self) -> dict:
        return asdict(self)


class A2Framework:
    def __init__(self, registry: A2GrantRegistry, *, worktree_fn=None, worker_fn=None,
                 test_fn=None, reviewer: str = "kai-independent-reviewer"):
        self._reg = registry
        # worktree_fn(mission_id, base_sha, base_dir) -> WorktreeAssignment (default: path-only, no FS op)
        self._worktree = worktree_fn or self._default_worktree
        # worker_fn(task, worktree) -> WorkerResult (the CodingWorkerRouter-dispatched change)
        self._worker = worker_fn
        # test_fn(worktree) -> {tests_run,tests_passed,tests_failed} (RUN_INTERNAL_TEST in the worktree)
        self._test = test_fn
        self._reviewer = reviewer

    @staticmethod
    def _default_worktree(mission_id, base_sha, base_dir):
        # path assignment only (no real git mutation) — the real op plugs in via worktree_fn
        return assign_worktrees(["a2"], mission_id, base_sha, base_dir)[0]

    def prepare(self, task) -> A2Prepared:
        """Run the A2 flow (§39) to a PREPARED result, or a fail-closed non-ready state. Never merges."""
        action_type = getattr(task, "a2_action_type", "") or ""
        company = getattr(task, "company_id", "")
        capability = getattr(task, "capability", "coding")
        env = getattr(task, "environment", "development")
        mission_id = getattr(task, "task_id", "a2")

        def result(state, **kw):
            return A2Prepared(state=state.value if isinstance(state, A2State) else state,
                              action_type=action_type, company_id=company, **kw)

        # 1. forbidden / unknown action → fail closed (§38)
        if action_type in FORBIDDEN_A2_ACTIONS:
            return result(A2State.OWNER_REQUIRED, reason=f"'{action_type}' is A3+/owner, never A2")
        if action_type not in {a.value for a in A2ActionType}:
            return result(A2State.BLOCKED, reason=f"unknown A2 action '{action_type}'")
        # 2. production environment is never A2 (§41)
        if env == "production":
            return result(A2State.OWNER_REQUIRED, reason="production changes are owner-gated")
        # 3. per-grant eligibility (§34) — no grant → needs certification, never a default-allow
        if not self._reg.is_granted(action_type, capability, company, env):
            return result(A2State.NEEDS_CERTIFICATION,
                          reason=f"no A2 grant for ({action_type},{capability},{company},{env})")
        # 4. isolated worktree + branch (§39/§12-13)
        wt = self._worktree(mission_id, getattr(task, "base_sha", ""), getattr(task, "base_dir", "/tmp/kai-a2"))
        if self._worker is None:
            # framework can prepare the worktree/branch but has no coding worker wired yet
            return result(A2State.WORKTREE, reason="isolated worktree prepared; no coding worker wired",
                          branch=wt.branch, worktree=wt.worktree)
        # 5. worker performs the change in the ISOLATED worktree (§39)
        wr: WorkerResult = self._worker(task, wt)
        files = list(wr.files_changed or [])
        # 6. §40 authority immutability — a diff touching authority surfaces is OWNER_REQUIRED, not A2
        auth_hits = touches_authority(files)
        if auth_hits:
            return result(A2State.OWNER_REQUIRED, branch=wt.branch, worktree=wt.worktree,
                          files_changed=files,
                          reason=f"diff touches authority-immutable surface(s): {auth_hits[:5]}")
        # 7. run tests IN the worktree (§39 RUN_INTERNAL_TEST again)
        t = self._test(wt) if self._test else {"tests_run": wr.tests_run, "tests_passed": wr.tests_passed,
                                               "tests_failed": wr.tests_failed}
        wr.tests_run, wr.tests_passed, wr.tests_failed = t["tests_run"], t["tests_passed"], t["tests_failed"]
        # 8. INDEPENDENT review — certify_worker_result refuses self-certification (§40 no self-approval)
        try:
            wr = certify_worker_result(wr, reviewed_by=self._reviewer, tests_ok=(wr.tests_failed == 0))
        except ValueError as e:
            return result(A2State.BLOCKED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          reason=str(e))
        if not wr.certified:
            return result(A2State.BLOCKED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          tests_run=wr.tests_run, tests_passed=wr.tests_passed, tests_failed=wr.tests_failed,
                          reviewed=wr.reviewed, reason="tests failed or no tests — not ready for review")
        # 9. PREPARED — ready for the OWNER to review/merge (A2 never merges/deploys §41)
        return result(A2State.READY_FOR_REVIEW, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                      tests_run=wr.tests_run, tests_passed=wr.tests_passed, tests_failed=wr.tests_failed,
                      reviewed=True, certified=True, reviewer=self._reviewer, ready_for_review=True,
                      evidence={"diff_summary": wr.diff_summary, "starting_sha": wr.starting_sha,
                                "artifacts": wr.artifacts})


if __name__ == "__main__":
    from app.services.holding.test_a2_framework import run
    run()
