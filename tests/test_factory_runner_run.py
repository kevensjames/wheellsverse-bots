# tests/test_factory_runner_run.py
import sys
from pathlib import Path

import pytest
from core.portfolio.actions import Action, ActionClass
from factory import runner

FAKE = str(Path(__file__).parent / "fixtures" / "fake_claude.py")


def _action(verb="implement", agent="engineer"):
    return Action(verb=verb, agent=agent, action_class=ActionClass.GREEN,
                  preconditions=[], business="acme",
                  payload={"task": {"id": "t1", "title": "add health endpoint"},
                           "cycle_id": "c1"})


def test_agent_work_success(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE} success")
    out = r.run(_action())
    assert out["ok"] is True
    assert out["cost_usd"] == 0.01
    assert out["pr_url"] is None


def test_agent_work_error_is_not_ok(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE} error")
    out = r.run(_action())
    assert out["ok"] is False


def test_agent_work_timeout_is_not_ok(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE} hang", timeout_s=1)
    out = r.run(_action())
    assert out["ok"] is False
    assert "timeout" in out["output"].lower()


def test_unknown_role_is_not_ok(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE} success")
    out = r.run(_action(agent="nonexistent"))
    assert out["ok"] is False


def test_gate_verbs_not_implemented_in_f2a(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE} success")
    for verb in ("build", "security", "commit_pr"):
        with pytest.raises(NotImplementedError):
            r.run(_action(verb=verb, agent="daemon"))


def test_report_verb_is_noop_ok(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE} success")
    out = r.run(_action(verb="report", agent="writer"))
    assert out["ok"] is True and out["cost_usd"] == 0.0
