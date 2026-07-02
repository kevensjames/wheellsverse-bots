# tests/test_factory_integration.py
import pytest
from factory import scheduler, project as P, state, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    monkeypatch.delenv("FACTORY_KILL", raising=False)


class MockRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.01, "output": "",
                "pr_url": "https://gh/pr/42" if action.verb == "commit_pr" else None}


def test_end_to_end_nightly_sweep():
    P.upsert_project(P.Project(slug="hello", name="Hello Service", repo_url="x"))
    state.save_backlog("hello", [{"id": "t1", "title": "scaffold", "priority": 1,
                                  "status": "pending", "depends_on": [], "source": "seed",
                                  "cycle_id": None}])

    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")

    assert out == {"status": "ran", "ticked": {"hello": "completed"}}
    assert state.load_backlog("hello")[0]["status"] == "done"
    cycles = paths.read_jsonl(paths.project_dir("hello") / "cycles.jsonl")
    assert cycles[-1]["pr_url"] == "https://gh/pr/42"
    assert (paths.project_dir("hello") / "reports" / "2026-06-30.md").exists()
    # spend recorded, audit written
    assert paths.read_jsonl(paths.data_root() / "audit.jsonl")
    assert paths.read_jsonl(paths.data_root() / "spend.jsonl")
