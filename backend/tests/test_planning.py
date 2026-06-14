"""Planning module tests — storage CRUD + branch schema, planner goal→steps
parsing, executor state machine (advance / fail→block / goto routing),
revision proposal, plan_query tool, and admin endpoint auth/scope gates.

Mirrors the test conventions of test_kg.py / test_self_correction.py:
  - isolated per-test SQLite db via monkeypatch of PLANNING_DB_PATH
  - fake router (SimpleNamespace) for LLM-touching paths
  - `client` + X-Admin-Token for endpoint tests
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.planning import executor as ex, planner, revision, storage as pl
from app.services.tools.base import ToolContext, ToolError
from app.services.tools.plan_query import PlanQueryTool

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_planning_db(tmp_path, monkeypatch):
    """Per-test SQLite file so tests don't pollute each other (or the real db)."""
    db = tmp_path / "planning.db"
    monkeypatch.setattr(pl, "PLANNING_DB_PATH", db)
    yield db


# ─── storage: plans ──────────────────────────────────────────────────


def test_create_plan_then_get():
    p = pl.create_plan("KDP launch", "launch a KDP book about X")
    assert p.id > 0
    assert p.status == "draft"
    got = pl.get_plan(p.id)
    assert got is not None
    assert got.title == "KDP launch"
    assert got.goal == "launch a KDP book about X"
    assert got.steps == []


def test_create_plan_empty_title_or_goal_raises():
    with pytest.raises(ValueError):
        pl.create_plan("   ", "goal")
    with pytest.raises(ValueError):
        pl.create_plan("title", "   ")


def test_create_plan_rejects_bad_status():
    with pytest.raises(ValueError):
        pl.create_plan("t", "g", status="nonsense")


def test_get_plan_missing_returns_none():
    assert pl.get_plan(999) is None


def test_list_plans_orders_and_filters():
    a = pl.create_plan("a", "g")
    b = pl.create_plan("b", "g")
    pl.update_plan_status(b.id, "blocked")
    all_plans = pl.list_plans()
    assert {p.id for p in all_plans} == {a.id, b.id}
    blocked = pl.list_plans(status="blocked")
    assert [p.id for p in blocked] == [b.id]


def test_update_plan_status_unknown_plan_raises():
    with pytest.raises(ValueError):
        pl.update_plan_status(123, "approved")


# ─── storage: steps + branch columns ─────────────────────────────────


def test_add_step_auto_increments_seq():
    p = pl.create_plan("t", "g")
    s1 = pl.add_step(p.id, "first")
    s2 = pl.add_step(p.id, "second")
    assert s1.seq == 1
    assert s2.seq == 2
    assert s1.status == "pending"


def test_add_step_persists_branch_directives():
    p = pl.create_plan("t", "g")
    s = pl.add_step(p.id, "risky", on_fail="goto:1", on_done="goto:5")
    fetched = pl.get_step(s.id)
    assert fetched.on_fail == "goto:1"
    assert fetched.on_done == "goto:5"


def test_add_step_tool_kind():
    p = pl.create_plan("t", "g")
    s = pl.add_step(p.id, "look it up", kind="tool", tool_name="kg_query")
    assert s.kind == "tool"
    assert s.tool_name == "kg_query"


def test_add_step_bad_kind_raises():
    p = pl.create_plan("t", "g")
    with pytest.raises(ValueError):
        pl.add_step(p.id, "x", kind="banana")


def test_add_step_empty_action_raises():
    p = pl.create_plan("t", "g")
    with pytest.raises(ValueError):
        pl.add_step(p.id, "   ")


def test_add_step_unknown_plan_raises():
    with pytest.raises(ValueError):
        pl.add_step(999, "x")


def test_replace_steps_renumbers_and_resets():
    p = pl.create_plan("t", "g")
    pl.add_step(p.id, "old1")
    pl.add_step(p.id, "old2")
    new = pl.replace_steps(p.id, [
        {"action": "a", "on_fail": "revise"},
        {"action": "b", "kind": "tool", "tool_name": "web_fetch"},
        {"action": "   "},  # skipped (empty)
    ])
    assert [s.seq for s in new] == [1, 2]
    assert new[0].action == "a"
    assert new[0].on_fail == "revise"
    assert new[1].kind == "tool"
    fetched = pl.get_plan(p.id)
    assert len(fetched.steps) == 2


