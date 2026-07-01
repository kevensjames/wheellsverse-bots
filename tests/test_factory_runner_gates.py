# tests/test_factory_runner_gates.py
import subprocess
import sys
from pathlib import Path

import pytest
from core.portfolio.actions import Action, ActionClass
from factory import runner, worktree, paths

FAKE_GH = str(Path(__file__).parent / "fixtures" / "fake_gh.py")


def _run(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _action(verb, agent="daemon"):
    return Action(verb=verb, agent=agent, action_class=ActionClass.GREEN,
                  preconditions=[], business="acme",
                  payload={"task": {"id": "t1", "title": "add feature"}, "cycle_id": "c1"})


def _worktree(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("init\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    clone = worktree.ensure_clone("acme", str(remote))
    return worktree.prepare("acme", "c1", "t1", clone_path=clone)


def test_build_verb_runs_pytest(tmp_path):
    wt = _worktree(tmp_path)
    (wt / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    r = runner.ClaudeCliRunner(wt, build_cmd="python -m pytest -q")
    out = r.run(_action("build"))
    assert out["ok"] is True and out["pr_url"] is None


def test_build_verb_fails_on_red(tmp_path):
    wt = _worktree(tmp_path)
    (wt / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    r = runner.ClaudeCliRunner(wt)
    assert r.run(_action("build"))["ok"] is False


def test_commit_pr_verb_opens_pr(tmp_path):
    wt = _worktree(tmp_path)
    (wt / "feature.py").write_text("def f():\n    return 1\n")
    r = runner.ClaudeCliRunner(wt, gh_bin=f"{sys.executable} {FAKE_GH}")
    out = r.run(_action("commit_pr", agent="git"))
    assert out["ok"] is True
    assert out["pr_url"] == "https://example.invalid/acme/pull/1"
