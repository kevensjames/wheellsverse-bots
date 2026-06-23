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
