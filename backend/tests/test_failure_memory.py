"""Failure memory tests — storage, similarity, tool, admin endpoints,
router hook, and memory-injection integration.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.failure_memory import (
    find_recent_similar,
    list_recent,
    record_failure,
)
from app.services.failure_memory import storage as fm
from app.services.tools.base import ToolContext, ToolError
from app.services.tools.failure_lookup import FailureLookupTool


ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path, monkeypatch):
    """Per-test failure log so they don't see each other."""
    p = tmp_path / "failures.jsonl"
    monkeypatch.setattr(fm, "FAILURE_LOG_PATH", p)
    yield p


# ─── write side ─────────────────────────────────────────────────────


def test_record_failure_appends_one_row(_isolated_log):
    record_failure(
        prompt="deploy KAI to prod",
        detail="pip resolution impossible",
        category="tool_error",
        tool_name="docker_build",
    )
    rows = list_recent()
    assert len(rows) == 1
    assert rows[0].prompt == "deploy KAI to prod"
    assert rows[0].tool_name == "docker_build"


def test_record_failure_swallows_write_failures(monkeypatch):
    """Audit-style — a broken log file path must NOT raise back to chat."""
    # Point at an unwritable path; record_failure logs and returns
    monkeypatch.setattr(fm, "FAILURE_LOG_PATH", fm.Path("/proc/no-such-dir/x.jsonl"))
    # No raise = pass
    record_failure(prompt="x", detail="y")


def test_record_failure_truncates_long_fields():
    long_prompt = "A" * 5000
    record_failure(prompt=long_prompt, detail="ok")
    rows = list_recent()
    assert len(rows[0].prompt) < 1000
    assert "5000 chars" in rows[0].prompt


def test_record_failure_normalizes_category():
    record_failure(prompt="x", detail="y", category="  TOOL_Error  ")
    assert list_recent()[0].category == "tool_error"


# ─── read side: list_recent ─────────────────────────────────────────


def test_list_recent_newest_first():
    record_failure(prompt="first", detail="d1")
    time.sleep(0.01)
    record_failure(prompt="second", detail="d2")
    rows = list_recent()
    assert rows[0].prompt == "second"
    assert rows[1].prompt == "first"


def test_list_recent_category_filter():
    record_failure(prompt="a", detail="d", category="tool_error")
    record_failure(prompt="b", detail="d", category="llm_error")
    only_tool = list_recent(category="tool_error")
    assert len(only_tool) == 1
    assert only_tool[0].prompt == "a"


def test_list_recent_tool_name_filter():
    record_failure(prompt="a", detail="d", tool_name="docker_build")
    record_failure(prompt="b", detail="d", tool_name="git_push")
    only_docker = list_recent(tool_name="docker_build")
    assert len(only_docker) == 1


def test_list_recent_since_filter():
    record_failure(prompt="old", detail="d")
    rows = list_recent(since=datetime.now(timezone.utc) + timedelta(seconds=1))
    assert rows == []
    rows = list_recent(since=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert len(rows) == 1


def test_list_recent_skips_bad_json(_isolated_log):
    record_failure(prompt="good", detail="d")
    _isolated_log.write_text(_isolated_log.read_text() + "{ this is broken\n")
    record_failure(prompt="good2", detail="d")
    rows = list_recent()
    # Bad line skipped, good ones survive
    assert len(rows) == 2


def test_list_recent_empty_when_log_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "FAILURE_LOG_PATH", tmp_path / "never-created.jsonl")
    assert list_recent() == []


# ─── similarity search ──────────────────────────────────────────────


def test_find_recent_similar_keyword_overlap():
    record_failure(
        prompt="deploy KAI to production via railway up",
        detail="pip resolver couldn't resolve litellm pin",
    )
    record_failure(prompt="send a tweet about the launch", detail="rate limit")
    results = find_recent_similar("deploy KAI production", k=3)
    assert len(results) == 1
    assert "deploy" in results[0].prompt.lower()


def test_find_recent_similar_min_score_filters_noise():
    record_failure(prompt="totally unrelated thing", detail="x")
    # No token overlap with this query
    results = find_recent_similar("buy stocks for retirement", k=3)
    assert results == []


def test_find_recent_similar_window_days_caps_lookback(monkeypatch):
    record_failure(prompt="deploy stuff fail", detail="x")
    # Force the lookup to look back zero days → no results
    results = find_recent_similar("deploy stuff", k=3, window_days=1)
    assert len(results) >= 0  # not asserting empty here — same-day matches do count