def test_next_pending_step_picks_lowest_seq():
    p = pl.create_plan("t", "g")
    pl.add_step(p.id, "one")
    s2 = pl.add_step(p.id, "two")
    # complete step 1
    pl.set_step_status(pl.get_plan(p.id).steps[0].id, "done")
    nxt = pl.next_pending_step(p.id)
    assert nxt.id == s2.id


def test_next_pending_step_none_when_all_done():
    p = pl.create_plan("t", "g")
    s = pl.add_step(p.id, "one")
    pl.set_step_status(s.id, "done")
    assert pl.next_pending_step(p.id) is None


def test_update_step_patches_only_given_fields():
    p = pl.create_plan("t", "g")
    s = pl.add_step(p.id, "orig")
    pl.update_step(s.id, action="changed", on_fail="stop")
    got = pl.get_step(s.id)
    assert got.action == "changed"
    assert got.on_fail == "stop"
    assert got.status == "pending"  # untouched


def test_update_step_no_fields_returns_existing():
    p = pl.create_plan("t", "g")
    s = pl.add_step(p.id, "orig")
    same = pl.update_step(s.id)
    assert same.id == s.id


# ─── storage: step runs ──────────────────────────────────────────────


def test_add_and_list_step_runs():
    p = pl.create_plan("t", "g")
    s = pl.add_step(p.id, "one")
    pl.add_step_run(s.id, p.id, s.seq, status="done", output="ok", cost_usd=0.002)
    pl.add_step_run(s.id, p.id, s.seq, status="failed", error="boom")
    runs = pl.list_step_runs(p.id)
    assert len(runs) == 2
    # newest first
    assert runs[0].status == "failed"
    assert runs[0].error == "boom"
    assert runs[1].output == "ok"
    assert runs[1].cost_usd == pytest.approx(0.002)


def test_steps_cascade_delete_on_replace_clears_runs():
    p = pl.create_plan("t", "g")
    s = pl.add_step(p.id, "one")
    pl.add_step_run(s.id, p.id, s.seq, status="done", output="x")
    # replacing steps deletes old steps → their runs cascade away
    pl.replace_steps(p.id, [{"action": "fresh"}])
    assert pl.list_step_runs(p.id) == []


# ─── storage: stats ──────────────────────────────────────────────────


def test_stats_counts_by_status():
    a = pl.create_plan("a", "g")
    b = pl.create_plan("b", "g")
    pl.update_plan_status(a.id, "executing")
    pl.update_plan_status(b.id, "blocked")
    pl.add_step(a.id, "x")
    s = pl.stats()
    assert s["total"] == 2
    assert s["active"] == 1  # executing
    assert s["blocked"] == 1
    assert s["step_total"] == 1


# ─── planner: JSON parsing ───────────────────────────────────────────


def test_parse_clean_object():
    steps = planner.parse_steps_json(
        '{"steps":[{"action":"a","kind":"chat"},'
        '{"action":"b","kind":"tool","tool_name":"web_fetch"}]}'
    )
    assert [s["action"] for s in steps] == ["a", "b"]
    assert steps[1]["kind"] == "tool"
    assert steps[1]["tool_name"] == "web_fetch"


def test_parse_bare_array():
    steps = planner.parse_steps_json('[{"action":"a"},{"action":"b"}]')
    assert len(steps) == 2


def test_parse_strips_code_fence():
    steps = planner.parse_steps_json('```json\n{"steps":[{"action":"x"}]}\n```')
    assert steps[0]["action"] == "x"


def test_parse_finds_object_in_prose():
    raw = 'Sure! Here is the plan:\n{"steps":[{"action":"do it"}]}\nHope that helps.'
    steps = planner.parse_steps_json(raw)
    assert steps[0]["action"] == "do it"


def test_parse_garbage_returns_empty():
    assert planner.parse_steps_json("no json here") == []
    assert planner.parse_steps_json("") == []


def test_parse_skips_actionless_rows():
    steps = planner.parse_steps_json(
        '{"steps":[{"action":""},{"action":"keep"},{"foo":"bar"}]}'
    )
    assert [s["action"] for s in steps] == ["keep"]


def test_parse_normalizes_null_on_fail_string():
    steps = planner.parse_steps_json('{"steps":[{"action":"a","on_fail":"null"}]}')
    assert "on_fail" not in steps[0]
    steps2 = planner.parse_steps_json('{"steps":[{"action":"a","on_fail":"goto:1"}]}')
    assert steps2[0]["on_fail"] == "goto:1"


