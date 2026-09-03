"""Limited A2 framework (Part D, §34-41) — safe REVERSIBLE_INTERNAL_WRITE preparation, never release.

A2 is NOT broad write authority. It is granted PER (action_type, capability, company, environment) —
never globally (§34). The only allowed A2 actions prepare an isolated change: create-worktree,
feature-branch, edit-in-worktree, update-internal-doc, draft-PR-artifact (§35/§38). Merge, production
push/deploy, external publish, permission/credential change, and money are NOT A2 and never will be
here (§38/§41). Completion means PREPARED (READY_FOR_REVIEW), not released — the owner merges.

Two non-negotiable gates reuse the certified coding layer:
  • independent review — `certify_worker_result` refuses a worker certifying itself (§40 no self-approval);
  • authority routing — a PATH-based pre-filter routes a diff touching approval gates / risk policy /
    security kill switch / auth / money / audit / credential / deploy / dependency-build / the certified
    test suite to OWNER_REQUIRED (§40). It is a defense-in-depth denylist (path match, not content), NOT
    a full content guarantee — the hard invariant is that A2 NEVER merges/deploys, so every prepared change
    is owner-reviewed before it can take effect. The path gate stops the obvious classes automatically.

Worker/worktree/test operations are injectable, so the whole flow is a deterministic self-test with no
real git mutation; the real ops (git worktree, CodingWorkerRouter, RUN_INTERNAL_TEST) plug in unchanged.
"""
from __future__ import annotations

import re
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
# not autonomously modify its own approval gates, RBAC/roles, risk classes, kill switches, the autonomy
# engine itself, auth, money, audit, or credentials. (Adversarial recheck: the operative kill switches
# live in the holding autonomy engine and RBAC/approval-gate files, so those are covered explicitly.)
_AUTHORITY_IMMUTABLE = (
    "config.py", "app/config",
    # capability governance (the whole governance surface is authority) — incl. the no-self-approval gate
    "services/capability/risk", "services/capability/security", "services/capability/manifest",
    "services/capability/execution", "services/capability/invocation", "services/capability/lifecycle",
    "services/capability/governance", "services/capability/coding", "governed_invoke",
    "certify_worker_result",
    # the holding AUTONOMY engine + its kill switches / owner-queue routing / grant registry / self-improve
    "services/holding/autonomous_work", "services/holding/plan", "services/holding/task_resolver",
    "services/holding/owner_queue", "services/holding/state_reconciler", "services/holding/a2_framework",
    "services/holding/self_improvement", "services/holding/digital_twin", "kill_switch", "kill-switch",
    # auth / RBAC / approval gates
    "kai_bridge", "auth", "session", "require_kai_ultra", "require_admin", "resolve_principal",
    "rbac", "role", "policy", "permission", "dependencies/admin", "routers/admin_users", "api_key",
    # money / audit / credentials / deploy (money tokens broadened: F4 naming-mismatch false-negatives)
    "financial", "money", "billing", "stripe", "dwolla", "payout", "ledger", "wallet", "payment",
    "invoice", "transaction", "audit", "credential", "secret", "deploy", "railway",
    # the CERTIFIED suites the A2 test gate runs — the judge must never be editable by the judged (F5).
    # test_si_calc_guard is the before/after fixture's oracle: runnable by the worker, NEVER editable by it.
    "test_self_model", "test_state_reconciler", "test_si_calc_guard")


# §26/§25 — dependency-manifest / build-file / binary / oversized gates. These live HERE at the shared
# A2Framework boundary (not only in SelfImprovementEngine) so BOTH A2 drivers — the self-improvement
# engine AND autonomous_work's direct prepare() path — enforce them identically.
DIFF_POLICY_VERSION = "1.1.0"
MAX_FILES_CHANGED = 10
MAX_TOTAL_DIFF_LINES = 400
_DEPENDENCY_FILES = re.compile(
    r"(requirements[^/]*\.txt|requirements/|constraints[^/]*\.txt|pyproject\.toml|setup\.py|setup\.cfg|"
    r"poetry\.lock|package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|dockerfile|\.dockerfile|"
    r"docker-compose|\.github/workflows/|gitlab-ci|jenkinsfile|nixpacks|procfile|buildspec|\.circleci|"
    r"makefile|pipfile|go\.mod|go\.sum|cargo\.(toml|lock)|gemfile)", re.I)
_BINARY_EXT = re.compile(
    r"\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|tar|7z|so|dylib|dll|exe|bin|wasm|whl|jar|class|pyc|"
    r"woff2?|ttf|mp4|mov|mp3|onnx|pt|pth|model|db|sqlite)$", re.I)


