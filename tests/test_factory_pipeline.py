import pytest
from core.portfolio.actions import ActionClass
from factory import pipeline, state, project as P, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


class MockRunner:
    """Scripted AgentAdapter. script maps verb -> dict overrides."""
    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []

    def run(self, action):
        self.calls.append(action.verb)
        spec = self.script.get(action.verb, {})
        return {
            "ok": spec.get("ok", True),
            "cost_usd": spec.get("cost_usd", 0.0),
            "output": spec.get("output", ""),
            "pr_url": spec.get("pr_url"),
        }


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "do thing", "priority": 1,
                               "status": "pending", "depends_on": [], "source": "seed",
                               "cycle_id": None}])


def test_pipeline_encodes_safety_classes():
    by_verb = {s.verb: s for s in pipeline.PIPELINE}
    assert by_verb["deploy_staging"].action_class is ActionClass.AMBER
    assert by_verb["deploy_prod"].action_class is ActionClass.RED


def test_happy_path_completes_and_opens_pr():
    _seed()
    runner = MockRunner({"commit_pr": {"pr_url": "https://gh/pr/1"}})
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "completed"
    assert res.pr_url == "https://gh/pr/1"
    assert state.load_backlog("a")[0]["status"] == "done"


def test_amber_deploy_is_queued_not_run():
    _seed()
    runner = MockRunner()
    pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert "deploy_staging" not in runner.calls          # AMBER never reaches adapter
    approvals = paths.read_jsonl(paths.data_root() / "approvals.jsonl")
    assert any(r["verb"] == "deploy_staging" for r in approvals)


def test_red_deploy_is_refused_not_run():
    _seed()
    runner = MockRunner()
    pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert "deploy_prod" not in runner.calls
    approvals = paths.read_jsonl(paths.data_root() / "approvals.jsonl")
    assert not any(r["verb"] == "deploy_prod" for r in approvals)  # RED isn't even queued


def test_security_hard_gate_blocks_task():
    _seed()
    runner = MockRunner({"security": {"ok": False}})
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "blocked"
    assert "commit_pr" not in runner.calls               # gate stops before PR
    assert state.load_backlog("a")[0]["status"] == "blocked"
    assert P.get_project("a").consecutive_failures == 1


def test_idle_when_no_ready_task():
    P.upsert_project(P.Project(slug="a", name="a", repo_url="x"))
    state.save_backlog("a", [])
    res = pipeline.run_cycle("a", MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert res.status == "idle"


def test_done_when_roadmap_complete_and_no_tasks():
    P.upsert_project(P.Project(slug="a", name="a", repo_url="x"))
    state.save_backlog("a", [])
    state.save_roadmap("a", {"milestones": [{"id": "m1", "title": "x",
                                             "status": "done", "features": []}]})
    res = pipeline.run_cycle("a", MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert res.status == "done"
    assert P.get_project("a").phase == "done"


class _BadOutputRunner:
    """Returns malformed output for the security hard-gate stage."""
    def __init__(self, bad):
        self.bad = bad
        self.calls = []

    def run(self, action):
        self.calls.append(action.verb)
        if action.verb == "security":
            return self.bad           # None or a dict missing "ok"
        return {"ok": True, "cost_usd": 0.0, "output": "", "pr_url":
                "https://gh/pr/1" if action.verb == "commit_pr" else None}


def test_hard_gate_fails_closed_on_none_output():
    _seed()
    runner = _BadOutputRunner(None)
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "blocked"
    assert "commit_pr" not in runner.calls


def test_hard_gate_fails_closed_on_missing_ok_key():
    _seed()
    runner = _BadOutputRunner({"cost_usd": 0.0, "output": "scan crashed"})
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "blocked"
    assert "commit_pr" not in runner.calls


def test_orphaned_in_progress_task_is_reclaimed_and_processed():
    P.upsert_project(P.Project(slug="a", name="a", repo_url="x"))
    state.save_backlog("a", [{"id": "t1", "title": "x", "priority": 1,
                              "status": "in_progress", "depends_on": [], "source": "seed",
                              "cycle_id": "DEAD-CYCLE"}])
    runner = MockRunner({"commit_pr": {"pr_url": "https://gh/pr/1"}})
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "completed"
    assert state.load_backlog("a")[0]["status"] == "done"


def test_hard_gate_fails_closed_on_non_dict_output():
    _seed()
    class _NonDictRunner:
        def __init__(self):
            self.calls = []
        def run(self, action):
            self.calls.append(action.verb)
            if action.verb == "security":
                return "done"  # non-dict truthy output
            return {"ok": True, "cost_usd": 0.0, "output": "",
                    "pr_url": "https://gh/pr/1" if action.verb == "commit_pr" else None}
    runner = _NonDictRunner()
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "blocked"
    assert "commit_pr" not in runner.calls
    assert P.get_project("a").consecutive_failures == 1
    assert state.load_backlog("a")[0]["status"] == "blocked"


def test_budget_overrun_queues_and_releases_task():
    _seed()
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 1, "portfolio_month": 1}})
    from factory import budget
    budget.record_spend("a", 5.0, "prior", "2026-06")    # already over ceiling
    res = pipeline.run_cycle("a", MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert res.status == "budget_queued"
    assert state.load_backlog("a")[0]["status"] == "pending"   # released