# ─── planner: propose_steps / generate_plan (fake router) ────────────


def _planner_router(content, *, cost=0.001):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    return r


def test_propose_steps_happy():
    r = _planner_router('{"steps":[{"action":"step one"},{"action":"step two"}]}')
    steps, cost = planner.propose_steps("launch X", router=r, user_id=uuid.uuid4())
    assert [s["action"] for s in steps] == ["step one", "step two"]
    assert cost == 0.001
    assert r.complete.called


def test_propose_steps_router_crash_failsoft():
    r = MagicMock()
    r.complete.side_effect = RuntimeError("down")
    steps, cost = planner.propose_steps("g", router=r, user_id=uuid.uuid4())
    assert steps == []
    assert cost == 0.0


def test_propose_steps_caps_at_max_steps():
    many = ",".join('{"action":"s%d"}' % i for i in range(30))
    r = _planner_router("{\"steps\":[" + many + "]}")
    steps, _ = planner.propose_steps("g", router=r, user_id=uuid.uuid4(), max_steps=5)
    assert len(steps) == 5


def test_propose_steps_empty_goal_raises():
    with pytest.raises(ValueError):
        planner.propose_steps("  ", router=MagicMock(), user_id=uuid.uuid4())


def test_generate_plan_persists_draft_with_steps():
    r = _planner_router('{"steps":[{"action":"one"},{"action":"two"}]}')
    plan, cost = planner.generate_plan(
        "Launch the KDP book about cats", router=r, user_id=uuid.uuid4()
    )
    assert plan.status == "draft"
    assert len(plan.steps) == 2
    assert plan.title.startswith("Launch the KDP")
    assert plan.meta.get("proposal_cost_usd") == 0.001


def test_generate_plan_empty_steps_still_creates_plan():
    r = _planner_router("not json")
    plan, _ = planner.generate_plan("g", router=r, user_id=uuid.uuid4())
    assert plan.status == "draft"
    assert plan.steps == []


# ─── executor: directive parsing ─────────────────────────────────────


def test_parse_directive_variants():
    assert ex.parse_directive(None) is None
    assert ex.parse_directive("") is None
    assert ex.parse_directive("stop") == ("stop", None)
    assert ex.parse_directive("revise") == ("revise", None)
    assert ex.parse_directive("goto:3") == ("goto", 3)
    assert ex.parse_directive("GOTO:5") == ("goto", 5)
    assert ex.parse_directive("goto:abc") is None
    assert ex.parse_directive("nonsense") is None


# ─── executor: state machine (fake runners) ──────────────────────────


def _ok(output="did it", cost=0.0):
    return lambda step: ex.RunOutcome(success=True, output=output, cost_usd=cost)


def _fail(error="boom"):
    return lambda step: ex.RunOutcome(success=False, error=error)


def _approved(actions):
    """Create an approved plan from a list of (action, kwargs) tuples."""
    p = pl.create_plan("t", "g")
    for action, kw in actions:
        pl.add_step(p.id, action, **kw)
    pl.update_plan_status(p.id, "approved")
    return p


def test_execute_draft_plan_does_not_run():
    p = pl.create_plan("t", "g")
    pl.add_step(p.id, "a")
    res = ex.execute_next(p.id, runner=_ok())
    assert res.ran is False
    assert res.plan_status == "draft"


def test_execute_unknown_plan_raises():
    with pytest.raises(ValueError):
        ex.execute_next(999, runner=_ok())


def test_execute_happy_advances_and_persists_result():
    p = _approved([("a", {}), ("b", {})])
    res = ex.execute_next(p.id, runner=_ok("output-a", cost=0.01))
    assert res.ran is True
    assert res.outcome == "done"
    assert res.plan_status == "executing"
    assert res.step_seq == 1
    assert res.next_seq == 2
    assert res.cost_usd == 0.01
    step1 = pl.get_plan(p.id).steps[0]
    assert step1.status == "done"
    assert step1.result == "output-a"
    runs = pl.list_step_runs(p.id)
    assert runs[0].status == "done"
    assert runs[0].output == "output-a"


def test_execute_last_step_completes_plan():
    p = _approved([("only", {})])
    res = ex.execute_next(p.id, runner=_ok())
    assert res.plan_status == "done"
    assert res.next_seq is None