def is_dependency_file(path: str) -> bool:
    """A dependency-manifest / lockfile / CI-build file — an autonomous A2 change to one is OWNER_REQUIRED
    (§26: install/build/merge-time code-execution vector, never introduced without owner review)."""
    return bool(path) and bool(_DEPENDENCY_FILES.search(str(path).lower()))


def is_binary_file(path: str) -> bool:
    """A binary-looking file (extension heuristic) — MAX_BINARY_FILES=0 for an autonomous A2 change."""
    return bool(path) and bool(_BINARY_EXT.search(str(path)))


def touches_authority(files_changed: list) -> list:
    """Return the subset of changed files that touch authority-immutable surfaces (§40). The caller MUST
    pass the git-derived diff of the worktree, NOT the worker's self-reported list (the gate must not
    trust the output it polices)."""
    hits = []
    for f in files_changed or []:
        low = str(f).lower().replace("\\", "/")
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
        env = (gr.environment or "").strip().lower()
        if env == "production" or not env:                   # case-insensitive; empty is not allowed
            raise ValueError("A2 grants are never for production (§38/§41)")
        if gr.action_type in FORBIDDEN_A2_ACTIONS:
            raise ValueError(f"'{gr.action_type}' is not an A2 action")
        self._g.add((gr.action_type, gr.capability, gr.company_id, env))

    def is_granted(self, action_type: str, capability: str, company_id: str, environment: str) -> bool:
        return (action_type, capability, company_id, (environment or "").strip().lower()) in self._g


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
    total_diff_lines: int = 0
    diagnosis: str = ""             # gate reason code (DEPENDENCY_CHANGE / BINARY_CHANGE / DIFF_TOO_LARGE)
    ready_for_review: bool = False
    merged: bool = False            # ALWAYS False — A2 never merges (invariant, asserted by tests)
    deployed: bool = False          # ALWAYS False — A2 never deploys

    def as_dict(self) -> dict:
        return asdict(self)


