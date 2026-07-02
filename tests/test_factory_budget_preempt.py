import pytest
from factory import pipeline, state, budget, project as P, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


class _OkRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://gh/pr/1" if action.verb == "commit_pr" else None}


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1, "status": "pending",
                               "depends_on": [], "source": "seed", "cycle_id": None}])


def test_budget_gate_preempts_using_estimated_stage_cost():
    _seed()
    # ceiling below the first architect stage's estimated cost (opus ~1.0) so the
    # gate must PRE-EMPT (queue) before running the stage, with zero prior spend.
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 0.5, "portfolio_month": 100}})
    res = pipeline.run_cycle("a", _OkRunner(), now_iso="2026-07-01T02:00:00Z")
    assert res.status == "budget_queued"
    # task released back to pending (not left in_progress)
    assert state.load_backlog("a")[0]["status"] == "pending"


def test_budget_gate_allows_when_ceiling_covers_estimate():
    _seed()
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 1000, "portfolio_month": 1000}})
    res = pipeline.run_cycle("a", _OkRunner(), now_iso="2026-07-01T02:00:00Z")
    assert res.status == "completed"
