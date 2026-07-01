# tests/test_factory_pr.py
import os
import subprocess
import sys
from pathlib import Path

import pytest
from factory import pr, worktree, paths

FAKE_GH = str(Path(__file__).parent / "fixtures" / "fake_gh.py")


def _run(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _clone_with_worktree(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("init\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    clone = worktree.ensure_clone("acme", str(remote))
    wt = worktree.prepare("acme", "c1", "t1", clone_path=clone)
    return remote, wt


def test_open_pr_commits_pushes_and_returns_url(tmp_path):
    remote, wt = _clone_with_worktree(tmp_path)
    (wt / "feature.py").write_text("def f():\n    return 1\n")
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "add feature"},
                     gh_bin=f"{sys.executable} {FAKE_GH}")
    assert url == "https://example.invalid/acme/pull/1"
    branches = _run("git", "--git-dir", str(remote), "branch", "--list", "factory/acme/t1").stdout
    assert "factory/acme/t1" in branches


def test_open_pr_no_changes_returns_none(tmp_path):
    remote, wt = _clone_with_worktree(tmp_path)
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "noop"},
                     gh_bin=f"{sys.executable} {FAKE_GH}")
    assert url is None


def test_open_pr_gh_failure_is_fail_soft(tmp_path):
    remote, wt = _clone_with_worktree(tmp_path)
    (wt / "feature.py").write_text("x=1\n")
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "add"},
                     gh_bin=f"{sys.executable} {FAKE_GH} fail")
    assert url is None  # branch still pushed, but no PR url
    branches = _run("git", "--git-dir", str(remote), "branch", "--list", "factory/acme/t1").stdout
    assert "factory/acme/t1" in branches