class A2Framework:
    def __init__(self, registry: A2GrantRegistry, *, worktree_fn=None, worker_fn=None,
                 test_fn=None, diff_fn=None, diff_lines_fn=None, reviewer: str = "kai-independent-reviewer"):
        self._reg = registry
        # worktree_fn(mission_id, base_sha, base_dir) -> WorktreeAssignment (default: path-only, no FS op)
        self._worktree = worktree_fn or self._default_worktree
        # worker_fn(task, worktree) -> WorkerResult (the CodingWorkerRouter-dispatched change)
        self._worker = worker_fn
        # test_fn(worktree) -> {tests_run,tests_passed,tests_failed} (RUN_INTERNAL_TEST in the worktree)
        self._test = test_fn
        # diff_fn(worktree, base_sha) -> [changed files] — the AUTHORITATIVE diff from the worktree, used
        # for the §40 authority gate instead of the untrusted worker self-report. Default: real git diff.
        self._diff = diff_fn or self._default_diff
        # diff_lines_fn(worktree, base_sha) -> int total changed lines (default: git numstat); 0 = unknown
        self._diff_lines = diff_lines_fn or self._default_diff_lines
        self._reviewer = reviewer

    @staticmethod
    def _default_worktree(mission_id, base_sha, base_dir):
        # path assignment only (no real git mutation) — the real op plugs in via worktree_fn
        return assign_worktrees(["a2"], mission_id, base_sha, base_dir)[0]

    @staticmethod
    def _default_diff(worktree, base_sha):
        # AUTHORITATIVE read-only diff since base_sha, capturing BOTH committed and uncommitted changes
        # (a committing worker leaves a clean working tree, so base..HEAD must be unioned with base..WT).
        # base_sha is REQUIRED — without it committed changes are invisible → fail closed (recheck HIGH).
        import subprocess
        if not base_sha:
            raise RuntimeError("base_sha required to verify the worktree diff")
        files = set()
        for extra in (["HEAD"], []):     # base..HEAD (committed) ∪ base..working-tree (uncommitted)
            out = subprocess.run(["git", "-C", worktree, "diff", "--name-only", base_sha, *extra],
                                 capture_output=True, text=True, timeout=15)
            if out.returncode != 0:
                raise RuntimeError("worktree diff unavailable")
            files.update(ln.strip() for ln in out.stdout.splitlines() if ln.strip())
        return sorted(files)

    @staticmethod
    def _default_diff_lines(worktree, base_sha):
        import subprocess
        if not base_sha:
            return 0
        out = subprocess.run(["git", "-C", worktree, "diff", "--numstat", base_sha, "HEAD"],
                             capture_output=True, text=True, timeout=15)
        total = 0
        for ln in out.stdout.splitlines():
            parts = ln.split("\t")
            for n in parts[:2]:
                if n.isdigit():
                    total += int(n)
        return total

    def prepare(self, task) -> A2Prepared:
        """Run the A2 flow (§39) to a PREPARED result, or a fail-closed non-ready state. Never merges."""
        action_type = getattr(task, "a2_action_type", "") or ""
        company = getattr(task, "company_id", "")
        capability = getattr(task, "capability", "coding")
        env = (getattr(task, "environment", "development") or "development").strip().lower()   # case-normalized
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
        # 6. §40 authority immutability — derive the AUTHORITATIVE changed-file set from the worktree
        #    itself (never the untrusted worker's self-report), then gate. No verifiable diff → fail closed.
        try:
            files = list(self._diff(wt.worktree, getattr(task, "base_sha", "")))
            diff_lines = int(self._diff_lines(wt.worktree, getattr(task, "base_sha", "")) or 0)
        except Exception as e:
            return result(A2State.BLOCKED, branch=wt.branch, worktree=wt.worktree,
                          reason=f"cannot verify worktree diff (fail closed): {str(e)[:80]}")
        # an EMPTY verifiable diff is never "clean" — it means a no-op or a wrong base_sha (recheck HIGH):
        # fail closed rather than staging a change with no reviewable evidence.
        if not files:
            return result(A2State.BLOCKED, branch=wt.branch, worktree=wt.worktree,
                          reason="empty/unverifiable diff (no-op or wrong base_sha) — not ready")
        auth_hits = touches_authority(files)
        if auth_hits:
            return result(A2State.OWNER_REQUIRED, branch=wt.branch, worktree=wt.worktree,
                          files_changed=files, total_diff_lines=diff_lines,
                          reason=f"diff touches authority-immutable surface(s): {auth_hits[:5]}")
        # §26/§25 — a dependency/build-file, a binary, or an oversized change is an explicitly-denied A2
        # category: it reaches the OWNER, never READY_FOR_REVIEW. Enforced HERE so the direct
        # autonomous_work path (and the cert) are gated identically to SelfImprovementEngine.
        dep_hits = [f for f in files if is_dependency_file(f)]
        if dep_hits:
            return result(A2State.OWNER_REQUIRED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          total_diff_lines=diff_lines, diagnosis="DEPENDENCY_CHANGE",
                          reason=f"dependency/build-file change is owner-gated: {dep_hits[:5]}")
        bin_hits = [f for f in files if is_binary_file(f)]
        if bin_hits:
            return result(A2State.OWNER_REQUIRED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          total_diff_lines=diff_lines, diagnosis="BINARY_CHANGE",
                          reason=f"binary-file change is owner-gated: {bin_hits[:5]}")
        if len(files) > MAX_FILES_CHANGED or diff_lines > MAX_TOTAL_DIFF_LINES:
            return result(A2State.OWNER_REQUIRED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          total_diff_lines=diff_lines, diagnosis="DIFF_TOO_LARGE",
                          reason=f"oversized change ({len(files)} files / {diff_lines} lines) is owner-gated "
                                 f"(policy {DIFF_POLICY_VERSION})")
        # 7. run tests IN the worktree (§39). Test evidence is NEVER taken from the worker's self-report
        #    (recheck): a wired worker REQUIRES an independent test_fn, else fail closed.
        if self._test is None:
            return result(A2State.BLOCKED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          total_diff_lines=diff_lines,
                          reason="no independent test verification wired — worker test counts are not trusted")
        t = self._test(wt)
        wr.tests_run, wr.tests_passed, wr.tests_failed = t["tests_run"], t["tests_passed"], t["tests_failed"]
        # 8. INDEPENDENT review — certify_worker_result refuses self-certification (§40 no self-approval)
        try:
            wr = certify_worker_result(wr, reviewed_by=self._reviewer, tests_ok=(wr.tests_failed == 0))
        except ValueError as e:
            return result(A2State.BLOCKED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          reason=str(e))
        if not wr.certified:
            return result(A2State.BLOCKED, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                          total_diff_lines=diff_lines,
                          tests_run=wr.tests_run, tests_passed=wr.tests_passed, tests_failed=wr.tests_failed,
                          reviewed=wr.reviewed, reason="tests failed or no tests — not ready for review")
        # 9. PREPARED — ready for the OWNER to review/merge (A2 never merges/deploys §41)
        return result(A2State.READY_FOR_REVIEW, branch=wt.branch, worktree=wt.worktree, files_changed=files,
                      total_diff_lines=diff_lines,
                      tests_run=wr.tests_run, tests_passed=wr.tests_passed, tests_failed=wr.tests_failed,
                      reviewed=True, certified=True, reviewer=self._reviewer, ready_for_review=True,
                      evidence={"diff_summary": wr.diff_summary, "starting_sha": wr.starting_sha,
                                "artifacts": wr.artifacts})


if __name__ == "__main__":
    from app.services.holding.test_a2_framework import run
    run()
