"""Operator Digest tests: snapshot gathering (defensive), LLM build (fail-soft),
Telegram send, history log, and the admin endpoint auth/scope gates.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.digest import digest as dg

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_digest_log(tmp_path, monkeypatch):
    monkeypatch.setattr(dg, "DIGEST_LOG_PATH", tmp_path / "digests.jsonl")
    yield


def _router(content, *, cost=0.003):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    return r


# ─── snapshot ────────────────────────────────────────────────────────


def test_gather_snapshot_has_subsystem_blocks():
    snap = dg.gather_snapshot()
    assert "generated_at" in snap
    for key in ("audit", "planning", "learning", "twin"):
        assert key in snap


def test_gather_snapshot_is_defensive(monkeypatch):
    # a subsystem blowing up must degrade to an error note, not raise
    import app.services.planning as planning
    monkeypatch.setattr(planning, "stats", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    snap = dg.gather_snapshot()
    assert "planning" in snap  # still present, with an error note


# ─── build ───────────────────────────────────────────────────────────


def test_build_digest_happy():
    out = dg.build_digest(router=_router("All healthy. No blocked plans."), user_id=uuid.uuid4())
    assert out["digest"].startswith("All healthy")
    assert out["cost_usd"] == 0.003
    assert "snapshot" in out


def test_build_digest_router_crash_falls_back():
    r = MagicMock()
    r.complete.side_effect = RuntimeError("down")
    out = dg.build_digest(router=r, user_id=uuid.uuid4())
    assert "Operator Digest" in out["digest"]  # fallback rendering
    assert out["cost_usd"] == 0.0


# ─── send + log ──────────────────────────────────────────────────────


def test_send_digest_no_deliver_logs():
    out = dg.send_digest(router=_router("digest body"), user_id=uuid.uuid4(), deliver=False)
    assert out["sent"] is False
    assert out["digest"] == "digest body"
    assert len(dg.list_digests()) == 1


def test_send_digest_deliver_calls_telegram(monkeypatch):
    import app.services.supreme.scanner as scanner
    calls = {}
    monkeypatch.setattr(scanner, "telegram_send", lambda text: calls.setdefault("text", text) or True)
    out = dg.send_digest(router=_router("ship it"), user_id=uuid.uuid4(), deliver=True)
    assert out["sent"] is True
    assert "ship it" in calls["text"]


def test_send_digest_telegram_failure_failsoft(monkeypatch):
    import app.services.supreme.scanner as scanner
    monkeypatch.setattr(scanner, "telegram_send", lambda text: (_ for _ in ()).throw(RuntimeError("no net")))
    out = dg.send_digest(router=_router("x"), user_id=uuid.uuid4(), deliver=True)
    assert out["sent"] is False  # fail-soft; digest still produced + logged
    assert len(dg.list_digests()) == 1


# ─── admin endpoints ─────────────────────────────────────────────────

import app.routers.admin_digest as admin_digest  # noqa: E402


@pytest.fixture
def _isolated_audit(monkeypatch):
    import tempfile
    from app.services.governance import audit_log as _al
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        monkeypatch.setattr(_al, "AUDIT_LOG_PATH", _al.Path(tf.name))
        yield


def _patch(monkeypatch, content="digest"):
    fake = MagicMock()
    fake.complete.return_value = SimpleNamespace(content=content, total_cost_usd=0.001)
    monkeypatch.setattr(admin_digest, "build_default_router", lambda session: fake)
    monkeypatch.setattr(admin_digest, "_resolve_operator_profile",
                        lambda session: SimpleNamespace(id=uuid.uuid4(), tier="ultra"))
    import app.services.supreme.scanner as scanner
    monkeypatch.setattr(scanner, "telegram_send", lambda text: True)


def test_admin_history_requires_token(client):
    assert client.get("/admin/digest/history").status_code == 403


def test_admin_run_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_DIGEST", raising=False)
    monkeypatch.delenv("KAI_SCOPE_DIGEST_RUN", raising=False)
    r = client.post("/admin/digest/run", headers=ADMIN_HEADERS, json={"deliver": False, "approved": True})
    assert r.status_code == 403


def test_admin_run_no_approval_409(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_DIGEST", "1")
    r = client.post("/admin/digest/run", headers=ADMIN_HEADERS, json={"deliver": False, "approved": False})
    assert r.status_code == 409


def test_admin_run_success(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_DIGEST", "1")
    _patch(monkeypatch, content="Today: all green.")
    r = client.post("/admin/digest/run", headers=ADMIN_HEADERS, json={"deliver": True, "approved": True})
    assert r.status_code == 200
    body = r.json()
    assert body["digest"].startswith("Today")
    assert body["sent"] is True