def test_execute_no_pending_marks_done():
    p = _approved([("a", {})])
    ex.execute_next(p.id, runner=_ok())  # completes the only step → done
    res = ex.execute_next(p.id, runner=_ok())  # nothing left
    assert res.ran is False
    assert res.plan_status == "done"


def test_failure_blocks_plan_by_default():
    p = _approved([("a", {})])
    res = ex.execute_next(p.id, runner=_fail("nope"))
    assert res.outcome == "failed"
    assert res.plan_status == "blocked"
    assert res.branch == "revise"
    step = pl.get_plan(p.id).steps[0]
    assert step.status == "failed"
    runs = pl.list_step_runs(p.id)
    assert runs[0].status == "failed"
    assert runs[0].error == "nope"


def test_failure_stop_directive_blocks_with_note():
    p = _approved([("a", {"on_fail": "stop"})])
    res = ex.execute_next(p.id, runner=_fail())
    assert res.plan_status == "blocked"
    assert res.branch == "stop"
    assert "stopped" in res.note


def test_failure_forward_goto_skips_intermediate():
    # step1 fails → goto:3, step2 (the normal path) must be skipped
    p = _approved([
        ("try A", {"on_fail": "goto:3"}),
        ("normal B", {}),
        ("fallback C", {}),
    ])
    res = ex.execute_next(p.id, runner=_fail())
    assert res.plan_status == "executing"
    assert res.branch == "goto:3"
    assert res.next_seq == 3  # B skipped, C is next
    steps = {s.seq: s.status for s in pl.get_plan(p.id).steps}
    assert steps[1] == "failed"
    assert steps[2] == "skipped"
    assert steps[3] == "pending"


def test_failure_backward_goto_rearms_retry_segment():
    # step2 fails → goto:1, re-arms steps 1 and 2 for a retry loop
    p = _approved([("A", {}), ("B", {"on_fail": "goto:1"})])
    ex.execute_next(p.id, runner=_ok())          # step1 done
    res = ex.execute_next(p.id, runner=_fail())   # step2 fails → goto:1
    assert res.plan_status == "executing"
    assert res.next_seq == 1
    steps = {s.seq: s.status for s in pl.get_plan(p.id).steps}
    assert steps[1] == "pending"  # re-armed
    assert steps[2] == "pending"  # re-armed (the failed step retries)


def test_failure_goto_missing_target_blocks():
    p = _approved([("a", {"on_fail": "goto:99"})])
    res = ex.execute_next(p.id, runner=_fail())
    assert res.plan_status == "blocked"


def test_success_on_done_forward_goto_skips():
    p = _approved([
        ("A", {"on_done": "goto:3"}),
        ("B", {}),
        ("C", {}),
    ])
    res = ex.execute_next(p.id, runner=_ok())
    assert res.outcome == "done"
    assert res.next_seq == 3
    assert "goto:3" in (res.branch or "")
    steps = {s.seq: s.status for s in pl.get_plan(p.id).steps}
    assert steps[1] == "done"
    assert steps[2] == "skipped"
    assert steps[3] == "pending"


def test_runner_returning_garbage_blocks_cleanly():
    p = _approved([("a", {})])
    res = ex.execute_next(p.id, runner=lambda s: "not a RunOutcome")
    assert res.outcome == "failed"
    assert res.plan_status == "blocked"


def test_runner_raising_blocks_cleanly():
    def _boom(step):
        raise RuntimeError("kaboom")
    p = _approved([("a", {})])
    res = ex.execute_next(p.id, runner=_boom)
    assert res.outcome == "failed"
    assert res.plan_status == "blocked"


# ─── revision: propose a fix for a blocked plan ──────────────────────


def _rev_router(content, *, cost=0.002):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    return r


def _blocked_with_failure():
    """A plan with step 1 done, step 2 failed, status blocked."""
    p = pl.create_plan("t", "launch the book")
    s1 = pl.add_step(p.id, "draft")
    s2 = pl.add_step(p.id, "write ch1")
    pl.set_step_status(s1.id, "done")
    pl.set_step_status(s2.id, "failed", result="boom")
    pl.add_step_run(s2.id, p.id, s2.seq, status="failed", error="DB timeout")
    pl.update_plan_status(p.id, "blocked")
    return p, s2


