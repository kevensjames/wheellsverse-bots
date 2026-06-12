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
from app.services.learning import tuning as ltun

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_learning_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "LEARNING_DB_PATH", tmp_path / "learning.db")
    # v2 synthesis also reads failures + self-correction events — isolate those
    # paths too so tests never pick up the repo's real data/ logs.
    from app.services.failure_memory import storage as _fstore
    from app.services.self_correction import loop as _scloop
    monkeypatch.setattr(_fstore, "FAILURE_LOG_PATH", tmp_path / "failures.jsonl")
    monkeypatch.setattr(_scloop, "EVENTS_PATH", tmp_path / "sc_events.jsonl")
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


def test_synthesis_no_signals_returns_empty():
    # v2: empty feedback AND failures AND self-correction → nothing to learn
    out = lsyn.synthesize_lessons(router=MagicMock(), user_id=uuid.uuid4())
    assert out["proposed"] == []
    assert "nothing to learn" in out["note"]


def test_synthesis_learns_from_failures_only():
    # no feedback — a recurring tool failure alone should drive a lesson
    from app.services import failure_memory
    failure_memory.record_failure(
        prompt="post the launch tweet", detail="401 Unauthorized from X API",
        category="tool_error", tool_name="twitter_post",
    )
    r = _router('{"lessons":[{"text":"Refresh the X token before posting",'
                '"source":"failure"}]}')
    out = lsyn.synthesize_lessons(router=r, user_id=uuid.uuid4())
    assert out["proposed"][0]["text"].startswith("Refresh")
    assert out["proposed"][0]["source"] == "failure"
    assert "1 failure" in out["note"]


def test_synthesis_learns_from_self_correction_only():
    # no feedback — a critic-caught + revised draft should drive a lesson
    from app.services.self_correction import loop as sc_loop
    with sc_loop.EVENTS_PATH.open("w") as fp:
        import json as _json
        fp.write(_json.dumps({
            "user_message": "summarize the audit", "was_revised": True,
            "final_severity": "major",
            "verdicts": [{"critique": "draft was far too long", "severity": "major"}],
        }) + "\n")
    r = _router('{"lessons":[{"text":"Keep summaries under 5 lines",'
                '"source":"self_correction"}]}')
    out = lsyn.synthesize_lessons(router=r, user_id=uuid.uuid4())
    assert out["proposed"][0]["source"] == "self_correction"
    assert "1 self-correction" in out["note"]


def test_synthesis_skips_ok_self_correction_events():
    # cheap-path events (ok / not revised) carry no signal → not fed → no learn
    from app.services.self_correction import loop as sc_loop
    with sc_loop.EVENTS_PATH.open("w") as fp:
        import json as _json
        fp.write(_json.dumps({
            "user_message": "hi", "was_revised": False, "final_severity": "none",
            "verdicts": [{"critique": "", "severity": "none"}],
        }) + "\n")
    out = lsyn.synthesize_lessons(router=MagicMock(), user_id=uuid.uuid4())
    assert out["proposed"] == []
    assert "nothing to learn" in out["note"]


def test_synthesis_invalid_source_defaults_mixed():
    ls.record_feedback(rating="down", note="x")
    r = _router('{"lessons":[{"text":"Do better","source":"banana"}]}')
    out = lsyn.synthesize_lessons(router=r, user_id=uuid.uuid4())
    assert out["proposed"][0]["source"] == "mixed"


def test_synthesis_can_disable_extra_sources():
    # a failure exists, but both extra sources are off and there's no feedback
    from app.services import failure_memory
    failure_memory.record_failure(prompt="x", detail="boom", category="tool_error")
    out = lsyn.synthesize_lessons(
        router=MagicMock(), user_id=uuid.uuid4(),
        include_failures=False, include_self_correction=False,
    )
    assert out["proposed"] == []
    assert "nothing to learn" in out["note"]


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


# ─── auto-tuning (evaluate_lessons) ──────────────────────────────────


def test_evaluate_no_active_lessons():
    ls.add_lesson("just proposed")  # proposed, not active
    out = ltun.evaluate_lessons()
    assert out["evaluated"] == [] and out["recommend_retire"] == []


def test_evaluate_insufficient_data():
    lesson = ls.add_lesson("x")
    ls.set_lesson_status(lesson.id, "active")  # active now, no feedback after
    out = ltun.evaluate_lessons()
    row = next(r for r in out["evaluated"] if r["id"] == lesson.id)
    assert row["verdict"] == "insufficient_data"
    assert row["recommend_retire"] is False


def test_evaluate_worsening_recommends_retire(monkeypatch):
    # before: 4 feedback, 1 down (25%)
    monkeypatch.setattr(ls, "_now", lambda: "2026-05-01T00:00:00+00:00")
    for _ in range(3):
        ls.record_feedback(rating="up")
    ls.record_feedback(rating="down")
    lesson = ls.add_lesson("be terse")
    # activate
    monkeypatch.setattr(ls, "_now", lambda: "2026-05-15T00:00:00+00:00")
    ls.set_lesson_status(lesson.id, "active")
    # after: 4 feedback, 3 down (75%) → down-rate rose → worsening
    monkeypatch.setattr(ls, "_now", lambda: "2026-05-20T00:00:00+00:00")
    for _ in range(3):
        ls.record_feedback(rating="down")
    ls.record_feedback(rating="up")
    out = ltun.evaluate_lessons(window_days=30, min_after_samples=3)
    row = next(r for r in out["evaluated"] if r["id"] == lesson.id)
    assert row["verdict"] == "worsening"
    assert row["recommend_retire"] is True
    assert lesson.id in out["recommend_retire"]


def test_evaluate_improving_keeps_lesson(monkeypatch):
    # before: 3/4 down (75%)
    monkeypatch.setattr(ls, "_now", lambda: "2026-05-01T00:00:00+00:00")
    for _ in range(3):
        ls.record_feedback(rating="down")
    ls.record_feedback(rating="up")
    lesson = ls.add_lesson("lead with the answer")
    monkeypatch.setattr(ls, "_now", lambda: "2026-05-15T00:00:00+00:00")
    ls.set_lesson_status(lesson.id, "active")
    # after: 1/4 down (25%) → down-rate fell → improving
    monkeypatch.setattr(ls, "_now", lambda: "2026-05-20T00:00:00+00:00")
    for _ in range(3):
        ls.record_feedback(rating="up")
    ls.record_feedback(rating="down")
    out = ltun.evaluate_lessons(window_days=30, min_after_samples=3)
    row = next(r for r in out["evaluated"] if r["id"] == lesson.id)
    assert row["verdict"] == "improving"
    assert row["recommend_retire"] is False


def test_activate_stamps_activated_at():
    lesson = ls.add_lesson("x")
    assert "activated_at" not in lesson.meta
    ls.set_lesson_status(lesson.id, "active")
    assert ls.get_lesson(lesson.id).meta.get("activated_at")


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


def test_tool_review_action():
    a = ls.add_lesson("Be concise"); ls.set_lesson_status(a.id, "active")
    out = LearningQueryTool().execute(_ctx(), action="review")
    assert out["action"] == "review" and "evaluated" in out and "caveat" in out


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


def test_admin_review_requires_token(client):
    assert client.get("/admin/learning/review").status_code == 403


def test_admin_review_returns_evaluation(client):
    a = ls.add_lesson("Be concise"); ls.set_lesson_status(a.id, "active")
    r = client.get("/admin/learning/review", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "evaluated" in body and "recommend_retire" in body and "caveat" in body


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
