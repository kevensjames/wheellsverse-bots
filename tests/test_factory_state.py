import pytest
from core.portfolio.actions import Action, ActionClass
from factory import state, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def _task(tid, prio=1, status="pending", deps=None):
    return {"id": tid, "title": tid, "priority": prio, "status": status,
            "depends_on": deps or [], "source": "seed", "cycle_id": None}


def test_backlog_roundtrip():
    state.save_backlog("a", [_task("t1")])
    assert state.load_backlog("a")[0]["id"] == "t1"


def test_next_ready_task_picks_lowest_priority():
    state.save_backlog("a", [_task("t2", prio=2), _task("t1", prio=1)])
    assert state.next_ready_task("a")["id"] == "t1"


def test_next_ready_task_respects_unmet_deps():
    state.save_backlog("a", [_task("t1", deps=["t0"]), _task("t0")])
    # t1 depends on t0 (still pending) -> t0 is the only ready one
    assert state.next_ready_task("a")["id"] == "t0"


def test_next_ready_task_allows_met_deps():
    state.save_backlog("a", [_task("t1", prio=1, deps=["t0"]),
                             _task("t0", prio=9, status="done")])
    assert state.next_ready_task("a")["id"] == "t1"


def test_next_ready_task_none_when_empty():
    state.save_backlog("a", [_task("t0", status="done")])
    assert state.next_ready_task("a") is None


def test_claim_task_is_compare_and_set():
    state.save_backlog("a", [_task("t1")])
    assert state.claim_task("a", "t1", "c1") is True
    # second claim fails — already in_progress
    assert state.claim_task("a", "t1", "c2") is False
    t = state.load_backlog("a")[0]
    assert t["status"] == "in_progress" and t["cycle_id"] == "c1"


def test_complete_block_release_transitions():
    state.save_backlog("a", [_task("t1")])
    state.claim_task("a", "t1", "c1")
    state.complete_task("a", "t1")
    assert state.load_backlog("a")[0]["status"] == "done"

    state.save_backlog("a", [_task("t2")])
    state.claim_task("a", "t2", "c2")
    state.release_task("a", "t2")
    rel = state.load_backlog("a")[0]
    assert rel["status"] == "pending" and rel["cycle_id"] is None


def test_roadmap_complete():
    assert state.roadmap_complete("a") is False  # no milestones
    state.save_roadmap("a", {"milestones": [{"id": "m1", "title": "x",
                                             "status": "done", "features": []}]})
    assert state.roadmap_complete("a") is True


def test_reclaim_orphans_resets_stale_in_progress():
    state.save_backlog("a", [
        {"id": "t1", "title": "x", "priority": 1, "status": "in_progress",
         "depends_on": [], "source": "s", "cycle_id": "OLD"},
        {"id": "t2", "title": "y", "priority": 1, "status": "done",
         "depends_on": [], "source": "s", "cycle_id": "OLD"},
    ])
    reclaimed = state.reclaim_orphans("a", "NEW")
    assert reclaimed == ["t1"]
    tasks = {t["id"]: t for t in state.load_backlog("a")}
    assert tasks["t1"]["status"] == "pending" and tasks["t1"]["cycle_id"] is None
    assert tasks["t2"]["status"] == "done"


def test_audit_and_approval_stamp_now_iso():
    state.audit({"verb": "x", "status": "ran"}, now_iso="2026-06-30T02:00:00Z")
    rows = paths.read_jsonl(paths.data_root() / "audit.jsonl")
    assert rows[0]["at"] == "2026-06-30T02:00:00Z"

    a = Action("deploy", "devops", ActionClass.AMBER, [], "a", {})
    aid = state.queue_approval(a, now_iso="2026-06-30T02:00:00Z")
    qrows = paths.read_jsonl(paths.data_root() / "approvals.jsonl")
    assert len(aid) == 12 and qrows[0]["status"] == "pending"
