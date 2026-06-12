"""KAI self-audit tests: auditor structure + store counting + scope reflection,
the admin endpoint auth + shape, and the audit_query tool.
"""
from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.audit import auditor

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture
def _fake_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(auditor, "DATA_ROOT", tmp_path)
    # planning sqlite store with 2 plans
    (tmp_path / "planning").mkdir()
    con = sqlite3.connect(tmp_path / "planning" / "planning.db")
    con.execute("CREATE TABLE plans (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO plans DEFAULT VALUES")
    con.execute("INSERT INTO plans DEFAULT VALUES")
    con.commit(); con.close()
    # governance jsonl store with 3 lines
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "audit.jsonl").write_text('{"a":1}\n{"a":2}\n{"a":3}\n')
    yield tmp_path


def test_run_audit_structure(_fake_data_root):
    a = auditor.run_audit()
    assert set(a) >= {"generated_at", "summary", "runtime", "subsystems", "issues"}
    assert a["summary"]["subsystems_total"] == len(auditor.SUBSYSTEMS)
    names = {s["name"] for s in a["subsystems"]}
    assert "Long-term planning" in names and "Digital twin" in names


def test_audit_counts_sqlite_and_jsonl(_fake_data_root):
    a = auditor.run_audit()
    by_key = {s["key"]: s for s in a["subsystems"]}
    assert by_key["planning"]["records"] == 2 and by_key["planning"]["store_exists"] is True
    assert by_key["governance"]["records"] == 3
    # a store that doesn't exist in the fake root
    assert by_key["kg"]["store_exists"] is False and by_key["kg"]["records"] == 0


def test_audit_reflects_scope_env(_fake_data_root, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_PLANNING", "1")
    monkeypatch.delenv("KAI_SCOPE_TWIN", raising=False)
    a = auditor.run_audit()
    by_key = {s["key"]: s for s in a["subsystems"]}
    assert by_key["planning"]["scope_enabled"] is True
    assert by_key["twin"]["scope_enabled"] is False
    # an OFF scope shows up as an issue
    assert any("Digital twin" in i for i in a["issues"])


def test_audit_runtime_reports_keys(_fake_data_root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    a = auditor.run_audit()
    assert a["runtime"]["openai_key_set"] is True


# ─── endpoint ────────────────────────────────────────────────────────


def test_admin_audit_requires_token(client):
    assert client.get("/admin/audit/run").status_code == 403


def test_admin_audit_returns_report(client):
    r = client.get("/admin/audit/run", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body and "subsystems" in body and "issues" in body
    assert body["summary"]["subsystems_total"] >= 12


# ─── tool ────────────────────────────────────────────────────────────


def test_audit_query_tool(_fake_data_root):
    from app.services.tools.audit_query import AuditQueryTool
    from app.services.tools.base import ToolContext
    out = AuditQueryTool().execute(ToolContext(user_id=uuid.uuid4(), session=MagicMock()))
    assert "summary" in out and "subsystems" in out and "issues" in out
    assert isinstance(out["enabled"], list)