def test_propose_revision_unknown_plan_raises():
    with pytest.raises(ValueError):
        revision.propose_revision(999, router=MagicMock(), user_id=uuid.uuid4())


def test_propose_revision_no_failure_returns_empty():
    p = pl.create_plan("t", "g")
    pl.add_step(p.id, "a")
    out = revision.propose_revision(p.id, router=MagicMock(), user_id=uuid.uuid4())
    assert out["failed_step"] is None
    assert out["proposed_steps"] == []


def test_propose_revision_happy():
    p, _ = _blocked_with_failure()
    r = _rev_router(
        '{"diagnosis":"ch1 needs an outline first",'
        '"steps":[{"action":"make outline"},{"action":"write ch1"}]}'
    )
    out = revision.propose_revision(p.id, router=r, user_id=uuid.uuid4())
    assert out["failed_step"]["seq"] == 2
    assert out["failed_step"]["error"] == "DB timeout"
    assert "outline" in out["diagnosis"]
    assert [s["action"] for s in out["proposed_steps"]] == ["make outline", "write ch1"]
    assert out["cost_usd"] == 0.002


def test_propose_revision_accepts_proposed_steps_alias():
    p, _ = _blocked_with_failure()
    r = _rev_router('{"diagnosis":"x","proposed_steps":[{"action":"redo"}]}')
    out = revision.propose_revision(p.id, router=r, user_id=uuid.uuid4())
    assert [s["action"] for s in out["proposed_steps"]] == ["redo"]


def test_propose_revision_router_crash_failsoft():
    p, _ = _blocked_with_failure()
    r = MagicMock()
    r.complete.side_effect = RuntimeError("down")
    out = revision.propose_revision(p.id, router=r, user_id=uuid.uuid4())
    assert out["proposed_steps"] == []
    assert "unavailable" in out["diagnosis"]
    assert out["failed_step"]["seq"] == 2


# ─── plan_query tool (read-only) ─────────────────────────────────────


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_plan_query_list():
    pl.create_plan("a", "g")
    pl.create_plan("b", "g")
    out = PlanQueryTool().execute(_ctx(), action="list")
    assert out["count"] == 2


def test_plan_query_list_status_filter():
    pl.create_plan("a", "g")
    b = pl.create_plan("b", "g")
    pl.update_plan_status(b.id, "blocked")
    out = PlanQueryTool().execute(_ctx(), action="list", status="blocked")
    assert out["count"] == 1
    assert out["plans"][0]["id"] == b.id


def test_plan_query_get():
    p = pl.create_plan("a", "g")
    pl.add_step(p.id, "one")
    out = PlanQueryTool().execute(_ctx(), action="get", plan_id=p.id)
    assert out["plan"]["id"] == p.id
    assert len(out["plan"]["steps"]) == 1


def test_plan_query_get_missing_plan():
    with pytest.raises(ToolError):
        PlanQueryTool().execute(_ctx(), action="get", plan_id=999)


def test_plan_query_status_next_step():
    p = pl.create_plan("a", "g")
    pl.add_step(p.id, "one")
    pl.add_step(p.id, "two")
    pl.update_plan_status(p.id, "executing")
    out = PlanQueryTool().execute(_ctx(), action="status", plan_id=p.id)
    assert out["next_step"]["seq"] == 1
    assert out["blocked_on"] is None


def test_plan_query_status_blocked_on():
    p, _ = _blocked_with_failure()
    out = PlanQueryTool().execute(_ctx(), action="status", plan_id=p.id)
    assert out["status"] == "blocked"
    assert out["blocked_on"]["seq"] == 2


def test_plan_query_requires_action():
    with pytest.raises(ToolError):
        PlanQueryTool().execute(_ctx(), action="")


def test_plan_query_get_requires_plan_id():
    with pytest.raises(ToolError):
        PlanQueryTool().execute(_ctx(), action="get")


# ─── admin endpoints ─────────────────────────────────────────────────

import app.routers.admin_planning as admin_planning  # noqa: E402


@pytest.fixture
def _isolated_audit(monkeypatch):
    """Isolate the governance audit log so write tests (incl. denied paths,
    which also record) don't pollute the real data/governance/audit.jsonl."""
    import tempfile
    from app.services.governance import audit_log as _al

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        monkeypatch.setattr(_al, "AUDIT_LOG_PATH", _al.Path(tf.name))
        yield


