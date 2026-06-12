"""Digital-twin tests: profile entries + drafts storage, compose_profile,
suggest_entries (fake router + stubbed KG), draft_as_operator, injection
gating, the system-prompt wiring (always-on operator model), tool, and admin
endpoint auth/scope gates.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.twin import storage as ts
from app.services.twin import composer as tcomp
from app.services.twin import draft as tdraft
from app.services.twin import decide as tdecide
from app.services.twin import injection as tinj

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_twin_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "TWIN_DB_PATH", tmp_path / "twin.db")
    # decide-as-operator logs to a JSONL sidecar — isolate it too
    monkeypatch.setattr(tdecide, "DECIDE_LOG_PATH", tmp_path / "decisions.jsonl")
    yield


# ─── storage ─────────────────────────────────────────────────────────


def test_add_entry_defaults_active():
    e = ts.add_entry("identity", "Founder of WheellsVerse")
    assert e.status == "active" and e.section == "identity"


def test_add_entry_bad_section():
    with pytest.raises(ValueError):
        ts.add_entry("hobbies", "x")


def test_add_entry_empty_text():
    with pytest.raises(ValueError):
        ts.add_entry("voice", "   ")


def test_list_entries_filters():
    ts.add_entry("identity", "a", status="active")
    ts.add_entry("voice", "b", status="proposed")
    assert len(ts.list_entries(status="active")) == 1
    assert len(ts.list_entries(section="voice")) == 1


def test_set_entry_status_flow():
    e = ts.add_entry("goals", "ship KAI", status="proposed")
    ts.set_entry_status(e.id, "active")
    assert ts.get_entry(e.id).status == "active"


def test_set_entry_status_unknown():
    with pytest.raises(ValueError):
        ts.set_entry_status(999, "active")


def test_drafts_add_and_list():
    ts.add_draft("reply to investor", "Dear ...", cost_usd=0.01)
    rows = ts.list_drafts()
    assert len(rows) == 1 and rows[0].task == "reply to investor"


def test_stats():
    ts.add_entry("identity", "a")
    ts.add_entry("voice", "b", status="proposed")
    ts.add_draft("t", "c")
    s = ts.stats()
    assert s["active_entries"] == 1
    assert s["active_by_section"].get("identity") == 1
    assert s["drafts"] == 1


# ─── composer ────────────────────────────────────────────────────────


def test_compose_profile_groups_by_section_order():
    entries = [
        ts.Entry(id=1, section="goals", text="ship"),
        ts.Entry(id=2, section="identity", text="founder"),
        ts.Entry(id=3, section="voice", text="direct"),
    ]
    out = tcomp.compose_profile(entries)
    # identity must come before voice before goals (SECTIONS order)
    assert out.index("[identity]") < out.index("[voice]") < out.index("[goals]")
    assert "- founder" in out


def test_compose_profile_empty():
    assert tcomp.compose_profile([]) == ""


def _router(content, *, cost=0.002):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    return r


def test_suggest_entries_no_facts(monkeypatch):
    monkeypatch.setattr(tcomp, "_gather_operator_facts", lambda *a, **k: [])
    out = tcomp.suggest_entries(router=MagicMock(), user_id=uuid.uuid4())
    assert out["proposed"] == []
    assert "no operator facts" in out["note"]


def test_suggest_entries_happy(monkeypatch):
    monkeypatch.setattr(tcomp, "_gather_operator_facts",
                        lambda *a, **k: ["Jhon owns KAI", "Jhon is founder"])
    r = _router('{"entries":[{"section":"identity","text":"Founder of WheellsVerse"},'
                '{"section":"voice","text":"Direct, no fluff"}]}')
    out = tcomp.suggest_entries(router=r, user_id=uuid.uuid4())
    assert len(out["proposed"]) == 2
    # stored as proposed
    assert len(ts.list_entries(status="proposed")) == 2


def test_suggest_entries_router_crash_failsoft(monkeypatch):
    monkeypatch.setattr(tcomp, "_gather_operator_facts", lambda *a, **k: ["x"])
    r = MagicMock(); r.complete.side_effect = RuntimeError("down")
    out = tcomp.suggest_entries(router=r, user_id=uuid.uuid4())
    assert out["proposed"] == [] and "unavailable" in out["note"]


def test_suggest_entries_bad_section_defaults_identity(monkeypatch):
    monkeypatch.setattr(tcomp, "_gather_operator_facts", lambda *a, **k: ["x"])
    r = _router('{"entries":[{"section":"hobbies","text":"likes chess"}]}')
    out = tcomp.suggest_entries(router=r, user_id=uuid.uuid4())
    assert out["proposed"][0]["section"] == "identity"


# ─── draft ───────────────────────────────────────────────────────────


def test_draft_as_operator_happy():
    ts.add_entry("voice", "Direct, concise, first-person")
    r = _router("Hey — quick update: shipping today.")
    out = tdraft.draft_as_operator(router=r, user_id=uuid.uuid4(), task="reply to the team")
    assert out["draft"].startswith("Hey")
    assert out["cost_usd"] == 0.002
    assert len(ts.list_drafts()) == 1  # logged


def test_draft_empty_task_raises():
    with pytest.raises(ValueError):
        tdraft.draft_as_operator(router=MagicMock(), user_id=uuid.uuid4(), task="  ")


def test_draft_router_crash_failsoft():
    r = MagicMock(); r.complete.side_effect = RuntimeError("down")
    out = tdraft.draft_as_operator(router=r, user_id=uuid.uuid4(), task="x")
    assert out["draft"] == "" and "unavailable" in out["note"]


# ─── decide-as-operator (ADVISORY) ───────────────────────────────────


def test_decide_as_operator_happy():
    ts.add_entry("values", "Ships fast, prefers reversible bets")
    r = _router('{"decision":"Ship the MVP now","rationale":"bias to action",'
                '"confidence":"high","caveats":["revisit if churn spikes"]}')
    out = tdecide.decide_as_operator(
        router=r, user_id=uuid.uuid4(), question="Ship now or wait a week?")
    assert out["decision"] == "Ship the MVP now"
    assert out["confidence"] == "high"
    assert out["caveats"] == ["revisit if churn spikes"]
    assert out["advisory"] is True            # never executes — advisory flag
    assert "not executed" in out["note"]
    assert len(tdecide.list_decisions()) == 1  # logged for calibration


def test_decide_empty_question_raises():
    with pytest.raises(ValueError):
        tdecide.decide_as_operator(router=MagicMock(), user_id=uuid.uuid4(), question="  ")


def test_decide_router_crash_failsoft():
    r = MagicMock(); r.complete.side_effect = RuntimeError("down")
    out = tdecide.decide_as_operator(router=r, user_id=uuid.uuid4(), question="x?")
    assert out["decision"] == "" and out["advisory"] is True
    assert "unavailable" in out["note"]


def test_decide_unstructured_kept_as_rationale():
    r = _router("I think you'd just ship it, you always do.")  # not JSON
    out = tdecide.decide_as_operator(router=r, user_id=uuid.uuid4(), question="ship?")
    assert out["decision"] == "(see rationale)"
    assert "ship it" in out["rationale"]
    assert out["confidence"] == "low"


def test_decide_invalid_confidence_defaults_low():
    r = _router('{"decision":"yes","rationale":"because","confidence":"certain"}')
    out = tdecide.decide_as_operator(router=r, user_id=uuid.uuid4(), question="q?")
    assert out["confidence"] == "low"   # 'certain' isn't a valid level → low


def test_decide_options_and_context_accepted():
    r = _router('{"decision":"Option B","confidence":"medium"}')
    out = tdecide.decide_as_operator(
        router=r, user_id=uuid.uuid4(), question="which vendor?",
        options=["Vendor A", "Vendor B"], context="B is cheaper")
    assert out["decision"] == "Option B"


# ─── injection gating ────────────────────────────────────────────────


def test_injection_scope_off(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_TWIN", raising=False)
    ts.add_entry("identity", "Founder")
    assert tinj.twin_preamble() == ""


def test_injection_scope_on_includes_active(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    ts.add_entry("identity", "Founder of WheellsVerse")
    ts.add_entry("voice", "Proposed voice", status="proposed")  # excluded
    pre = tinj.twin_preamble()
    assert "Operator profile" in pre
    assert "Founder of WheellsVerse" in pre
    assert "Proposed voice" not in pre


def test_injection_scope_on_no_active(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    ts.add_entry("identity", "p", status="proposed")
    assert tinj.twin_preamble() == ""


# ─── system-prompt wiring (always-on operator model) ────────────────


def test_system_prompt_injects_twin_when_scope_on(monkeypatch):
    from app.services.nai_brain.system_prompt import build_system_prompt
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    ts.add_entry("identity", "Founder of WheellsVerse")
    prompt = build_system_prompt(memory_preamble="", persona_prompt="", lessons_preamble="")
    assert "Operator profile" in prompt
    assert "Founder of WheellsVerse" in prompt


def test_system_prompt_no_twin_when_scope_off(monkeypatch):
    from app.services.nai_brain.system_prompt import build_system_prompt
    monkeypatch.delenv("KAI_SCOPE_TWIN", raising=False)
    ts.add_entry("identity", "Founder of WheellsVerse")
    prompt = build_system_prompt(memory_preamble="", persona_prompt="", lessons_preamble="")
    assert "Founder of WheellsVerse" not in prompt


# ─── twin_query tool ─────────────────────────────────────────────────

from app.services.tools.base import ToolContext, ToolError  # noqa: E402
from app.services.tools.twin_query import TwinQueryTool  # noqa: E402


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_tool_profile_action():
    ts.add_entry("identity", "Founder")
    ts.add_entry("voice", "proposed", status="proposed")  # excluded (active only)
    out = TwinQueryTool().execute(_ctx(), action="profile")
    assert out["count"] == 1 and out["entries"][0]["text"] == "Founder"


def test_tool_drafts_action():
    ts.add_draft("t", "drafted text")
    out = TwinQueryTool().execute(_ctx(), action="drafts")
    assert out["count"] == 1 and out["drafts"][0]["content"] == "drafted text"


def test_tool_stats_action():
    ts.add_entry("goals", "ship")
    out = TwinQueryTool().execute(_ctx(), action="stats")
    assert out["active_entries"] == 1


def test_tool_unknown_action():
    with pytest.raises(ToolError):
        TwinQueryTool().execute(_ctx(), action="bogus")


# ─── admin endpoints ─────────────────────────────────────────────────

import app.routers.admin_twin as admin_twin  # noqa: E402


@pytest.fixture
def _isolated_audit(monkeypatch):
    import tempfile
    from app.services.governance import audit_log as _al
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        monkeypatch.setattr(_al, "AUDIT_LOG_PATH", _al.Path(tf.name))
        yield


def _patch_llm(monkeypatch, content, *, cost=0.002):
    fake = MagicMock()
    fake.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    monkeypatch.setattr(admin_twin, "build_default_router", lambda session: fake)
    monkeypatch.setattr(
        admin_twin, "_resolve_operator_profile",
        lambda session: SimpleNamespace(id=uuid.uuid4(), tier="ultra"),
    )
    return fake


def test_admin_stats_requires_token(client):
    assert client.get("/admin/twin/stats").status_code == 403


def test_admin_add_entry_and_profile(client):
    r = client.post("/admin/twin/entries", headers=ADMIN_HEADERS,
                    json={"section": "voice", "text": "Direct, no fluff"})
    assert r.status_code == 200
    assert r.json()["entry"]["status"] == "active"
    r2 = client.get("/admin/twin/profile?status=active", headers=ADMIN_HEADERS)
    assert r2.json()["count"] == 1


def test_admin_add_entry_bad_section_400(client):
    r = client.post("/admin/twin/entries", headers=ADMIN_HEADERS,
                    json={"section": "hobbies", "text": "chess"})
    assert r.status_code == 400


def test_admin_suggest_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_TWIN", raising=False)
    monkeypatch.delenv("KAI_SCOPE_TWIN_SUGGEST", raising=False)
    r = client.post("/admin/twin/suggest", headers=ADMIN_HEADERS, json={})
    assert r.status_code == 403


def test_admin_suggest_success(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    monkeypatch.setattr(tcomp, "_gather_operator_facts", lambda *a, **k: ["Jhon owns KAI"])
    _patch_llm(monkeypatch, '{"entries":[{"section":"identity","text":"Founder"}]}')
    r = client.post("/admin/twin/suggest", headers=ADMIN_HEADERS, json={"max_entries": 3})
    assert r.status_code == 200
    assert r.json()["proposed"][0]["text"] == "Founder"


def test_admin_activate_flow(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    e = ts.add_entry("identity", "Founder", status="proposed")
    r1 = client.post(f"/admin/twin/entries/{e.id}/activate",
                     headers=ADMIN_HEADERS, json={"approved": False})
    assert r1.status_code == 409
    r2 = client.post(f"/admin/twin/entries/{e.id}/activate",
                     headers=ADMIN_HEADERS, json={"approved": True})
    assert r2.status_code == 200
    assert r2.json()["entry"]["status"] == "active"


def test_admin_draft_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_TWIN", raising=False)
    monkeypatch.delenv("KAI_SCOPE_TWIN_DRAFT", raising=False)
    r = client.post("/admin/twin/draft", headers=ADMIN_HEADERS, json={"task": "x"})
    assert r.status_code == 403


def test_admin_draft_success(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    ts.add_entry("voice", "Direct, concise")
    _patch_llm(monkeypatch, "Hey team — shipping today.")
    r = client.post("/admin/twin/draft", headers=ADMIN_HEADERS,
                    json={"task": "reply to the team"})
    assert r.status_code == 200
    assert r.json()["draft"].startswith("Hey team")


def test_admin_decide_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_TWIN", raising=False)
    monkeypatch.delenv("KAI_SCOPE_TWIN_DECIDE", raising=False)
    r = client.post("/admin/twin/decide", headers=ADMIN_HEADERS, json={"question": "ship?"})
    assert r.status_code == 403


def test_admin_decide_success(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    ts.add_entry("values", "Bias to action")
    _patch_llm(monkeypatch, '{"decision":"Ship now","confidence":"high","rationale":"r"}')
    r = client.post("/admin/twin/decide", headers=ADMIN_HEADERS,
                    json={"question": "ship now or wait?"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "Ship now" and body["advisory"] is True


def test_admin_decisions_list(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_TWIN", "1")
    _patch_llm(monkeypatch, '{"decision":"yes","confidence":"low"}')
    client.post("/admin/twin/decide", headers=ADMIN_HEADERS, json={"question": "q?"})
    r = client.get("/admin/twin/decisions", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["count"] == 1
