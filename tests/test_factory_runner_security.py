import subprocess
import pytest
from core.portfolio.actions import Action, ActionClass
from factory import runner, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _repo(tmp_path):
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True, check=True)
    return tmp_path


def _action(verb="security", agent="security"):
    return Action(verb=verb, agent=agent, action_class=ActionClass.GREEN, preconditions=[],
                  business="acme", payload={"task": {"id": "t1", "title": "x"}, "cycle_id": "c1"})


def test_security_clean_ok_and_no_issue(tmp_path):
    wt = _repo(tmp_path / "wt")
    (wt / "ok.py").write_text("x = 1\n")
    r = runner.ClaudeCliRunner(wt)
    out = r.run(_action())
    assert out["ok"] is True and out["pr_url"] is None
    assert not (paths.project_dir("acme") / "known_issues.jsonl").exists()


@pytest.mark.skipif(__import__("shutil").which("gitleaks") is None, reason="gitleaks not installed")
def test_security_leak_blocks_and_records_issue(tmp_path):
    wt = _repo(tmp_path / "wt")
    (wt / "leak.py").write_text('aws_secret_access_key = "k3n29cXx9b1ZQm7U+mLwNr6yT4oKhDf8JsVpAeRi"\n')
    r = runner.ClaudeCliRunner(wt)
    out = r.run(_action())
    assert out["ok"] is False
    issues = paths.read_jsonl(paths.project_dir("acme") / "known_issues.jsonl")
    assert len(issues) == 1 and issues[0]["kind"] == "security" and issues[0]["findings"] >= 1
