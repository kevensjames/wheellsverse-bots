import json
from core.portfolio import loops, state, paths
from core.portfolio.actions import ActionClass


class _OkAdapter:
    def run(self, action):
        return {"ran": action.verb}


def _write_loop(tmp_path, slug, steps):
    d = tmp_path / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "loop.json").write_text(json.dumps({"business": slug, "steps": steps}))


def test_load_loop_parses_steps(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "research_niche", "agent": "kai.research", "class": "green"},
        {"verb": "run_outreach_campaign", "agent": "cold_outreach",
         "class": "auto_capped", "preconditions": ["warmup_complete"]},
    ])
    steps = loops.load_loop("n8n")
    assert [s.verb for s in steps] == ["research_niche", "run_outreach_campaign"]
    assert steps[1].action_class is ActionClass.AUTO_CAPPED
    assert steps[1].preconditions == ["warmup_complete"]


def test_select_next_skips_completed_and_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    steps = [
        loops.LoopStep("a", "kai", ActionClass.GREEN, []),
        loops.LoopStep("b", "kai", ActionClass.GREEN, []),
        loops.LoopStep("c", "kai", ActionClass.GREEN, []),
    ]
    st = {"completed_verbs": ["a"], "pending_verbs": ["b"]}
    assert loops.select_next_step(steps, st).verb == "c"
    assert loops.select_next_step(steps, {"completed_verbs": ["a", "b", "c"],
                                          "pending_verbs": []}) is None


def test_tick_executes_green_and_marks_completed(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "research_niche", "agent": "kai.research", "class": "green"},
    ])
    res = loops.tick("n8n", adapter_for=lambda step: _OkAdapter(), ctx_for=lambda step: {})
    assert res.status == "executed"
    assert state.load_state("n8n")["completed_verbs"] == ["research_niche"]
    # second tick: nothing left to do
    assert loops.tick("n8n", adapter_for=lambda s: _OkAdapter(), ctx_for=lambda s: {}) is None


def test_tick_queues_auto_capped_when_precondition_unmet(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "run_outreach_campaign", "agent": "cold_outreach",
         "class": "auto_capped", "preconditions": ["warmup_complete"]},
    ])
    res = loops.tick("n8n", adapter_for=lambda s: _OkAdapter(),
                     ctx_for=lambda s: {"warmup_complete": False})
    assert res.status == "queued"
    assert state.load_state("n8n")["pending_verbs"] == ["run_outreach_campaign"]
    assert len(state.list_approvals("pending")) == 1
    # verb is now pending -> not re-selected on the next tick
    assert loops.tick("n8n", adapter_for=lambda s: _OkAdapter(),
                      ctx_for=lambda s: {"warmup_complete": False}) is None


def test_tick_red_is_refused_and_does_not_block_forever(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "sign_contract", "agent": "legal", "class": "red"},
    ])
    res = loops.tick("n8n", adapter_for=lambda s: _OkAdapter(), ctx_for=lambda s: {})
    assert res.status == "refused"
    # RED stays out of completed; it is parked in pending so the loop advances.
    assert "sign_contract" in state.load_state("n8n")["pending_verbs"]
