"""Continuous-learning tests: feedback + lessons storage, synthesis (fake
router), injection gating, the system-prompt wiring (loop closure), the
learning_query tool, and admin endpoint auth/scope gates.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.learning import storage as ls
from app.services.learning import synthesis as lsyn
from app.services.learning import injection as linj

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_learning_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "LEARNING_DB_PATH", tmp_path / "learning.db")
    yield


# ─── storage: feedback ───────────────────────────────────────────────


def test_record_and_list_feedback():
    ls.record_feedback(rating="down", note="too verbose")
    ls.record_feedback(rating="up", note="great")
    rows = ls.list_feedback()
    assert len(rows) == 2
    assert rows[0].rating == "up"  # newest first
    downs = ls.list_feedback(rating="down")
    assert len(downs) == 1 and downs[0].note == "too verbose"


def test_record_feedback_bad_rating():
    with pytest.raises(ValueError):
        ls.record_feedback(rating="meh")


# ─── storage: lessons ────────────────────────────────────────────────


def test_add_lesson_and_status_flow():
    lesson = ls.add_lesson("Be more concise", source="feedback")
    assert lesson.status == "proposed"
    ls.set_lesson_status(lesson.id, "active")
    assert ls.get_lesson(lesson.id).status == "active"
    active = ls.list_lessons(status="active")
    assert [x.id for x in active] == [lesson.id]


def test_add_lesson_empty_raises():
    with pytest.raises(ValueError):
        ls.add_lesson("   ")


def test_set_lesson_status_bad_value():
    lesson = ls.add_lesson("x")
    with pytest.raises(ValueError):
        ls.set_lesson_status(lesson.id, "banana")


def test_set_lesson_status_unknown_lesson():
    with pytest.raises(ValueError):
        ls.set_lesson_status(999, "active")


def test_stats():
    ls.record_feedback(rating="down", note="a")
    ls.record_feedback(rating="down", note="b")
    lesson = ls.add_lesson("be concise")
    ls.set_lesson_status(lesson.id, "active")
    s = ls.stats()
    assert s["feedback_total"] == 2
    assert s["feedback_by_rating"]["down"] == 2
    assert s["active_lessons"] == 1


# ─── synthesis (fake router) ─────────────────────────────────────────


def _router(content, *, cost=0.002):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    return r


def test_synthesis_no_feedback_returns_empty():
    out = lsyn.synthesize_lessons(router=MagicMock(), user_id=uuid.uuid4())
    assert out["proposed"] == []
    assert "no feedback" in out["note"]


def test_synthesis_happy_stores_proposed():
    ls.record_feedback(rating="down", note="answers are too long")
    r = _router('{"lessons":[{"text":"Be concise","source":"feedback"},'
                '{"text":"Lead with the answer"}]}')
    out = lsyn.synthesize_lessons(router=r, user_id=uuid.uuid4())
    assert [p["text"] for p in out["proposed"]] == ["Be concise", "Lead with the answer"]
    assert out["cost_usd"] == 0.002
    # stored as proposed
    proposed = ls.list_lessons(status="proposed")
    assert len(proposed) == 2


def test_synthesis_router_crash_failsoft():
    ls.record_feedback(rating="down", note="x")
    r = MagicMock()
    r.complete.side_effect = RuntimeError("down")
    out = lsyn.synthesize_lessons(router=r, user_id=uuid.uuid4())
    assert out["proposed"] == []
    assert "unavailable" in out["note"]


def test_synthesis_parses_bare_string_array():
    ls.record_feedback(rating="down", note="x")
    r = _router('["Be concise", "Cite sources"]')
    out = lsyn.synthesize_lessons(router=r, user_id=uuid.uuid4())
    assert [p["text"] for p in out["proposed"]] == ["Be concise", "Cite sources"]


def test_synthesis_caps_at_max():
    ls.record_feedback(rating="down", note="x")
    many = ",".join('{"text":"L%d"}' % i for i in range(20))
    r = _router("{\"lessons\":[" + many + "]}")
    out = lsyn.synthesize_lessons(router=r, user_id=uuid.uuid4(), max_lessons=3)
    assert len(out["proposed"]) == 3


# ─── injection gating ────────────────────────────────────────────────


def test_injection_scope_off_returns_empty(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_LEARNING", raising=False)
    lesson = ls.add_lesson("Be concise")
    ls.set_lesson_status(lesson.id, "active")
    assert linj.active_lessons_preamble() == ""


def test_injection_scope_on_includes_active_lessons(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_LEARNING", "1")
    a = ls.add_lesson("Be concise"); ls.set_lesson_status(a.id, "active")
    ls.add_lesson("Proposed not active")  # stays proposed → excluded
    pre = linj.active_lessons_preamble()
    assert "Be concise" in pre
    assert "Proposed not active" not in pre


def test_injection_scope_on_no_active_returns_empty(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_LEARNING", "1")
    ls.add_lesson("just proposed")  # not active
    assert linj.active_lessons_preamble() == ""


# ─── the loop closes: build_system_prompt injects active lessons ─────


def test_system_prompt_injects_active_lesson_when_scope_on(monkeypatch):
    from app.services.nai_brain.system_prompt import build_system_prompt
    monkeypatch.setenv("KAI_SCOPE_LEARNING", "1")
    a = ls.add_lesson("Always lead with the answer"); ls.set_lesson_status(a.id, "active")
    prompt = build_system_prompt(memory_preamble="", persona_prompt="")
    assert "Always lead with the answer" in prompt


def test_system_prompt_no_lessons_when_scope_off(monkeypatch):
    from app.services.nai_brain.system_prompt import build_system_prompt
    monkeypatch.delenv("KAI_SCOPE_LEARNING", raising=False)
    a = ls.add_lesson("Always lead with the answer"); ls.set_lesson_status(a.id, "active")
    prompt = build_system_prompt(memory_preamble="", persona_prompt="")
    assert "Always lead with the answer" not in prompt


def test_system_prompt_explicit_empty_lessons_disables(monkeypatch):
    from app.services.nai_brain.system_prompt import build_system_prompt
    monkeypatch.setenv("KAI_SCOPE_LEARNING", "1")
    a = ls.add_lesson("x"); ls.set_lesson_status(a.id, "active")
    # explicit "" overrides the auto-pull (used by callers that don't want lessons)
    prompt = build_system_prompt(memory_preamble="", persona_prompt="", lessons_preamble="")
    assert "Lessons learned" not in prompt


# ─── learning_query tool ─────────────────────────────────────────────

from app.services.tools.base import ToolContext, ToolError  # noqa: E402
from app.services.tools.learning_query import LearningQueryTool  # noqa: E402


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_tool_lessons_action():
    a = ls.add_lesson("Be concise"); ls.set_lesson_status(a.id, "active")
    ls.add_lesson("proposed one")
    out = LearningQueryTool().execute(_ctx(), action="lessons", status="active")
    assert out["count"] == 1 and out["lessons"][0]["text"] == "Be concise"


def test_tool_feedback_action():
    ls.record_feedback(rating="down", note="verbose")
    out = LearningQueryTool().execute(_ctx(), action="feedback")
    assert out["count"] == 1 and out["feedback"][0]["rating"] == "down"


def test_tool_stats_action():
    ls.record_feedback(rating="up", note="x")
    out = LearningQueryTool().execute(_ctx(), action="stats")
    assert out["feedback_total"] == 1


def test_tool_unknown_action():
    with pytest.raises(ToolError):
        LearningQueryTool().execute(_ctx(), action="bogus")


# ─── admin endpoints ─────────────────────────────────────────────────

import app.routers.admin_learning as admin_learning  # noqa: E402


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
    monkeypatch.setattr(admin_learning, "build_default_router", lambda session: fake)
    monkeypatch.setattr(
        admin_learning, "_resolve_operator_profile",
        lambda session: SimpleNamespace(id=uuid.uuid4(), tier="ultra"),
    )
    return fake


def test_admin_stats_requires_token(client):
    assert client.get("/admin/learning/stats").status_code == 403


def test_admin_feedback_record_and_list(client):
    r = client.post("/admin/learning/feedback", headers=ADMIN_HEADERS,
                    json={"rating": "down", "note": "too long"})
    assert r.status_code == 200
    assert r.json()["feedback"]["rating"] == "down"
    r2 = client.get("/admin/learning/feedback", headers=ADMIN_HEADERS)
    assert r2.json()["count"] == 1


def test_admin_feedback_bad_rating_400(client):
    r = client.post("/admin/learning/feedback", headers=ADMIN_HEADERS,
                    json={"rating": "sideways"})
    assert r.status_code == 400


def test_admin_synthesize_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_LEARNING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_LEARNING_SYNTHESIZE", raising=False)
    r = client.post("/admin/learning/synthesize", headers=ADMIN_HEADERS, json={})
    assert r.status_code == 403


def test_admin_synthesize_success(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_LEARNING", "1")
    ls.record_feedback(rating="down", note="answers too long")
    _patch_llm(monkeypatch, '{"lessons":[{"text":"Be concise"}]}')
    r = client.post("/admin/learning/synthesize", headers=ADMIN_HEADERS,
                    json={"max_lessons": 3})
    assert r.status_code == 200
    assert r.json()["proposed"][0]["text"] == "Be concise"


def test_admin_activate_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_LEARNING", raising=False)
    monkeypatch.delenv("KAI_SCOPE_LEARNING_ACTIVATE", raising=False)
    lesson = ls.add_lesson("x")
    r = client.post(f"/admin/learning/lessons/{lesson.id}/activate",
                    headers=ADMIN_HEADERS, json={"approved": True})
    assert r.status_code == 403


def test_admin_activate_flow(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_LEARNING", "1")
    lesson = ls.add_lesson("Be concise")
    # no approval → 409
    r1 = client.post(f"/admin/learning/lessons/{lesson.id}/activate",
                     headers=ADMIN_HEADERS, json={"approved": False})
    assert r1.status_code == 409
    # approved → active
    r2 = client.post(f"/admin/learning/lessons/{lesson.id}/activate",
                     headers=ADMIN_HEADERS, json={"approved": True})
    assert r2.status_code == 200
    assert r2.json()["lesson"]["status"] == "active"


def test_admin_dismiss_flow(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_LEARNING", "1")
    lesson = ls.add_lesson("Be concise")
    ls.set_lesson_status(lesson.id, "active")
    r = client.post(f"/admin/learning/lessons/{lesson.id}/dismiss",
                    headers=ADMIN_HEADERS, json={"approved": True})
    assert r.status_code == 200
    assert r.json()["lesson"]["status"] == "dismissed"
