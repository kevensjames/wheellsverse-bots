"""Continuous Research tests — sources (with mocked HTTP), scorer,
digest cycle, admin endpoints, scheduler lifecycle.

Real HTTP would make these flaky + slow. We mock at the urlopen seam
so the rest of the pipeline (parsing, scoring, persistence) gets
exercised honestly.
"""
from __future__ import annotations

import io
import json
import uuid
from unittest.mock import patch

import pytest

from app.config import settings
from app.services.research import sources, scorer
from app.services.research import digest as digest_mod
from app.services.research.scheduler import is_running, start, stop
from app.services.research.scorer import (
    HIGH_THRESHOLD,
    load_interests,
    score_item,
    severity,
)
from app.services.research.sources import Item

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_digests(tmp_path, monkeypatch):
    """Per-test JSONL so writes don't leak."""
    p = tmp_path / "digests.jsonl"
    monkeypatch.setattr(digest_mod, "DIGESTS_PATH", p)
    yield p


@pytest.fixture
def _scope_on(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_RESEARCH", "1")


# ─── scorer ─────────────────────────────────────────────────────────


def test_scorer_returns_zero_when_no_interests(monkeypatch):
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "")
    it = Item(source="hn", title="some title", url="x", summary="y")
    assert score_item(it, load_interests()) == 0.0


def test_scorer_single_token_match():
    it = Item(source="hn", title="A guide to FastAPI deployments", url="x", summary="")
    assert score_item(it, ["fastapi"]) == 1.0


def test_scorer_multi_token_phrase_needs_all_tokens():
    """'knowledge graph' counts as ONE hit only if both 'knowledge' AND
    'graph' appear in the item — not just one."""
    it_both = Item(source="hn", title="Building a knowledge graph", url="x", summary="")
    it_one = Item(source="hn", title="Graph databases at scale", url="x", summary="")
    assert score_item(it_both, ["knowledge-graph"]) == 1.0
    assert score_item(it_one, ["knowledge-graph"]) == 0.0


def test_scorer_score_is_fraction_of_interests_matched():
    it = Item(source="hn", title="LLM agents in production", url="x", summary="")
    score = score_item(it, ["llm", "fastapi", "kubernetes"])
    assert 0.30 < score < 0.40  # 1 of 3 ≈ 0.333


def test_scorer_short_and_stopword_tokens_ignored():
    it = Item(source="hn", title="the is a", url="x", summary="")
    assert score_item(it, ["the"]) == 0.0


def test_severity_buckets():
    assert severity(0.8) == "high"
    assert severity(0.3) == "medium"
    assert severity(0.05) == "low"
    assert severity(0.0) == "none"


def test_severity_at_thresholds():
    # The boundary lands in the higher bucket (>=)
    assert severity(HIGH_THRESHOLD) == "high"
    assert severity(scorer.MEDIUM_THRESHOLD) == "medium"


# ─── sources ────────────────────────────────────────────────────────


