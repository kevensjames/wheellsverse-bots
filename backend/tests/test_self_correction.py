"""Self-correction tests — critic parsing, reviser fallback, loop control
flow, persistence, admin endpoints, and chat integration.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.self_correction import (
    CorrectionResult,
    Verdict,
    critique,
    revise,
    run_correction_loop,
)
from app.services.self_correction import loop as sc_loop
from app.services.self_correction.critic import _parse_verdict

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_events(tmp_path, monkeypatch):
    """Per-test events log so writes don't leak."""
    p = tmp_path / "events.jsonl"
    monkeypatch.setattr(sc_loop, "EVENTS_PATH", p)
    yield p


# ─── critic JSON parsing ───────────────────────────────────────────


def test_parse_clean_json():
    v = _parse_verdict(
        '{"ok": true, "severity": "minor", '
        '"critique": "small typo", "suggestions": ["fix typo"]}'
    )
    assert v.ok is True
    assert v.severity == "minor"
    assert v.critique == "small typo"
    assert v.suggestions == ["fix typo"]


def test_parse_strips_code_fence():
    v = _parse_verdict('```json\n{"ok": true, "severity": "none", "critique": "x"}\n```')
    assert v.ok is True
    assert v.severity == "none"


def test_parse_finds_json_in_prose():
    raw = (
        "Sure, here is my verdict:\n"
        '{"ok": false, "severity": "major", '
        '"critique": "off-topic", "suggestions": []}\n\nThanks!'
    )
    v = _parse_verdict(raw)
    assert v.ok is False
    assert v.severity == "major"
    assert v.needs_revision is True


def test_parse_handles_nested_braces():
    raw = (
        '{"ok": false, "severity": "critical", '
        '"critique": "the format `{foo: bar}` is wrong", '
        '"suggestions": []}'
    )
    v = _parse_verdict(raw)
    assert v.severity == "critical"
    assert "{foo: bar}" in v.critique


def test_parse_unknown_severity_normalized():
    v = _parse_verdict(
        '{"ok": true, "severity": "fatal", "critique": "x", "suggestions": []}'
    )
    assert v.severity == "none"  # bogus severity → safe default


def test_parse_empty_text_fail_open():
    v = _parse_verdict("")
    assert v.ok is True
    assert v.severity == "none"


def test_parse_non_json_fail_open():
    """If the critic returns prose with no JSON block, accept the draft."""
    v = _parse_verdict("The draft is fine.")
    assert v.ok is True


def test_parse_malformed_json_fail_open():
    v = _parse_verdict('{"ok": true, "severity":')  # truncated
    assert v.ok is True
    # critique should mention the parse failure for the audit trail
    assert "unparseable" in v.critique or "non-JSON" in v.critique


# ─── Verdict.needs_revision ─────────────────────────────────────────


def test_needs_revision_only_when_major_or_critical():
    assert Verdict(ok=False, severity="major", critique="").needs_revision is True
    assert Verdict(ok=False, severity="critical", critique="").needs_revision is True
    assert Verdict(ok=False, severity="minor", critique="").needs_revision is False
    assert Verdict(ok=True, severity="none", critique="").needs_revision is False


# ─── critic / reviser with mocked adapter ──────────────────────────


def _make_router(adapter_response_text: str, *, cost: float = 0.001):
    """Build a router whose first cloudflare adapter returns the given text."""
    adapter = MagicMock()
    adapter.name = "cloudflare"
    adapter.model = "llama-3-8b"
    adapter.complete.return_value = SimpleNamespace(
        content=adapter_response_text,
        tool_calls=None,
        total_cost_usd=cost,
    )
    return SimpleNamespace(adapters={"cloudflare": adapter}), adapter


def test_critique_calls_cheap_adapter(monkeypatch):
    router, adapter = _make_router(
        '{"ok": true, "severity": "none", "critique": "perfect"}'
    )
    v, cost = critique(
        user_message="say hi",
        draft_response="Hi!",
        router=router,
    )
    assert adapter.complete.called
    assert v.ok is True
    assert cost == 0.001


def test_critique_adapter_crash_fail_open(monkeypatch):
    router, adapter = _make_router("ignored")
    adapter.complete.side_effect = RuntimeError("network down")
    v, cost = critique(
        user_message="say hi", draft_response="Hi!", router=router,
    )
    assert v.ok is True  # fail-open: bad critic must not block reply
    assert cost == 0.0


def test_revise_uses_original_adapter():
    """Reviser quality must match the draft's quality → reuse same adapter."""
    router, _ = _make_router("ignored")
    original_adapter = MagicMock()
    original_adapter.complete.return_value = SimpleNamespace(
        content="Revised reply.", total_cost_usd=0.005,
    )
    revised, cost = revise(
        user_message="say hi",
        draft_response="Hi.",
        verdict=Verdict(
            ok=False, severity="major", critique="too terse",
            suggestions=["expand", "add greeting"],
        ),
        router=router,
        original_adapter=original_adapter,
    )
    assert revised == "Revised reply."
    assert cost == 0.005


def test_revise_failure_returns_draft_unchanged():
    router, _ = _make_router("ignored")
    original_adapter = MagicMock()
    original_adapter.complete.side_effect = RuntimeError("ratelimit")
    revised, cost = revise(
        user_message="x", draft_response="original draft",
        verdict=Verdict(ok=False, severity="major", critique="bad"),
        router=router, original_adapter=original_adapter,
    )
    assert revised == "original draft"  # fail-open
    assert cost == 0.0


