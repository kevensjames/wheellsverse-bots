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


def _wt(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("i\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "i", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    clone = worktree.ensure_clone("acme", str(remote))
    return worktree.prepare("acme", "c1", "t1", clone_path=clone)


def test_open_pr_recovers_existing_pr_url(tmp_path):
    wt = _wt(tmp_path)
    (wt / "f.py").write_text("x=1\n")
    # 'exists' mode: `pr create` fails 'already exists', `pr view` returns the url
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "add"},
                     gh_bin=f"{sys.executable} {FAKE_GH} exists")
    assert url == "https://example.invalid/acme/pull/7"