def _mock_urlopen(payload_map):
    """payload_map: dict[url_substring] -> (bytes, content_type). Calls
    to urlopen pick the longest matching url and return that payload."""
    def factory(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        best = ""
        for key in payload_map:
            if key in url and len(key) > len(best):
                best = key
        if not best:
            raise RuntimeError(f"no mock for {url}")
        payload = payload_map[best]
        class _Resp:
            def __init__(self, body):
                self._body = body
            def read(self):
                return self._body
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
        return _Resp(payload)
    return factory


def test_fetch_hn_parses_top_stories(monkeypatch):
    payload = {
        "/topstories.json": json.dumps([1, 2]).encode(),
        "/item/1.json": json.dumps({
            "type": "story", "title": "Big AI news", "url": "https://x.test",
            "score": 200, "descendants": 50, "by": "alice",
        }).encode(),
        "/item/2.json": json.dumps({
            "type": "story", "title": "Another thing", "url": "https://y.test",
            "score": 100, "descendants": 20,
        }).encode(),
    }
    with patch.object(sources.urllib.request, "urlopen", _mock_urlopen(payload)):
        items = sources.fetch_hn(top_n=2)
    assert len(items) == 2
    assert items[0].source == "hn"
    assert items[0].title == "Big AI news"
    assert items[0].url == "https://x.test"


def test_fetch_hn_skips_non_story(monkeypatch):
    payload = {
        "/topstories.json": json.dumps([1]).encode(),
        "/item/1.json": json.dumps({"type": "comment", "text": "nope"}).encode(),
    }
    with patch.object(sources.urllib.request, "urlopen", _mock_urlopen(payload)):
        items = sources.fetch_hn(top_n=1)
    assert items == []


def test_fetch_hn_network_error_returns_empty(monkeypatch):
    def boom(req, timeout=None):
        raise RuntimeError("network down")
    with patch.object(sources.urllib.request, "urlopen", boom):
        items = sources.fetch_hn(top_n=5)
    assert items == []


def test_parse_arxiv_atom_extracts_entries():
    xml = """<?xml version="1.0"?>
    <feed>
      <entry>
        <title>A new agent framework</title>
        <summary>We propose a multi-agent design.</summary>
        <id>http://arxiv.org/abs/2401.00001v1</id>
        <link href="http://arxiv.org/abs/2401.00001" rel="alternate"/>
      </entry>
      <entry>
        <title>Another paper</title>
        <summary>Some abstract.</summary>
        <id>http://arxiv.org/abs/2401.00002v1</id>
      </entry>
    </feed>"""
    items = sources._parse_arxiv_atom(xml)
    assert len(items) == 2
    assert items[0].title == "A new agent framework"
    assert "arxiv.org/abs/2401.00001" in items[0].url
    assert items[1].url.startswith("http://arxiv.org/abs/2401.00002")


def test_fetch_gh_trending_parses(monkeypatch):
    payload = {
        "api.github.com": json.dumps({
            "items": [
                {
                    "full_name": "operator/cool-tool",
                    "html_url": "https://github.com/operator/cool-tool",
                    "description": "Best new thing",
                    "stargazers_count": 1000,
                    "language": "Python",
                    "topics": ["ai-agents", "llm"],
                },
            ]
        }).encode(),
    }
    with patch.object(sources.urllib.request, "urlopen", _mock_urlopen(payload)):
        items = sources.fetch_gh_trending(window_days=1, top_n=5)
    assert len(items) == 1
    assert items[0].source == "gh_trending"
    assert items[0].metadata["stars"] == 1000
    assert "ai-agents" in items[0].metadata["topics"]


# ─── digest orchestrator ───────────────────────────────────────────


def test_run_research_cycle_with_all_sources_empty(monkeypatch):
    """All-empty cycle is recorded, no crash."""
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "")
    monkeypatch.setattr(digest_mod, "fetch_hn", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])
    d = digest_mod.run_research_cycle()
    assert d.total_items_fetched == 0
    assert d.high_count == 0
    assert d.top_by_source == {"hn": [], "arxiv": [], "gh_trending": []}


def test_run_research_cycle_scores_and_persists(monkeypatch, _isolated_digests):
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "llm,agent")
    monkeypatch.setattr(digest_mod, "fetch_hn", lambda: [
        Item(source="hn", title="LLM agent breakthrough", url="x", summary=""),
        Item(source="hn", title="Random other story", url="y", summary=""),
    ])
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])
    d = digest_mod.run_research_cycle()
    assert d.total_items_fetched == 2
    # First item matches both → score ~1.0
    hn_items = d.top_by_source["hn"]
    assert hn_items[0]["score"] >= 0.5
    assert hn_items[0]["severity"] == "high"
    assert d.high_count >= 1
    # Persisted
    assert _isolated_digests.exists()
    saved = json.loads(_isolated_digests.read_text().strip().split("\n")[0])
    assert saved["id"] == d.id


def test_run_research_cycle_isolates_source_failures(monkeypatch):
    """One failing source must not poison the digest."""
    def boom():
        raise RuntimeError("api down")
    monkeypatch.setattr(digest_mod, "fetch_hn", boom)
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [
        Item(source="arxiv", title="A paper", url="x", summary=""),
    ])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "")
    d = digest_mod.run_research_cycle()
    # HN bucket empty, arxiv has one
    assert d.top_by_source["hn"] == []
    assert len(d.top_by_source["arxiv"]) == 1