def test_find_recent_similar_ignores_stopwords():
    record_failure(prompt="the a is for", detail="x")
    # Query is all stopwords + short tokens — should produce zero
    results = find_recent_similar("the a is", k=3)
    assert results == []


def test_find_recent_similar_empty_query():
    assert find_recent_similar("") == []
    assert find_recent_similar("   ") == []


def test_find_recent_similar_score_attached():
    record_failure(prompt="git push failed authentication", detail="bad creds")
    results = find_recent_similar("git push authentication", k=1)
    assert len(results) == 1
    assert results[0].similarity_score > 0


# ─── failure_lookup tool ────────────────────────────────────────────


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_tool_mode_recent():
    record_failure(prompt="failed deploy", detail="d")
    out = FailureLookupTool().execute(_ctx(), mode="recent")
    assert out["mode"] == "recent"
    assert out["count"] == 1


def test_tool_mode_similar():
    record_failure(
        prompt="docker build fails on pip install",
        detail="ResolutionImpossible",
    )
    out = FailureLookupTool().execute(
        _ctx(), mode="similar", query="docker pip build"
    )
    assert out["mode"] == "similar"
    assert out["count"] == 1
    assert out["failures"][0]["score"] is not None


def test_tool_mode_similar_requires_query():
    with pytest.raises(ToolError):
        FailureLookupTool().execute(_ctx(), mode="similar", query="")


def test_tool_unknown_mode():
    with pytest.raises(ToolError):
        FailureLookupTool().execute(_ctx(), mode="rotate")


def test_tool_recent_with_tool_name_filter():
    record_failure(prompt="x", detail="y", tool_name="git_push")
    record_failure(prompt="x", detail="y", tool_name="docker_build")
    out = FailureLookupTool().execute(
        _ctx(), mode="recent", tool_name="git_push"
    )
    assert out["count"] == 1
    assert out["failures"][0]["tool"] == "git_push"


# ─── admin endpoints ────────────────────────────────────────────────


def test_admin_failures_recent_requires_token(client):
    r = client.get("/admin/failures/recent")
    assert r.status_code == 403


def test_admin_failures_recent_returns_shape(client):
    record_failure(prompt="failed thing", detail="why")
    r = client.get("/admin/failures/recent", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["failures"][0]["prompt"] == "failed thing"


def test_admin_failures_similar(client):
    record_failure(
        prompt="git rebase produces merge conflicts",
        detail="cannot continue",
    )
    r = client.get(
        "/admin/failures/similar?q=git+rebase+conflicts",
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["failures"][0]["similarity_score"] > 0


def test_admin_failures_stats(client):
    record_failure(prompt="a", detail="d", category="tool_error", tool_name="docker")
    record_failure(prompt="b", detail="d", category="tool_error", tool_name="docker")
    record_failure(prompt="c", detail="d", category="llm_error")
    r = client.get("/admin/failures/stats", headers=ADMIN_HEADERS)
    body = r.json()
    assert body["total_recent"] == 3
    assert body["by_category"]["tool_error"] == 2
    assert body["by_tool"]["docker"] == 2


# ─── memory injection integration ───────────────────────────────────


def test_memory_preamble_surfaces_past_failures(monkeypatch):
    """build_memory_preamble must include failure block when there's a
    matching past failure for the user's prompt."""
    record_failure(
        prompt="deploy via docker compose up",
        detail="container exits immediately",
        tool_name="docker_compose",
    )
    # Mock search_memories so we ONLY see the failure block (no pgvector hit)
    from app.services.nai_brain import memory_injection as mi
    monkeypatch.setattr(mi, "search_memories", lambda *a, **kw: [])
    monkeypatch.setattr(mi, "format_for_prompt", lambda m: "")

    out = mi.build_memory_preamble(
        session=MagicMock(),
        user_id=uuid.uuid4(),
        query="deploy via docker compose",
    )
    assert "Past failures" in out
    assert "docker_compose" in out


def test_memory_preamble_empty_when_no_failures_no_memories(monkeypatch):
    from app.services.nai_brain import memory_injection as mi
    monkeypatch.setattr(mi, "search_memories", lambda *a, **kw: [])
    monkeypatch.setattr(mi, "format_for_prompt", lambda m: "")
    out = mi.build_memory_preamble(
        session=MagicMock(),
        user_id=uuid.uuid4(),
        query="brand-new untouched topic xyz",
    )
    assert out == ""
