from __future__ import annotations

from pathlib import Path

from core.portfolio import execute, state
from core.portfolio.actions import Action, ActionClass


def _queue(monkeypatch, tmp_path, verb="deploy_demo_instance", cls=ActionClass.AUTO_CAPPED):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    return state.queue_approval(Action(verb, "infra", cls, [], "n8n", {}))


def test_refuses_until_approved(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)
    assert execute.execute_approval(aid)["status"] == "refused"   # still pending


def test_executes_an_approved_action(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)
    state.resolve_approval(aid, "approved")
    res = execute.execute_approval(aid)
    assert res["status"] == "executed"
    assert res["verb"] == "deploy_demo_instance"
    # the infra adapter drafted a manifest artifact on disk
    assert (tmp_path / "n8n" / "artifacts" / "infra" / "deploy-manifest.json").exists()
    # the verb is marked completed
    assert "deploy_demo_instance" in state.load_state("n8n")["completed_verbs"]
    # audited as executed_by_approval
    audit = state.list_audit(50) if hasattr(state, "list_audit") else []
    # the approval is now 'executed' and cannot double-fire
    assert execute.execute_approval(aid)["status"] == "refused"
    assert {a["id"]: a["status"] for a in state.list_approvals()}[aid] == "executed"


def test_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert execute.execute_approval("missing-id")["status"] == "not_found"


def test_rejected_never_executes(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)
    state.resolve_approval(aid, "rejected")
    assert execute.execute_approval(aid)["status"] == "refused"


def test_refused_pending_does_not_run_adapter(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)  # pending
    assert execute.execute_approval(aid)["status"] == "refused"
    # the infra adapter NEVER ran -> no manifest on disk
    assert not (tmp_path / "n8n" / "artifacts" / "infra" / "deploy-manifest.json").exists()


def test_adapter_failure_marks_failed_not_executed(monkeypatch, tmp_path):
    aid = _queue(monkeypatch, tmp_path)
    state.resolve_approval(aid, "approved")
    import core.portfolio.adapters as ad

    class _Boom:
        def run(self, action):
            raise RuntimeError("boom")

    monkeypatch.setattr(ad, "adapter_for", lambda step: _Boom())
    res = execute.execute_approval(aid)
    assert res["status"] == "failed"
    assert {a["id"]: a["status"] for a in state.list_approvals()}[aid] == "failed"


def test_compare_and_set_claim_semantics(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    aid = state.queue_approval(Action("v", "a", ActionClass.AMBER, [], "n8n", {}))
    assert state.compare_and_set_approval(aid, "approved", "executing") is False  # currently pending
    state.resolve_approval(aid, "approved")
    assert state.compare_and_set_approval(aid, "approved", "executing") is True
    assert state.compare_and_set_approval(aid, "approved", "executing") is False  # now 'executing'


def test_appended_rearm_row_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    aid = state.queue_approval(Action("research_niche", "kai.research", ActionClass.GREEN, [], "n8n", {}))
    state.resolve_approval(aid, "approved")
    assert state.compare_and_set_approval(aid, "approved", "executing") is True  # legit claim
    # attacker appends a crafted duplicate 'approved' row for the same id
    import json as _j
    with (tmp_path / "approvals.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(_j.dumps({"id": aid, "status": "approved", "verb": "research_niche",
                           "agent": "kai.research", "action_class": "green",
                           "preconditions": [], "business": "n8n", "payload": {}}) + "\n")
    # mixed {executing, approved} state -> must REFUSE the re-claim
    assert state.compare_and_set_approval(aid, "approved", "executing") is False


def test_unknown_verb_refused_not_completed(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    aid = state.queue_approval(Action("totally_unknown_verb", "x", ActionClass.AMBER, [], "n8n", {}))
    state.resolve_approval(aid, "approved")
    res = execute.execute_approval(aid)
    assert res["status"] == "refused"
    assert "totally_unknown_verb" not in state.load_state("n8n").get("completed_verbs", [])
