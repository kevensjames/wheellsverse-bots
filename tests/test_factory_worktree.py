# tests/test_factory_worktree.py
import subprocess
from pathlib import Path

import pytest
from factory import worktree, paths


def _run(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _bare_remote(tmp_path) -> Path:
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    # seed the remote with one commit via a scratch clone
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("init\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    return remote


def test_branch_name():
    assert worktree.branch_name("acme", "t1") == "factory/acme/t1"


def test_ensure_clone_is_idempotent(tmp_path):
    remote = _bare_remote(tmp_path)
    p1 = worktree.ensure_clone("acme", str(remote))
    assert p1 == paths.workspaces_root() / "acme"
    assert (p1 / "README.md").exists()
    p2 = worktree.ensure_clone("acme", str(remote))  # second call: no error, same path
    assert p2 == p1


def test_prepare_creates_worktree_on_factory_branch(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    wt = worktree.prepare("acme", "c1", "t1", clone_path=clone)
    assert wt.exists() and (wt / "README.md").exists()
    head = _run("git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head == "factory/acme/t1"


def test_cleanup_removes_worktree(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    wt = worktree.prepare("acme", "c1", "t1", clone_path=clone)
    worktree.cleanup("acme", "c1", clone_path=clone)
    assert not wt.exists()
    worktree.cleanup("acme", "c1", clone_path=clone)  # idempotent: no raise


def test_safe_push_rejects_non_factory_branch(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    with pytest.raises(worktree.PushRejected):
        worktree.safe_push(clone, "acme", "main")
    with pytest.raises(worktree.PushRejected):
        worktree.safe_push(clone, "acme", "factory/other/t1")  # wrong slug


def test_safe_push_allows_and_pushes_factory_branch(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    worktree.prepare("acme", "c1", "t1", clone_path=clone)
    # make a commit on the factory branch inside the clone's worktree checkout
    wt = paths.worktrees_root() / "acme" / "c1"
    (wt / "f.txt").write_text("x\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(wt), "add", ".")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(wt), "commit", "-m", "add f")
    # push the branch from the worktree
    worktree.safe_push(wt, "acme", "factory/acme/t1")
    branches = _run("git", "--git-dir", str(remote), "branch", "--list", "factory/acme/t1").stdout
    assert "factory/acme/t1" in branches