def test_revise_empty_response_falls_back():
    router, _ = _make_router("ignored")
    original_adapter = MagicMock()
    original_adapter.complete.return_value = SimpleNamespace(
        content="", total_cost_usd=0.001,
    )
    revised, cost = revise(
        user_message="x", draft_response="original",
        verdict=Verdict(ok=False, severity="major", critique="bad"),
        router=router, original_adapter=original_adapter,
    )
    assert revised == "original"


# ─── correction loop control flow ──────────────────────────────────


def test_loop_skips_revision_when_ok():
    """ok verdict → no revise call, single iteration."""
    router, critic_adapter = _make_router(
        '{"ok": true, "severity": "none", "critique": "perfect"}'
    )
    original_adapter = MagicMock()
    result = run_correction_loop(
        user_message="hi",
        initial_draft="Hello!",
        router=router,
        original_adapter=original_adapter,
        max_iterations=2,
    )
    assert result.iterations == 1
    assert result.was_revised is False
    assert result.final_text == "Hello!"
    assert not original_adapter.complete.called  # reviser never invoked


def test_loop_revises_on_major_verdict():
    """major verdict → revise once, then accept revised (within max_iterations=1)."""
    router, critic_adapter = _make_router(
        '{"ok": false, "severity": "major", '
        '"critique": "off-topic", "suggestions": ["focus"]}'
    )
    original_adapter = MagicMock()
    original_adapter.complete.return_value = SimpleNamespace(
        content="Better reply", total_cost_usd=0.01,
    )
    result = run_correction_loop(
        user_message="explain decorators",
        initial_draft="Pizza is great.",
        router=router,
        original_adapter=original_adapter,
        max_iterations=1,
    )
    assert result.was_revised is True
    assert result.final_text == "Better reply"
    assert result.iterations == 1


def test_loop_max_iterations_capped_at_three():
    """Hard cap so a stuck loop can't burn the budget."""
    router, _ = _make_router(
        '{"ok": false, "severity": "critical", "critique": "still bad"}'
    )
    original_adapter = MagicMock()
    original_adapter.complete.return_value = SimpleNamespace(
        content="still bad attempt", total_cost_usd=0.001,
    )
    result = run_correction_loop(
        user_message="x",
        initial_draft="y",
        router=router,
        original_adapter=original_adapter,
        max_iterations=100,  # asked for 100…
    )
    assert result.iterations <= 3  # …capped at 3


def test_loop_persists_event(_isolated_events):
    router, _ = _make_router(
        '{"ok": true, "severity": "none", "critique": "ok"}'
    )
    run_correction_loop(
        user_message="say hi",
        initial_draft="Hi.",
        router=router,
        original_adapter=MagicMock(),
    )
    assert _isolated_events.exists()
    rows = _isolated_events.read_text().strip().split("\n")
    assert len(rows) == 1
    event = json.loads(rows[0])
    assert event["iterations"] == 1
    assert event["was_revised"] is False
    assert event["final_severity"] == "none"


def test_loop_critic_crash_returns_draft(_isolated_events):
    router, adapter = _make_router("ignored")
    adapter.complete.side_effect = RuntimeError("boom")
    result = run_correction_loop(
        user_message="x",
        initial_draft="original",
        router=router,
        original_adapter=MagicMock(),
    )
    # Critic crashed → fail-open path inside critique() returns
    # ok-verdict; loop sees ok, exits without revising
    assert result.final_text == "original"
    assert result.was_revised is False


# ─── stats summary ─────────────────────────────────────────────────


def test_stats_summary_empty():
    s = sc_loop.stats_summary()
    assert s["total_recent"] == 0
    assert s["revisions_applied"] == 0


def test_stats_summary_aggregates(_isolated_events):
    # Seed a few events
    router, _ = _make_router(
        '{"ok": true, "severity": "none", "critique": "ok"}'
    )
    for _ in range(3):
        run_correction_loop(
            user_message="x", initial_draft="y",
            router=router, original_adapter=MagicMock(),
        )
    s = sc_loop.stats_summary()
    assert s["total_recent"] == 3
    assert s["avg_iterations"] == 1.0


# ─── admin endpoints ───────────────────────────────────────────────


def test_admin_stats_requires_token(client):
    r = client.get("/admin/self-correction/stats")
    assert r.status_code == 403


def test_admin_stats_empty(client):
    r = client.get("/admin/self-correction/stats", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["total_recent"] == 0


def test_admin_events_empty(client):
    r = client.get("/admin/self-correction/events", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"count": 0, "events": []}


def test_admin_latest_returns_null_when_empty(client):
    r = client.get("/admin/self-correction/latest", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"event": None}


def test_admin_events_after_run(client, _isolated_events):
    router, _ = _make_router(
        '{"ok": true, "severity": "none", "critique": "ok"}'
    )
    run_correction_loop(
        user_message="hello",
        initial_draft="Hi.",
        router=router,
        original_adapter=MagicMock(),
    )
    r = client.get("/admin/self-correction/events", headers=ADMIN_HEADERS)
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["iterations"] == 1
    assert body["events"][0]["final_severity"] == "none"
