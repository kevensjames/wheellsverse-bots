"""push.py — guard unit tests (no git) + real-git integration (skipped w/o git).
Proves branch-only, CI-path rejection, no-ambient-credential, and a real push to
a review branch that never touches the default branch."""
import pathlib
import subprocess

import pytest

from app.services.swe_runtime import push
from app.services.swe_runtime.policy import PolicyDenied
from app.services.swe_runtime.push import PushError

_MODIFY_PATCH = (
    "--- a/lib.py\n+++ b/lib.py\n@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n-    return a - b\n+    return a + b\n"
)


# ── Guard unit tests (no git needed) ─────────────────────────────────────────
def test_patch_touches_ci():
    assert push._patch_touches_ci("--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n")
    assert push._patch_touches_ci("+++ b/.gitlab-ci.yml\n")
    assert push._patch_touches_ci("+++ b/.git/hooks/pre-commit\n")
    assert not push._patch_touches_ci("--- a/src/lib.py\n+++ b/src/lib.py\n")


def test_review_branch_for():
    assert push.review_branch_for("abc123") == "kai/swe/abc123"
    for bad in ["../main", "-x", ".hidden", "a b", "a~b", "", "a/b"]:
        with pytest.raises(PolicyDenied):
            push.review_branch_for(bad)


def test_https_push_url_normalizes_and_refuses_insecure():
    assert push._https_push_url("git@github.com:o/r.git") == "https://x-access-token@github.com/o/r.git"
    assert push._https_push_url("https://github.com/o/r.git") == "https://x-access-token@github.com/o/r.git"
    assert push._https_push_url("https://old:tok@github.com/o/r.git") == "https://x-access-token@github.com/o/r.git"
    for bad in ["http://github.com/o/r.git", "ssh://git@github.com/o/r.git"]:
        with pytest.raises(PolicyDenied):
            push._https_push_url(bad)


def test_resolve_credential(monkeypatch):
    monkeypatch.delenv("KAI_SWE_PUSH_TOKEN", raising=False)
    assert push.resolve_push_credential() is None
    monkeypatch.setenv("KAI_SWE_PUSH_TOKEN", "ghp_x")
    assert push.resolve_push_credential() == "ghp_x"


def test_protected_default(monkeypatch):
    monkeypatch.delenv("KAI_SWE_PROTECTED_BRANCHES", raising=False)
    p = push._protected_branches()
    assert {"main", "istanbul", "master"} <= p


def test_redact_remote_strips_userinfo():
    assert push._redact_remote(
        "https://x-access-token:tok@github.com/o/r.git") == "https://github.com/o/r.git"


def test_protected_task_id_refused_before_fs():
    # task_id 'main' is protected → refused before touching the filesystem.
    with pytest.raises(PolicyDenied):
        push.apply_and_push(source_dir="/nonexistent", task_id="main", patch="x", actor="op")


def test_empty_patch_refused():
    with pytest.raises(PolicyDenied):
        push.apply_and_push(source_dir="/nonexistent", task_id="t1", patch="   ", actor="op")


def test_ci_patch_refused_before_fs():
    ci = "--- a/.github/workflows/x.yml\n+++ b/.github/workflows/x.yml\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(PolicyDenied):
        push.apply_and_push(source_dir="/nonexistent", task_id="t1", patch=ci, actor="op")


# ── Real-git integration ─────────────────────────────────────────────────────
def _has_git():
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except Exception:
        return False


needs_git = pytest.mark.skipif(not _has_git(), reason="git not available")


