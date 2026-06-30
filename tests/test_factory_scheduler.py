import pytest
from factory import scheduler, project as P, state, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("FACTORY_ENABLED", raising=False)
    monkeypatch.delenv("FACTORY_KILL", raising=False)


class MockRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://gh/pr/1" if action.verb == "commit_pr" else None}


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1,
                               "status": "pending", "depends_on": [], "source": "seed",
                               "cycle_id": None}])


def test_dormant_by_default():
    _seed()
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "dormant" and out["ticked"] == {}


def test_kill_halts_even_if_enabled(monkeypatch):
    _seed()
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    monkeypatch.setenv("FACTORY_KILL", "1")
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "killed"


def test_enabled_ticks_active_projects_and_writes_report(monkeypatch):
    _seed()
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "ran"
    assert out["ticked"] == {"a": "completed"}
    assert (paths.project_dir("a") / "reports" / "2026-06-30.md").exists()


def test_set_enabled_via_control_file():
    _seed()
    scheduler.set_enabled(True)
    assert scheduler.is_enabled() is True
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "ran"


def test_only_active_projects_ticked(monkeypatch):
    _seed("a")
    P.upsert_project(P.Project(slug="b", name="b", repo_url="x", phase="dormant"))
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert "b" not in out["ticked"]
