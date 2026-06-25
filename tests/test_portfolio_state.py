from core.portfolio import state, paths
from core.portfolio.actions import Action, ActionClass


def test_default_state(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    s = state.load_state("n8n")
    assert s["phase"] == "planning"
    assert s["completed_verbs"] == []
    assert s["pending_verbs"] == []


def test_mark_completed_clears_pending_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    state.mark_pending("n8n", "run_outreach_campaign")
    assert state.load_state("n8n")["pending_verbs"] == ["run_outreach_campaign"]
    state.mark_completed("n8n", "run_outreach_campaign")
    reloaded = state.load_state("n8n")          # re-read from disk, not in-memory
    assert reloaded["completed_verbs"] == ["run_outreach_campaign"]
    assert reloaded["pending_verbs"] == []


def test_record_artifact_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    p = state.record_artifact("n8n", "outreach", "touch1.txt", "Hi there")
    assert p.exists()
    assert p.read_text() == "Hi there"
    assert p.parent == tmp_path / "n8n" / "artifacts" / "outreach"


def test_audit_appends(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    state.audit({"verb": "x", "status": "executed"})
    state.audit({"verb": "y", "status": "queued"})
    rows = paths.read_jsonl(tmp_path / "audit.jsonl")
    assert [r["verb"] for r in rows] == ["x", "y"]


def test_approval_queue_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    action = Action("deploy_demo_instance", "infra", ActionClass.AMBER, [], "n8n", {"x": 1})
    aid = state.queue_approval(action)
    assert len(aid) == 12
    pending = state.list_approvals("pending")
    assert len(pending) == 1
    assert pending[0]["verb"] == "deploy_demo_instance"
    assert state.resolve_approval(aid, "approved") is True
    assert state.list_approvals("pending") == []
    assert state.list_approvals("approved")[0]["id"] == aid
    assert state.resolve_approval("missing-id", "approved") is False


def test_mark_pending_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    state.mark_pending("n8n", "draft_outreach")
    state.mark_pending("n8n", "draft_outreach")
    assert state.load_state("n8n")["pending_verbs"] == ["draft_outreach"]


def test_load_state_coerces_null_verb_lists(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    paths.save_json_atomic(tmp_path / "n8n" / "state.json",
                           {"phase": "planning", "completed_verbs": None, "pending_verbs": None})
    s = state.load_state("n8n")
    assert s["completed_verbs"] == []
    assert s["pending_verbs"] == []