def _g(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repos(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True)
    (work / "lib.py").write_text("def add(a, b):\n    return a - b\n")
    _g(str(work), "add", "-A")
    _g(str(work), "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    branch = _g(str(work), "rev-parse", "--abbrev-ref", "HEAD")
    _g(str(work), "push", "-q", "origin", branch)
    return {"bare": str(bare), "work": str(work), "branch": branch}


def _bare_refs(bare):
    return subprocess.run(["git", "-C", bare, "for-each-ref", "--format=%(refname:short)"],
                          capture_output=True, text=True).stdout


@needs_git
def test_apply_and_push_creates_review_branch_not_default(repos):
    before = _g(repos["bare"], "rev-parse", repos["branch"])
    info = push.apply_and_push(source_dir=repos["work"], task_id="t1",
                               patch=_MODIFY_PATCH, actor="op")
    assert info["review_branch"] == "kai/swe/t1"
    refs = _bare_refs(repos["bare"])
    assert "kai/swe/t1" in refs
    # the review branch carries the change...
    assert "a + b" in _g(repos["bare"], "show", "kai/swe/t1:lib.py")
    # ...and the DEFAULT branch is byte-for-byte untouched (no force, no move).
    assert _g(repos["bare"], "rev-parse", repos["branch"]) == before
    assert "a - b" in _g(repos["bare"], "show", f"{repos['branch']}:lib.py")


@needs_git
def test_dirty_source_refused(repos):
    (pathlib.Path(repos["work"]) / "lib.py").write_text("uncommitted\n")
    with pytest.raises(PolicyDenied):
        push.apply_and_push(source_dir=repos["work"], task_id="t1",
                            patch=_MODIFY_PATCH, actor="op")


@needs_git
def test_ci_quoted_path_bypass_blocked(repos):
    # A hand-crafted patch with a C-quoted non-ASCII CI path slips past the
    # raw-text pre-check, but the authoritative post-apply guard must catch it.
    quoted = (
        'diff --git "a/.github/workflows/\\303\\251.yml" "b/.github/workflows/\\303\\251.yml"\n'
        "new file mode 100644\n"
        "--- /dev/null\n"
        '+++ "b/.github/workflows/\\303\\251.yml"\n'
        "@@ -0,0 +1 @@\n"
        "+on: push\n"
    )
    assert not push._patch_touches_ci(quoted)        # raw-text pre-check misses it
    with pytest.raises(PolicyDenied):                 # post-apply guard catches it
        push.apply_and_push(source_dir=repos["work"], task_id="t1", patch=quoted, actor="op")
    assert "kai/swe/t1" not in _bare_refs(repos["bare"])   # nothing pushed


@needs_git
def test_ci_rename_bypass_blocked(repos):
    # A pure rename of an existing base file into .github/workflows/ has no
    # +++/--- lines, so the raw-text pre-check misses it — the post-apply guard
    # (on git's own affected paths, --find-renames) must catch it.
    (pathlib.Path(repos["work"]) / "buildscript.yml").write_text("on: push\n")
    _g(repos["work"], "add", "-A")
    _g(repos["work"], "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "-m", "add build")
    _g(repos["work"], "push", "-q", "origin", repos["branch"])
    rename = (
        "diff --git a/buildscript.yml b/.github/workflows/ci.yml\n"
        "similarity index 100%\n"
        "rename from buildscript.yml\n"
        "rename to .github/workflows/ci.yml\n"
    )
    assert not push._patch_touches_ci(rename)         # raw-text pre-check misses it
    with pytest.raises(PolicyDenied):
        push.apply_and_push(source_dir=repos["work"], task_id="t1", patch=rename, actor="op")
    assert "kai/swe/t1" not in _bare_refs(repos["bare"])


@needs_git
def test_remote_host_without_token_refuses_no_ambient(repos, monkeypatch):
    # Point origin at a remote host and provide NO token → refuse (never fall
    # back to an ambient credential / ssh key). Guard fires before any network.
    _g(repos["work"], "remote", "set-url", "origin", "https://github.com/example/repo.git")
    monkeypatch.delenv("KAI_SWE_PUSH_TOKEN", raising=False)
    with pytest.raises(PolicyDenied):
        push.apply_and_push(source_dir=repos["work"], task_id="t1",
                            patch=_MODIFY_PATCH, actor="op")
