"""Pure tests for the Coding Worker Router + result/verification/worktree doctrine (§10-§16).
Run: python3 backend/app/services/capability/test_capability_coding.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.manifest import (  # noqa: E402
    CapabilityManifest as CM, CapabilityType as CT, RiskClass, ActionClass, ActivationMode,
    Availability, Certification, WorkerProfile,
)
from capability.coding import (  # noqa: E402
    CodingTask, CodingWorkerRouter, coding_action_class, WorkerResult, certify_worker_result,
    assign_worktrees,
)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def worker(cid, cert=Certification.EXPERIMENTAL, provider="", ctx=64000, headless=True,
           parallel=False, interactive=False, modes=("implement",), risk=RiskClass.MEDIUM):
    return CM(id=cid, name=cid, type=CT.CODING_WORKER, availability=Availability.AVAILABLE,
              activation=ActivationMode.ON_DEMAND, risk_class=risk, certification=cert,
              worker_profile=WorkerProfile(coding_modes=list(modes), headless_support=headless,
                                           parallel_support=parallel, interactive_only=interactive,
                                           context_window=ctx, model_provider=provider, git_support=True))


def pool():
    return [
        worker("claude-code", cert=Certification.CERTIFIED, provider="anthropic", ctx=200000,
               modes=("implement", "review", "debug"), risk=RiskClass.MEDIUM),
        worker("codex", provider="openai", ctx=190000, modes=("implement", "test")),
        worker("gemini-cli", provider="google", ctx=1000000, modes=("implement",)),
        worker("cline", provider="anthropic", ctx=200000, parallel=True, modes=("implement", "review")),
        worker("windsurf", provider="anthropic", ctx=200000, headless=False, interactive=True),
    ]


R = CodingWorkerRouter()


# ── §11 selection is by attributes, not a hard-coded winner ───────────────────
def t_no_hardcoded_winner_provider():
    # a task pinned to OpenAI must NOT pick the CERTIFIED anthropic claude-code
    d = R.select(CodingTask(task_type="implement", required_model="openai"), pool())
    assert d.selected == "codex", f"provider pin must route to codex, got {d.selected}"
    d2 = R.select(CodingTask(task_type="implement", required_model="google"), pool())
    assert d2.selected == "gemini-cli"


def t_interactive_excluded_from_unattended():
    d = R.select(CodingTask(task_type="implement", unattended=True), pool())
    assert d.selected != "windsurf"
    assert any(cid == "windsurf" for cid, _ in d.rejected)


def t_parallel_requires_support():
    d = R.select(CodingTask(task_type="implement", parallel=True), pool())
    # only cline declares parallel_support in this pool
    assert d.selected == "cline", f"parallel task must route to a parallel-capable worker, got {d.selected}"


def t_unhealthy_excluded_and_none_when_all_down():
    health = {m.id: False for m in pool()}
    d = R.select(CodingTask(), pool(), health=health)
    assert d.selected is None and "no eligible" in d.reason


def t_reliability_and_context_for_hard_task():
    d = R.select(CodingTask(task_type="review", complexity="high", repo_size="large"), pool())
    # claude-code: CERTIFIED + review mode + 200k context → should win a hard review task
    assert d.selected == "claude-code", f"hard review should pick claude-code, got {d.selected} ({d.scores})"
    assert d.fallbacks, "fallbacks recorded (§19)"


# ── §14 coding action classes ─────────────────────────────────────────────────
def t_action_classes():
    assert coding_action_class("read") == ActionClass.READ_ONLY
    assert coding_action_class("edit") == ActionClass.REVERSIBLE_WRITE
    assert coding_action_class("commit") == ActionClass.HIGH_IMPACT
    assert coding_action_class("pr") == ActionClass.HIGH_IMPACT
    assert coding_action_class("merge") == ActionClass.DESTRUCTIVE
    assert coding_action_class("branch_protection") == ActionClass.PROHIBITED
    assert coding_action_class("something_unknown") == ActionClass.HIGH_IMPACT   # fail closed


# ── §16 a worker never certifies itself ───────────────────────────────────────
def t_worker_cannot_self_certify():
    r = WorkerResult(task="impl", worker="codex", tests_run=5, tests_passed=5, tests_failed=0)
    try:
        certify_worker_result(r, reviewed_by="codex", tests_ok=True); assert False, "self-cert must raise"
    except ValueError:
        pass
    certify_worker_result(r, reviewed_by="claude-code", tests_ok=True)
    assert r.reviewed is True and r.certified is True


def t_result_not_certified_without_passing_tests():
    r = WorkerResult(task="impl", worker="cline", tests_run=3, tests_passed=2, tests_failed=1)
    certify_worker_result(r, reviewed_by="claude-code", tests_ok=False)
    assert r.reviewed is True and r.certified is False, "failing tests → not certified"
    r2 = WorkerResult(task="impl", worker="cline", tests_run=0)   # 'done' with no tests
    certify_worker_result(r2, reviewed_by="claude-code", tests_ok=True)
    assert r2.certified is False, "no tests run → never certified (§15 no trust without evidence)"


# ── §12/§13 worktree isolation ────────────────────────────────────────────────
def t_worktree_isolation():
    a = assign_worktrees(["codex", "cline", "gemini-cli"], mission_id="m42", base_sha="abc123", base_dir="/wt")
    paths = [x.worktree for x in a]
    branches = [x.branch for x in a]
    assert len(set(paths)) == 3 and len(set(branches)) == 3, "each writable worker gets its own worktree+branch"
    assert all(x.starting_sha == "abc123" for x in a)
    try:
        assign_worktrees(["codex", "codex"], "m1", "sha", "/wt"); assert False
    except ValueError:
        pass


# ── §26 adversarial: fake results / untrusted by default / governed writes ────
def t_adv_worker_result_untrusted_by_default():
    r = WorkerResult(task="x", worker="codex", ending_state="done", tests_passed=99)
    assert r.reviewed is False and r.certified is False, "'done' is never trusted without review+tests"


def t_adv_fabricated_test_claim_not_certified():
    # a worker CLAIMS passing tests but ran none (fabricated evidence) → never certified
    r = WorkerResult(task="x", worker="codex", tests_run=0, tests_passed=50, tests_failed=0)
    certify_worker_result(r, reviewed_by="claude-code", tests_ok=True)
    assert r.certified is False, "a fabricated test claim (0 run) must not certify"


def t_adv_git_writes_are_governed_action_classes():
    # a worker trying to push/merge/change protection maps to gated/forbidden classes (§14/§26)
    assert coding_action_class("push") == ActionClass.HIGH_IMPACT
    assert coding_action_class("merge") == ActionClass.DESTRUCTIVE
    assert coding_action_class("branch_protection") == ActionClass.PROHIBITED


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
