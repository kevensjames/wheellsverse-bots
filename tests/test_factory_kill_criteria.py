import pytest
from factory import pipeline, state, project as P


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


class _AlwaysBlocksRunner:
    """Fails the security hard-gate every cycle so the task always blocks."""
    def run(self, action):
        ok = not (action.verb == "security")
        return {"ok": ok, "cost_usd": 0.0, "output": "", "pr_url": None}


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1, "status": "pending",
                               "depends_on": [], "source": "seed", "cycle_id": None}])


def test_requeue_oldest_blocked_resets_first_blocked():
    state.save_backlog("a", [
        {"id": "t1", "title": "x", "priority": 1, "status": "blocked", "depends_on": [],
         "source": "s", "cycle_id": "c0"},
        {"id": "t2", "title": "y", "priority": 1, "status": "blocked", "depends_on": [],
         "source": "s", "cycle_id": "c0"},
    ])
    assert state.requeue_oldest_blocked("a") == "t1"
    tasks = {t["id"]: t for t in state.load_backlog("a")}
    assert tasks["t1"]["status"] == "pending" and tasks["t1"]["cycle_id"] is None
    assert tasks["t2"]["status"] == "blocked"  # only the first is requeued


def test_requeue_none_when_no_blocked():
    state.save_backlog("a", [{"id": "t1", "title": "x", "priority": 1, "status": "done",
                              "depends_on": [], "source": "s", "cycle_id": None}])
    assert state.requeue_oldest_blocked("a") is None


def test_persistent_failure_escalates_to_blocked_red():
    _seed()
    runner = _AlwaysBlocksRunner()
    # cycle 1: t1 pending -> claimed -> blocks (failures=1)
    assert pipeline.run_cycle("a", runner, now_iso="2026-07-01T02:00:00Z").status == "blocked"
    assert P.get_project("a").consecutive_failures == 1
    # cycles 2 and 3: blocked t1 is requeued and retried -> blocks again (failures 2, 3)
    assert pipeline.run_cycle("a", runner, now_iso="2026-07-02T02:00:00Z").status == "blocked"
    assert pipeline.run_cycle("a", runner, now_iso="2026-07-03T02:00:00Z").status == "blocked"
    assert P.get_project("a").phase == "blocked_red"
    assert "a" not in [p.slug for p in P.list_active()]  # excluded from ticking
