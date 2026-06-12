"""KAI Supreme tests — scanner unit + storage + admin endpoints.

We don't run the real scanners against the operator's actual filesystem
in tests (would produce flaky results based on disk state). Instead we
exercise the orchestration layer with synthetic findings + mocked
SCANNER_REGISTRY for end-to-end paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.services.supreme import scanner as sc
from app.services.supreme import storage as st
from app.services.supreme.scanner import Finding


ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


# ─── data models ─────────────────────────────────────────────────────


def test_finding_defaults_have_discovered_at():
    f = Finding(id="x", severity="low", category="test", title="t", detail="d")
    assert f.discovered_at  # ISO timestamp set by default factory


def test_severity_levels_ordered():
    assert sc.SEVERITY_LEVELS["critical"] > sc.SEVERITY_LEVELS["high"]
    assert sc.SEVERITY_LEVELS["high"] > sc.SEVERITY_LEVELS["medium"]
    assert sc.SEVERITY_LEVELS["medium"] > sc.SEVERITY_LEVELS["low"]


# ─── map loader ──────────────────────────────────────────────────────


def test_load_map_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "MAP_PATH", tmp_path / "missing.yaml")
    assert sc.load_map() == {}


def test_load_map_parses_yaml(tmp_path, monkeypatch):
    map_path = tmp_path / "map.yaml"
    map_path.write_text(
        "version: 99\n"
        "last_updated: 2026-06-09\n"
        "supreme:\n"
        "  scan_interval_seconds: 60\n"
        "  scans: [process_health]\n"
    )
    monkeypatch.setattr(sc, "MAP_PATH", map_path)
    m = sc.load_map()
    assert m["version"] == 99
    assert m["supreme"]["scan_interval_seconds"] == 60


# ─── scan_once orchestration ─────────────────────────────────────────


def test_scan_once_isolates_scanner_failures(monkeypatch):
    """One crashing scanner must not block the others."""

    class GoodScanner(sc.Scanner):
        def scan(self):
            return [Finding(id="g1", severity="low", category="test", title="ok", detail="")]

    class BadScanner(sc.Scanner):
        def scan(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(sc, "SCANNER_REGISTRY", {
        "good": GoodScanner,
        "bad": BadScanner,
    })
    # Map opts both in
    findings = sc.scan_once({"supreme": {"scans": ["good", "bad"]}})
    assert len(findings) == 1
    assert findings[0].id == "g1"


def test_scan_once_respects_active_scans_filter(monkeypatch):
    """Only scanners listed in map.supreme.scans should run."""
    called = []

    class A(sc.Scanner):
        def scan(self):
            called.append("a")
            return []

    class B(sc.Scanner):
        def scan(self):
            called.append("b")
            return []

    monkeypatch.setattr(sc, "SCANNER_REGISTRY", {"a": A, "b": B})
    sc.scan_once({"supreme": {"scans": ["a"]}})
    assert called == ["a"]


def test_scan_once_runs_all_when_no_filter(monkeypatch):
    called = []

    class A(sc.Scanner):
        def scan(self):
            called.append("a")
            return []

    monkeypatch.setattr(sc, "SCANNER_REGISTRY", {"a": A})
    sc.scan_once({})  # no supreme.scans key → all
    assert called == ["a"]


# ─── proposal storage ────────────────────────────────────────────────


def test_save_proposal_writes_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    findings = [
        Finding(id="x", severity="high", category="test", title="t", detail="d"),
    ]
    path = sc.save_proposal(findings)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["finding_count"] == 1
    assert data["severity_counts"]["high"] == 1
    assert data["findings"][0]["id"] == "x"


def test_severity_counts_zero_when_no_findings():
    assert sc._severity_counts([]) == {"low": 0, "medium": 0, "high": 0, "critical": 0}


def test_severity_counts_groups_correctly():
    counts = sc._severity_counts([
        Finding(id="1", severity="low", category="t", title="t", detail=""),
        Finding(id="2", severity="low", category="t", title="t", detail=""),
        Finding(id="3", severity="critical", category="t", title="t", detail=""),
    ])
    assert counts == {"low": 2, "medium": 0, "high": 0, "critical": 1}


# ─── storage helpers ─────────────────────────────────────────────────


def _seed_proposal(dir_: Path, name: str, finding_count: int = 1, severity: str = "low"):
    p = dir_ / name
    p.write_text(json.dumps({
        "scanned_at": name.removeprefix("scan-").removesuffix(".json"),
        "finding_count": finding_count,
        "severity_counts": {severity: finding_count},
        "findings": [
            {"id": f"f{i}", "severity": severity, "category": "test",
             "title": "t", "detail": "d", "evidence": "", "proposed_fix": "",
             "auto_fixable": False, "discovered_at": "2026-06-09T00:00:00+00:00"}
            for i in range(finding_count)
        ],
    }))


def test_list_proposals_returns_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    _seed_proposal(tmp_path, "scan-20260601T120000Z.json")
    _seed_proposal(tmp_path, "scan-20260609T120000Z.json")
    out = st.list_proposals(limit=10)
    assert out[0]["name"] == "scan-20260609T120000Z.json"
    assert out[1]["name"] == "scan-20260601T120000Z.json"


def test_list_proposals_skips_bad_json(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    _seed_proposal(tmp_path, "scan-20260609T120000Z.json")
    (tmp_path / "scan-20260609T130000Z.json").write_text("{ not valid json")
    out = st.list_proposals()
    # Bad one skipped — good one survives
    assert len(out) == 1


def test_read_proposal_path_traversal_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    # All these MUST be rejected without touching disk
    assert st.read_proposal("../etc/passwd") is None
    assert st.read_proposal("/etc/passwd") is None
    assert st.read_proposal("..\\windows\\system32") is None
    # Even valid-looking but not scan- prefix
    assert st.read_proposal("other.json") is None


def test_read_proposal_returns_full_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    _seed_proposal(tmp_path, "scan-20260609T120000Z.json", finding_count=3)
    data = st.read_proposal("scan-20260609T120000Z.json")
    assert data is not None
    assert data["finding_count"] == 3
    assert len(data["findings"]) == 3


def test_latest_proposals_empty_when_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    assert st.latest_proposals(n=1) == []


# ─── telegram formatter ──────────────────────────────────────────────


def test_telegram_format_filters_below_threshold():
    findings = [
        Finding(id="1", severity="low", category="t", title="ignore me", detail=""),
        Finding(id="2", severity="high", category="t", title="show me", detail="d"),
    ]
    msg = sc.format_findings_for_telegram(findings, min_severity="medium")
    assert "show me" in msg
    assert "ignore me" not in msg


def test_telegram_format_returns_none_when_no_important():
    findings = [
        Finding(id="1", severity="low", category="t", title="t", detail=""),
    ]
    assert sc.format_findings_for_telegram(findings, "medium") is None


def test_telegram_format_uses_kai_branding():
    findings = [Finding(id="1", severity="high", category="t", title="t", detail="d")]
    msg = sc.format_findings_for_telegram(findings)
    # NarAI → KAI rename verified
    assert "KAI Supreme" in msg
    assert "NarAI" not in msg


# ─── admin endpoints ─────────────────────────────────────────────────


def test_admin_supreme_status_requires_token(client):
    r = client.get("/admin/supreme/status")
    assert r.status_code == 403


def test_admin_supreme_status_returns_shape(client):
    r = client.get("/admin/supreme/status", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {
        "scheduler_running", "scan_interval_seconds",
        "telegram_notify_severity", "active_scans",
        "map_loaded", "map_version",
    }
    # Scheduler shouldn't be running in tests (KAI_SUPREME_ENABLED not set)
    assert body["scheduler_running"] is False


def test_admin_supreme_latest_empty(client, tmp_path, monkeypatch):
    """No proposals on disk → returns {proposal: null} not a 404."""
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    r = client.get("/admin/supreme/latest", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["proposal"] is None


def test_admin_supreme_latest_with_data(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    _seed_proposal(tmp_path, "scan-20260609T120000Z.json", finding_count=2, severity="high")
    r = client.get("/admin/supreme/latest", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["proposal"]["finding_count"] == 2


def test_admin_supreme_history(client, tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)
    _seed_proposal(tmp_path, "scan-20260608T120000Z.json")
    _seed_proposal(tmp_path, "scan-20260609T120000Z.json")
    r = client.get("/admin/supreme/history?limit=5", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    rows = r.json()["proposals"]
    assert len(rows) == 2
    assert rows[0]["name"] == "scan-20260609T120000Z.json"


def test_admin_supreme_proposal_404_for_missing(client):
    r = client.get(
        "/admin/supreme/proposal/scan-99999999T000000Z.json",
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 404


def test_admin_supreme_proposal_404_for_traversal(client):
    """Path traversal attempts → 404 (storage layer rejects), not 500."""
    r = client.get(
        "/admin/supreme/proposal/..%2F..%2Fetc%2Fpasswd",
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 404


def test_admin_supreme_scan_now(client, tmp_path, monkeypatch):
    """Manual scan trigger writes a proposal + returns its name."""
    monkeypatch.setattr(sc, "PROPOSALS_DIR", tmp_path)
    monkeypatch.setattr(st, "PROPOSALS_DIR", tmp_path)

    # Use an empty scanner registry so we don't run real subprocess probes
    monkeypatch.setattr(sc, "SCANNER_REGISTRY", {})
    # Don't actually post to Telegram
    monkeypatch.setattr(sc, "telegram_send", lambda text: True)
    monkeypatch.setattr(sc, "load_map", lambda: {})

    r = client.post("/admin/supreme/scan", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["finding_count"] == 0
    assert body["proposal_name"].startswith("scan-")
    # Proposal actually written
    assert (tmp_path / body["proposal_name"]).exists()


def test_admin_supreme_scan_requires_token(client):
    r = client.post("/admin/supreme/scan")
    assert r.status_code == 403


# ─── scheduler ───────────────────────────────────────────────────────


def test_scheduler_disabled_by_default(monkeypatch):
    from app.services.supreme import scheduler
    monkeypatch.delenv("KAI_SUPREME_ENABLED", raising=False)
    scheduler.stop()  # ensure clean slate
    assert scheduler.start() is False
    assert scheduler.is_running() is False


def test_scheduler_starts_when_enabled(monkeypatch):
    from app.services.supreme import scheduler
    monkeypatch.setenv("KAI_SUPREME_ENABLED", "1")
    # Patch run_full_cycle so the thread doesn't actually scan
    monkeypatch.setattr(scheduler, "run_full_cycle", lambda smap=None: (None, []))
    monkeypatch.setattr(scheduler, "load_map", lambda: {"supreme": {"scan_interval_seconds": 9999}})

    scheduler.stop()  # ensure clean slate
    try:
        assert scheduler.start() is True
        assert scheduler.is_running() is True
        # Second start is a no-op
        assert scheduler.start() is False
    finally:
        scheduler.stop()
    assert scheduler.is_running() is False
