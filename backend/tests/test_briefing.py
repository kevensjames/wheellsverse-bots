"""Daily Brief endpoint + service tests.

The service itself is exercised via the endpoint — it's a thin wrapper.
We mock the audit log path to keep tests hermetic.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.governance import audit_log as al
from app.services import briefing as br
from app.services.briefing import daily_brief as db_module


ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    """Isolated audit log per test so briefing actions don't pollute the
    real data/governance/audit.jsonl."""
    monkeypatch.setattr(al, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


@pytest.fixture
def _scope_enabled(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_BRIEFING_DAILY", "1")


# ─── auth gate ───────────────────────────────────────────────────────


def test_briefing_generate_requires_token(client):
    r = client.post("/admin/briefing/generate")
    assert r.status_code == 403


# ─── scope gate ──────────────────────────────────────────────────────


def test_briefing_returns_403_when_scope_disabled(client, monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_BRIEFING_DAILY", raising=False)
    monkeypatch.delenv("KAI_SCOPE_BRIEFING", raising=False)
    r = client.post("/admin/briefing/generate", headers=ADMIN_HEADERS)
    assert r.status_code == 403
    detail = r.json().get("detail", "")
    assert "KAI_SCOPE_BRIEFING_DAILY" in detail or "Scope" in detail


# ─── happy path ──────────────────────────────────────────────────────


def test_briefing_generates_shape(client, _scope_enabled, monkeypatch):
    # Mock latest_proposals so we don't depend on real Supreme scans
    monkeypatch.setattr(db_module, "latest_proposals", lambda n=1: [])
    r = client.post("/admin/briefing/generate", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    for key in ("generated_at", "users", "revenue", "spend", "scanner",
                "errors", "headline"):
        assert key in body
    # Empty DB → empty shape, never crashes
    assert isinstance(body["users"]["total"], int)
    assert isinstance(body["spend"]["today_usd"], (int, float))
    assert isinstance(body["headline"], str) and body["headline"]


def test_briefing_surfaces_supreme_headline_findings(
    client, _scope_enabled, monkeypatch
):
    fake_scan = {
        "scanned_at": "20260609T080000Z",
        "finding_count": 2,
        "severity_counts": {"low": 0, "medium": 0, "high": 1, "critical": 1},
        "findings": [
            {"severity": "critical", "title": "Disk 95% full", "category": "disk_space"},
            {"severity": "high",     "title": ".env missing supabase keys", "category": "env_completeness"},
            {"severity": "low",      "title": "minor thing", "category": "x"},  # filtered out
        ],
    }
    monkeypatch.setattr(db_module, "latest_proposals", lambda n=1: [fake_scan])
    r = client.post("/admin/briefing/generate", headers=ADMIN_HEADERS)
    sc = r.json()["scanner"]
    assert sc["has_scan"] is True
    titles = [f["title"] for f in sc["headline_findings"]]
    assert "Disk 95% full" in titles
    assert ".env missing supabase keys" in titles
    # Low severity filtered out
    assert "minor thing" not in titles
    # Headline should mention the high+ count
    assert "⚠️" in r.json()["headline"]


def test_briefing_headline_clean_when_no_high_findings(
    client, _scope_enabled, monkeypatch
):
    monkeypatch.setattr(db_module, "latest_proposals", lambda n=1: [
        {"severity_counts": {"low": 5}, "findings": []},
    ])
    r = client.post("/admin/briefing/generate", headers=ADMIN_HEADERS)
    assert "✓ scanner clean" in r.json()["headline"]


# ─── audit-log integration ───────────────────────────────────────────


def test_briefing_writes_audit_entry(client, _scope_enabled, monkeypatch):
    from app.services import governance
    monkeypatch.setattr(db_module, "latest_proposals", lambda n=1: [])
    r = client.post("/admin/briefing/generate", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    rows = governance.list_actions(scope="briefing.daily")
    assert len(rows) == 1
    assert rows[0]["success"] is True
    assert rows[0]["destructive"] is False
    assert rows[0]["scope"] == "briefing.daily"


def test_audit_endpoint_returns_recent(client, _scope_enabled, monkeypatch):
    monkeypatch.setattr(db_module, "latest_proposals", lambda n=1: [])
    client.post("/admin/briefing/generate", headers=ADMIN_HEADERS)
    client.post("/admin/briefing/generate", headers=ADMIN_HEADERS)
    r = client.get("/admin/briefing/audit?limit=10", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    actions = r.json()["actions"]
    # Both briefings logged + newest first
    assert len(actions) >= 2
    for a in actions[:2]:
        assert a["scope"] == "briefing.daily"


def test_audit_endpoint_requires_token(client):
    r = client.get("/admin/briefing/audit")
    assert r.status_code == 403


# ─── module export ───────────────────────────────────────────────────


def test_briefing_package_exports_generator():
    assert callable(br.generate_daily_brief)
