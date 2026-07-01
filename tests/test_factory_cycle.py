import subprocess
import pytest
from factory import cycle, worktree, state, project as P, paths


def _run(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


class _MockRunner:
    def __init__(self, wt):
        self.wt = wt
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://gh/pr/1" if action.verb == "commit_pr" else None}


def _project_with_repo(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("i\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "i", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    P.upsert_project(P.Project(slug="acme", name="acme", repo_url=str(remote)))
    state.save_backlog("acme", [{"id": "t1", "title": "x", "priority": 1, "status": "pending",
                                 "depends_on": [], "source": "seed", "cycle_id": None}])
    return remote


def test_run_with_worktree_provisions_runs_and_cleans_up(tmp_path):
    _project_with_repo(tmp_path)
    res = cycle.run_with_worktree("acme", now_iso="2026-07-01T02:00:00Z",
                                  make_runner=lambda wt: _MockRunner(wt))
    assert res.status == "completed"
    assert state.load_backlog("acme")[0]["status"] == "done"
    # worktree cleaned up
    leftover = list((paths.worktrees_root() / "acme").glob("*")) if (paths.worktrees_root() / "acme").exists() else []
    assert leftover == []


def test_run_with_worktree_idle_when_no_task(tmp_path):
    _project_with_repo(tmp_path)
    state.save_backlog("acme", [])  # nothing ready
    res = cycle.run_with_worktree("acme", now_iso="2026-07-01T02:00:00Z",
                                  make_runner=lambda wt: _MockRunner(wt))
    assert res.status in ("idle", "done")
    # no worktree provisioned
    assert not (paths.worktrees_root() / "acme").exists() or \
           list((paths.worktrees_root() / "acme").glob("*")) == []


def test_run_with_worktree_cleans_up_on_exception(tmp_path):
    _project_with_repo(tmp_path)
    def _boom(wt):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        cycle.run_with_worktree("acme", now_iso="2026-07-01T02:00:00Z", make_runner=_boom)
    root = paths.worktrees_root() / "acme"
    leftover = list(root.glob("*")) if root.exists() else []
    assert leftover == []  # finally cleaned the worktree even though make_runner raised


def test_run_with_worktree_no_divergence_with_orphan(tmp_path):
    _project_with_repo(tmp_path)  # seeds task t1 pending
    # simulate a crashed prior cycle: t1 left in_progress with a stale cycle_id
    state.save_backlog("acme", [{"id": "t1", "title": "x", "priority": 1,
                                 "status": "in_progress", "depends_on": [], "source": "seed",
                                 "cycle_id": "DEAD"}])
    res = cycle.run_with_worktree("acme", now_iso="2026-07-01T02:00:00Z",
                                  make_runner=lambda wt: _MockRunner(wt))
    # t1 is reclaimed to pending, claimed, and really processed on its worktree branch
    assert res.status == "completed" and res.task_id == "t1"
    assert state.load_backlog("acme")[0]["status"] == "done"