def test_telegram_alert_fired_on_high(monkeypatch):
    """When any item scores HIGH, the telegram helper gets called."""
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "agent")
    monkeypatch.setattr(digest_mod, "fetch_hn", lambda: [
        Item(source="hn", title="agent agent agent agent", url="x", summary=""),
    ])
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])

    sent = {"called": False}
    def fake_send(msg):
        sent["called"] = True
        sent["msg"] = msg
        return True
    from app.services.supreme import scanner as _supreme
    monkeypatch.setattr(_supreme, "telegram_send", fake_send)

    digest_mod.run_research_cycle()
    assert sent["called"] is True
    assert "KAI Research" in sent["msg"]


def test_telegram_not_called_when_no_high(monkeypatch):
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "nothing-matches-this")
    monkeypatch.setattr(digest_mod, "fetch_hn", lambda: [
        Item(source="hn", title="random unrelated topic", url="x", summary=""),
    ])
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])
    sent = {"called": False}
    from app.services.supreme import scanner as _supreme
    monkeypatch.setattr(_supreme, "telegram_send", lambda m: sent.update(called=True))

    digest_mod.run_research_cycle()
    assert sent["called"] is False


# ─── read side ──────────────────────────────────────────────────────


def test_list_digests_returns_summaries(monkeypatch):
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "")
    monkeypatch.setattr(digest_mod, "fetch_hn", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])
    digest_mod.run_research_cycle()
    digest_mod.run_research_cycle()
    rows = digest_mod.list_digests()
    assert len(rows) == 2
    # Summary shape — no full item lists
    assert "top_by_source" not in rows[0]
    assert "severity_counts" in rows[0]


def test_latest_digests_returns_full(monkeypatch):
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "")
    monkeypatch.setattr(digest_mod, "fetch_hn", lambda: [
        Item(source="hn", title="x", url="y", summary=""),
    ])
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])
    digest_mod.run_research_cycle()
    full = digest_mod.latest_digests(n=1)[0]
    assert "top_by_source" in full
    assert len(full["top_by_source"]["hn"]) == 1


def test_list_digests_empty_when_log_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(digest_mod, "DIGESTS_PATH", tmp_path / "never.jsonl")
    assert digest_mod.list_digests() == []


# ─── admin endpoints ───────────────────────────────────────────────


def test_admin_research_status_requires_token(client):
    r = client.get("/admin/research/status")
    assert r.status_code == 403


def test_admin_research_status_shape(client):
    r = client.get("/admin/research/status", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {
        "scheduler_running", "interests", "thresholds", "telegram_enabled",
    }
    assert body["thresholds"]["high"] == HIGH_THRESHOLD


def test_admin_research_digests_empty(client):
    r = client.get("/admin/research/digests", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"digests": []}


def test_admin_research_run_now(client, monkeypatch, _scope_on):
    monkeypatch.setenv("KAI_RESEARCH_INTERESTS", "")
    monkeypatch.setattr(digest_mod, "fetch_hn", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_arxiv", lambda: [])
    monkeypatch.setattr(digest_mod, "fetch_gh_trending", lambda: [])
    r = client.post("/admin/research/run-now", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert body["total_items_fetched"] == 0


def test_admin_research_run_now_requires_token(client):
    r = client.post("/admin/research/run-now")
    assert r.status_code == 403


def test_admin_research_latest_empty(client):
    r = client.get("/admin/research/latest", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"digest": None}


# ─── scheduler lifecycle ───────────────────────────────────────────


def test_scheduler_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KAI_RESEARCH_ENABLED", raising=False)
    stop()
    assert start() is False
    assert is_running() is False


def test_scheduler_starts_when_enabled(monkeypatch):
    """Start + immediately stop. We don't wait for the first cycle since
    that hits the network."""
    monkeypatch.setenv("KAI_RESEARCH_ENABLED", "1")
    # Make the cycle a no-op so the start->stop dance is fast
    monkeypatch.setattr(
        "app.services.research.scheduler.run_research_cycle",
        lambda: type("D", (), {"id": "20260610T000000Z"})(),
    )
    stop()
    try:
        assert start() is True
        assert is_running() is True
        assert start() is False  # idempotent
    finally:
        stop()
    assert is_running() is False
