"""github_scout — read-only GitHub repo search + adoption assessment. Mocks
urllib (no network); payloads mirror the GitHub Search API repo shape. Asserts
the assessment logic (license class, maintenance, risk flags, recommendation),
the safety-first ranking, and that the Self-Improvement Scout preset is wired."""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools import github_scout as gs
from app.services.tools.base import ToolContext, ToolError
from app.services.tools.github_scout import GithubScoutTool


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def _repo(**over):
    base = {
        "full_name": "All-Hands-AI/OpenHands",
        "description": "Autonomous software engineering agents",
        "html_url": "https://github.com/All-Hands-AI/OpenHands",
        "language": "Python",
        "topics": ["agent", "llm", "autonomous"],
        "pushed_at": "2026-05-01T00:00:00Z",
        "stargazers_count": 40000,
        "archived": False,
        "license": {"spdx_id": "MIT"},
    }
    base.update(over)
    return base


def test_parses_and_assesses(monkeypatch):
    monkeypatch.setattr(gs, "_months_since", lambda ts: 2.0)
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"items": [_repo()]}))
    out = GithubScoutTool().execute(_ctx(), query="autonomous agent framework")
    assert out["count"] == 1
    r = out["results"][0]
    assert r["repo"] == "All-Hands-AI/OpenHands"
    assert "permissive" in r["license"]
    assert r["maintained"] is True
    assert r["recommendation"] == "evaluate"
    assert r["risk_flags"] == []
    assert "DISCOVERY ONLY" in out["note"]


def test_no_license_is_blocker_and_avoided(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"items": [_repo(license=None)]}))
    r = GithubScoutTool().execute(_ctx(), query="x")["results"][0]
    assert r["recommendation"] == "avoid"
    assert any("legal blocker" in f for f in r["risk_flags"])


def test_archived_is_avoided(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"items": [_repo(archived=True)]}))
    r = GithubScoutTool().execute(_ctx(), query="x")["results"][0]
    assert r["recommendation"] == "avoid"
    assert any("archived" in f for f in r["risk_flags"])


def test_copyleft_is_caution(monkeypatch):
    monkeypatch.setattr(gs, "_months_since", lambda ts: 2.0)
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"items": [_repo(license={"spdx_id": "AGPL-3.0"})]}))
    r = GithubScoutTool().execute(_ctx(), query="x")["results"][0]
    assert r["recommendation"] == "caution"
    assert any("copyleft" in f for f in r["risk_flags"])


def test_stale_is_caution(monkeypatch):
    # ancient push date → stale regardless of when the test runs
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"items": [_repo(pushed_at="2015-01-01T00:00:00Z")]}))
    r = GithubScoutTool().execute(_ctx(), query="x")["results"][0]
    assert r["recommendation"] == "caution"
    assert any("stale" in f for f in r["risk_flags"])


def test_ranks_evaluate_above_avoid(monkeypatch):
    monkeypatch.setattr(gs, "_months_since", lambda ts: 2.0)
    payload = {"items": [
        _repo(full_name="bad/archived", archived=True, stargazers_count=99999),
        _repo(full_name="good/healthy", stargazers_count=500),
    ]}
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Resp(payload))
    out = GithubScoutTool().execute(_ctx(), query="x")
    # healthy repo ranks first despite ~200x fewer stars (archived → avoid tier)
    assert out["results"][0]["repo"] == "good/healthy"
    assert out["results"][1]["repo"] == "bad/archived"


def test_blank_query_raises():
    with pytest.raises(ToolError):
        GithubScoutTool().execute(_ctx(), query="  ")


def test_network_failure_raises(monkeypatch):
    def _boom(req, timeout=None):
        raise RuntimeError("github down")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(ToolError):
        GithubScoutTool().execute(_ctx(), query="x")


def test_no_results(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Resp({"items": []}))
    out = GithubScoutTool().execute(_ctx(), query="zzz")
    assert out["count"] == 0 and out["results"] == []
    assert "No repositories matched" in out["note"]


def test_qualifiers_in_query(monkeypatch):
    captured = {}

    def _cap(req, timeout=None):
        captured["url"] = req.full_url
        return _Resp({"items": []})
    monkeypatch.setattr("urllib.request.urlopen", _cap)
    GithubScoutTool().execute(_ctx(), query="agents", language="python", min_stars=250)
    assert "stars" in captured["url"] and "language" in captured["url"]


def test_preset_registered():
    from app.services.presets.registry import get_preset
    p = get_preset("self_improvement")
    assert p is not None
    assert "github_scout" in p.tool_whitelist
    assert "audit_query" in p.tool_whitelist