def _patch_llm(monkeypatch, content, *, cost=0.001):
    """Patch admin_planning's router build + operator resolution so the
    LLM-touching endpoints run against a fake router with canned content —
    no real adapters or DB ultra-profile needed."""
    fake_router = MagicMock()
    fake_router.complete.return_value = SimpleNamespace(
        content=content, total_cost_usd=cost
    )
    monkeypatch.setattr(admin_planning, "build_default_router", lambda session: fake_router)
    monkeypatch.setattr(
        admin_planning, "_resolve_operator_profile",
        lambda session: SimpleNamespace(id=uuid.uuid4(), tier="ultra"),
    )
    monkeypatch.setattr(admin_planning, "build_default_registry", lambda: MagicMock())
    return fake_router


# reads -------------------------------------------------------------


def test_admin_stats_requires_token(client):
    assert client.get("/admin/planning/stats").status_code == 403


def test_admin_stats_empty(client):
    r = client.get("/admin/planning/stats", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_admin_list_and_get(client):
    p = pl.create_plan("a", "g")
    pl.add_step(p.id, "one")
    r = client.get("/admin/planning/list", headers=ADMIN_HEADERS)
    assert r.json()["count"] == 1
    r2 = client.get(f"/admin/planning/{p.id}", headers=ADMIN_HEADERS)
    assert r2.json()["plan"]["id"] == p.id
    assert len(r2.json()["plan"]["steps"]) == 1


def test_admin_get_missing_404(client):
    assert client.get("/admin/planning/999", headers=ADMIN_HEADERS).status_code == 404


# create ------------------------------------------------------------


def test_admin_create_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_PLANNING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_PLANNING_CREATE", raising=False)
    r = client.post(
        "/admin/planning/create", headers=ADMIN_HEADERS,
        json={"goal": "x", "approved": True},
    )
    assert r.status_code == 403


def test_admin_create_requires_approval_409(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    r = client.post(
        "/admin/planning/create", headers=ADMIN_HEADERS,
        json={"goal": "x", "approved": False},
    )
    assert r.status_code == 409


def test_admin_create_approved_generates_plan(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    _patch_llm(monkeypatch, '{"steps":[{"action":"one"},{"action":"two"}]}')
    r = client.post(
        "/admin/planning/create", headers=ADMIN_HEADERS,
        json={"goal": "launch the book", "approved": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["status"] == "draft"
    assert len(body["plan"]["steps"]) == 2


# approve -----------------------------------------------------------


def test_admin_approve_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_PLANNING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_PLANNING_APPROVE", raising=False)
    p = pl.create_plan("a", "g")
    r = client.post(
        f"/admin/planning/{p.id}/approve", headers=ADMIN_HEADERS,
        json={"approved": True},
    )
    assert r.status_code == 403


def test_admin_approve_flow(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    p = pl.create_plan("a", "g")
    pl.add_step(p.id, "one")
    # no approval → 409
    r1 = client.post(
        f"/admin/planning/{p.id}/approve", headers=ADMIN_HEADERS,
        json={"approved": False},
    )
    assert r1.status_code == 409
    # approved → 200, status approved
    r2 = client.post(
        f"/admin/planning/{p.id}/approve", headers=ADMIN_HEADERS,
        json={"approved": True},
    )
    assert r2.status_code == 200
    assert r2.json()["plan"]["status"] == "approved"


def test_admin_approve_rejects_done_plan_400(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    p = pl.create_plan("a", "g")
    pl.update_plan_status(p.id, "done")
    r = client.post(
        f"/admin/planning/{p.id}/approve", headers=ADMIN_HEADERS,
        json={"approved": True},
    )
    assert r.status_code == 400


# edit steps --------------------------------------------------------


def test_admin_edit_steps(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    p = pl.create_plan("a", "g")
    pl.add_step(p.id, "old")
    r = client.post(
        f"/admin/planning/{p.id}/steps", headers=ADMIN_HEADERS,
        json={
            "steps": [{"action": "new1"}, {"action": "new2", "on_fail": "stop"}],
            "approved": True,
        },
    )
    assert r.status_code == 200
    steps = r.json()["plan"]["steps"]
    assert [s["action"] for s in steps] == ["new1", "new2"]
    assert steps[1]["on_fail"] == "stop"


# execute-next ------------------------------------------------------


def test_admin_execute_next_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_PLANNING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_PLANNING_EXECUTE", raising=False)
    p = pl.create_plan("a", "g")
    pl.update_plan_status(p.id, "approved")
    r = client.post(
        f"/admin/planning/{p.id}/execute-next", headers=ADMIN_HEADERS,
        json={"approved": True},
    )
    assert r.status_code == 403


def test_admin_execute_next_runs_step(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    _patch_llm(monkeypatch, "step output here")
    p = pl.create_plan("a", "g")
    pl.add_step(p.id, "do it")
    pl.update_plan_status(p.id, "approved")
    r = client.post(
        f"/admin/planning/{p.id}/execute-next", headers=ADMIN_HEADERS,
        json={"approved": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["outcome"] == "done"
    assert body["plan"]["status"] == "done"


# revise ------------------------------------------------------------


def test_admin_revise_proposes(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    _patch_llm(monkeypatch, '{"diagnosis":"needs outline","steps":[{"action":"outline"}]}')
    p, _ = _blocked_with_failure()
    r = client.post(
        f"/admin/planning/{p.id}/revise", headers=ADMIN_HEADERS,
        json={"approved": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert "outline" in body["diagnosis"]
    assert body["proposed_steps"][0]["action"] == "outline"


# ─── remediation (proactive: detected issues → draft plans) ──────────

from app.services.planning import remediation as prem  # noqa: E402


def _steps_router(steps_json='{"steps":[{"action":"do x","kind":"chat"}]}', *, cost=0.001):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=steps_json, total_cost_usd=cost)
    return r


def test_remediation_gather_defensive():
    # reads real subsystems (audit/failures/learning/planning) — must never raise
    assert isinstance(prem._gather_issues(), list)


def test_remediation_goal_for_kinds():
    assert "recurring failure" in prem._goal_for({"kind": "failure", "detail": "x"})
    assert "audit issue" in prem._goal_for({"kind": "audit", "detail": "y"})
    assert "underperforming" in prem._goal_for({"kind": "lesson", "detail": "z"})
    assert "blocked" in prem._goal_for({"kind": "blocked_plan", "detail": "w"})


def test_propose_remediations_no_issues(monkeypatch):
    monkeypatch.setattr(prem, "_gather_issues", lambda *a, **k: [])
    out = prem.propose_remediations(router=MagicMock(), user_id=uuid.uuid4())
    assert out["proposed_plans"] == [] and out["issues_found"] == 0
    assert "nothing to remediate" in out["note"]


def test_propose_remediations_drafts_a_plan(monkeypatch):
    monkeypatch.setattr(prem, "_gather_issues", lambda *a, **k: [
        {"kind": "failure", "weight": 3, "detail": "tool_error [twitter] ×2: 401"}])
    out = prem.propose_remediations(router=_steps_router(), user_id=uuid.uuid4(), max_plans=1)
    assert out["issues_found"] == 1 and len(out["proposed_plans"]) == 1
    p = out["proposed_plans"][0]
    assert p["status"] == "draft" and p["issue_kind"] == "failure"
    # persisted as an inert draft tagged as a remediation
    plan = pl.get_plan(p["plan_id"])
    assert plan.status == "draft" and plan.meta.get("remediation") is True


def test_propose_remediations_caps_at_max_plans(monkeypatch):
    monkeypatch.setattr(prem, "_gather_issues", lambda *a, **k: [
        {"kind": "failure", "weight": 3, "detail": f"f{i}"} for i in range(5)])
    out = prem.propose_remediations(router=_steps_router(), user_id=uuid.uuid4(), max_plans=2)
    assert len(out["proposed_plans"]) == 2  # capped, even though 5 issues found
    assert out["issues_found"] == 5


def test_admin_remediate_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_PLANNING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_PLANNING_REMEDIATE", raising=False)
    r = client.post("/admin/planning/remediate", headers=ADMIN_HEADERS, json={})
    assert r.status_code == 403


def test_admin_remediate_propose_only_no_approval(client, monkeypatch, _isolated_audit):
    # destructive=False → works WITHOUT approved=true (drafts are inert)
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    monkeypatch.setattr(prem, "_gather_issues", lambda *a, **k: [
        {"kind": "audit", "weight": 2, "detail": "X: scope off"}])
    _patch_llm(monkeypatch, '{"steps":[{"action":"flip the flag","kind":"chat"}]}')
    r = client.post("/admin/planning/remediate", headers=ADMIN_HEADERS, json={"max_plans": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["issues_found"] == 1
    assert body["proposed_plans"][0]["status"] == "draft"


# ─── integration scout (capability → draft integration plan) ─────────

from app.services.planning import integration as pint  # noqa: E402


def _candidate(**over):
    base = {
        "repo": "All-Hands-AI/OpenHands",
        "url": "https://github.com/All-Hands-AI/OpenHands",
        "stars": 40000, "license": "MIT (permissive)",
        "recommendation": "evaluate",
    }
    base.update(over)
    return base


def test_integration_goal_for_references_repo():
    g = pint._goal_for("agent memory", _candidate())
    assert "All-Hands-AI/OpenHands" in g
    # the goal must forbid running the repo's code — reference design only
    assert "REFERENCE DESIGN" in g and "NOT by cloning" in g
    assert "Do NOT download or execute external code" in g


def test_propose_integrations_empty_capability_raises():
    with pytest.raises(ValueError):
        pint.propose_integrations(
            "  ", router=MagicMock(), user_id=uuid.uuid4(), session=MagicMock()
        )


def test_propose_integrations_no_candidates(monkeypatch):
    monkeypatch.setattr(pint, "_scout", lambda *a, **k: [])
    out = pint.propose_integrations(
        "obscure", router=MagicMock(), user_id=uuid.uuid4(), session=MagicMock()
    )
    assert out["proposed_plans"] == [] and out["candidates_found"] == 0
    assert "no GitHub repos matched" in out["note"]


def test_propose_integrations_all_avoid_drafts_nothing(monkeypatch):
    # avoid-tier (no license / archived) is never proposed
    monkeypatch.setattr(pint, "_scout", lambda *a, **k: [_candidate(recommendation="avoid")])
    out = pint.propose_integrations(
        "x", router=_steps_router(), user_id=uuid.uuid4(), session=MagicMock()
    )
    assert out["proposed_plans"] == [] and out["candidates_found"] == 1
    assert "safely adoptable" in out["note"]


def test_propose_integrations_drafts_inert_plan(monkeypatch):
    monkeypatch.setattr(pint, "_scout", lambda *a, **k: [_candidate()])
    out = pint.propose_integrations(
        "agent memory", router=_steps_router(), user_id=uuid.uuid4(),
        session=MagicMock(), max_plans=1,
    )
    assert out["candidates_found"] == 1 and len(out["proposed_plans"]) == 1
    p = out["proposed_plans"][0]
    assert p["status"] == "draft" and p["candidate_repo"] == "All-Hands-AI/OpenHands"
    # persisted as an inert draft tagged as an integration
    plan = pl.get_plan(p["plan_id"])
    assert plan.status == "draft" and plan.meta.get("integration") is True
    assert plan.meta.get("capability") == "agent memory"


def test_propose_integrations_caps_at_max_plans(monkeypatch):
    monkeypatch.setattr(pint, "_scout", lambda *a, **k: [
        _candidate(repo=f"acme/repo{i}") for i in range(4)])
    out = pint.propose_integrations(
        "x", router=_steps_router(), user_id=uuid.uuid4(),
        session=MagicMock(), max_plans=1,
    )
    assert len(out["proposed_plans"]) == 1 and out["candidates_found"] == 4


def test_admin_scout_integrate_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_PLANNING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_PLANNING_SCOUT", raising=False)
    r = client.post(
        "/admin/planning/scout-integrate", headers=ADMIN_HEADERS,
        json={"capability": "agent memory"},
    )
    assert r.status_code == 403


def test_admin_scout_integrate_propose_only_no_approval(client, monkeypatch, _isolated_audit):
    # destructive=False → works WITHOUT approved=true (discovery read-only, draft inert)
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    monkeypatch.setattr(pint, "_scout", lambda *a, **k: [_candidate()])
    _patch_llm(monkeypatch, '{"steps":[{"action":"read router.py","kind":"chat"}]}')
    r = client.post(
        "/admin/planning/scout-integrate", headers=ADMIN_HEADERS,
        json={"capability": "agent memory", "max_plans": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["candidates_found"] == 1
    assert body["proposed_plans"][0]["status"] == "draft"
    assert body["proposed_plans"][0]["candidate_repo"] == "All-Hands-AI/OpenHands"
