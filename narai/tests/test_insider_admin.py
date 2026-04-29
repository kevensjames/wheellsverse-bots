"""Tests for insider_admin: lead capture + admin auth gate."""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh leads DB + isolated env per test."""
    db = tmp_path / "leads.db"
    monkeypatch.setenv("INSIDER_LEADS_DB_PATH", str(db))
    # No admin token by default — endpoints should return 503
    monkeypatch.delenv("NARAI_ADMIN_TOKEN", raising=False)

    import narai.api.routes.insider_admin as mod
    return importlib.reload(mod)


def test_lead_capture_persists_email(admin):
    body = admin.LeadRequest(email="alice@example.com", source="insider_landing")
    result = admin.capture_lead(body)
    assert result["ok"] is True

    with admin._conn() as c:
        rows = c.execute("SELECT email, source FROM leads").fetchall()
    assert len(rows) == 1
    assert rows[0]["email"] == "alice@example.com"
    assert rows[0]["source"] == "insider_landing"


def test_lead_capture_idempotent_on_email(admin):
    body = admin.LeadRequest(email="bob@example.com", source="x")
    admin.capture_lead(body)
    admin.capture_lead(body)
    admin.capture_lead(body)

    with admin._conn() as c:
        rows = c.execute("SELECT COUNT(*) AS n FROM leads").fetchone()
    assert rows["n"] == 1  # INSERT OR IGNORE on email PRIMARY KEY


def test_admin_endpoints_503_when_token_unset(admin):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        admin._require_admin("anything")
    assert exc.value.status_code == 503


def test_admin_endpoints_401_on_wrong_token(admin, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NARAI_ADMIN_TOKEN", "secret-xyz")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        admin._require_admin("wrong")
    assert exc.value.status_code == 401


def test_admin_endpoints_pass_with_correct_token(admin, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NARAI_ADMIN_TOKEN", "secret-xyz")
    # Should not raise
    admin._require_admin("secret-xyz")


def test_admin_endpoints_401_on_empty_token_even_when_admin_set(admin, monkeypatch: pytest.MonkeyPatch):
    """Empty header must not match an empty NARAI_ADMIN_TOKEN by accident
    (the require_admin function already rejects empty NARAI_ADMIN_TOKEN with 503)."""
    monkeypatch.setenv("NARAI_ADMIN_TOKEN", "real-token")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        admin._require_admin("")
    assert exc.value.status_code == 401
