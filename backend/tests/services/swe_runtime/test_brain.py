"""DefaultBrain + Budget — bounded loop, host-side diff, no-exec guarantee.
Pure unit tests with a fake AgentRuntime (no Docker, no DB)."""
import pathlib

import pytest

from app.services.swe_runtime.brain import DefaultBrain, Mission, Step
from app.services.swe_runtime.budget import Budget, BudgetBreach
from app.services.swe_runtime.sandbox import SandboxResult


class FakeRuntime:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_task(self, task):
        self.calls.append(task)
        return self.result


def _mission(src, commands, budget=None):
    return Mission(task_id="t1", source_dir=str(src), goal="fix",
                   commands=list(commands), budget=budget or Budget.default())


# ── Budget ───────────────────────────────────────────────────────────────────
def test_budget_check_raises_at_max_steps():
    b = Budget(max_steps=2)
    b.tick_step(); b.tick_step()
    with pytest.raises(BudgetBreach):
        b.check()


def test_budget_check_raises_on_tokens_and_cost():
    b = Budget(max_tokens=10); b.charge_tokens(11)
    with pytest.raises(BudgetBreach):
        b.check()
    b2 = Budget(max_cost_usd=0.5); b2.charge_cost(0.6)
    with pytest.raises(BudgetBreach):
        b2.check()


# ── plan ─────────────────────────────────────────────────────────────────────
def test_plan_wraps_commands_into_steps(tmp_path):
    steps = DefaultBrain().plan(_mission(tmp_path, ["echo a", "echo b"]))
    assert [s.command for s in steps] == ["echo a", "echo b"]
    assert steps[0].n == 1 and steps[1].n == 2


# ── execute ──────────────────────────────────────────────────────────────────
def test_execute_produces_patch(tmp_path):
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a - b\n")
    m = _mission(tmp_path, ["sed -i 's/a - b/a + b/' lib.py"])
    plan = DefaultBrain().plan(m)
    fake = FakeRuntime(SandboxResult(0, "", "",
                       artifacts={"lib.py": "def add(a, b):\n    return a + b\n"}))
    r = DefaultBrain().execute(m, plan, fake)
    assert r.status == "awaiting_push_approval"
    assert r.patch.startswith("--- a/lib.py") and "a + b" in r.patch
    assert len(fake.calls) == 1                          # exactly one composed run
    assert fake.calls[0].command.startswith("set -e")    # composed script


def test_execute_no_changes_fails(tmp_path):
    (tmp_path / "lib.py").write_text("same\n")
    m = _mission(tmp_path, ["true"])
    fake = FakeRuntime(SandboxResult(0, "", "", artifacts={"lib.py": "same\n"}))
    r = DefaultBrain().execute(m, DefaultBrain().plan(m), fake)
    assert r.status == "failed" and "no changes" in r.error


def test_execute_nonzero_exit_fails(tmp_path):
    m = _mission(tmp_path, ["false"])
    fake = FakeRuntime(SandboxResult(1, "", "boom", artifacts={}))
    r = DefaultBrain().execute(m, DefaultBrain().plan(m), fake)
    assert r.status == "failed" and "exited 1" in r.error


def test_execute_disabled_sandbox_fails(tmp_path):
    m = _mission(tmp_path, ["echo hi"])
    fake = FakeRuntime(SandboxResult(-1, "", "", disabled=True))
    r = DefaultBrain().execute(m, DefaultBrain().plan(m), fake)
    assert r.status == "failed" and "disabled" in r.error


def test_execute_plan_too_long_fails(tmp_path):
    m = _mission(tmp_path, [], budget=Budget(max_steps=1))
    plan = [Step(1, "echo a", "r"), Step(2, "echo b", "r")]
    fake = FakeRuntime(SandboxResult(0, "", ""))
    r = DefaultBrain().execute(m, plan, fake)
    assert r.status == "failed" and "max_steps" in r.error
    assert fake.calls == []                              # never ran the sandbox


def test_execute_policy_denied_step_fails(tmp_path):
    m = _mission(tmp_path, [])
    plan = [Step(1, "curl http://evil", "r")]
    fake = FakeRuntime(SandboxResult(0, "", ""))
    r = DefaultBrain().execute(m, plan, fake)
    assert r.status == "failed" and "policy" in r.error
    assert fake.calls == []                              # denied before running


def test_brain_reaches_world_only_through_runtime():
    # The brain must have no shell/exec path of its own — only runtime.run_task.
    import app.services.swe_runtime.brain as brain_mod
    text = pathlib.Path(brain_mod.__file__).read_text()
    for forbidden in ("import subprocess", "subprocess.", "os.system(", "os.popen(", "os.exec"):
        assert forbidden not in text, forbidden
