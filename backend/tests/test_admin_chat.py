"""Operator chat endpoint tests.

We mock Brain at the import seam so these tests don't need real
adapters, network, or a populated llm_call_log. The narrow contract
we're checking:

  - 403 without admin token
  - upserts operator profile (tier='ultra' regardless of pre-existing state)
  - delegates message to Brain.chat with the operator's user_id
  - returns the (conv_id, message, cost) tuple shaped for the dashboard JS
"""
from __future__ import annotations

import uuid as _uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.models.profile import Profile
from app.routers import admin_chat as ac


ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


# ─── auth ────────────────────────────────────────────────────────────


def test_admin_chat_requires_token(client):
    r = client.post("/admin/kai-chat", json={"message": "hi"})
    assert r.status_code == 403


def test_admin_chat_rejects_wrong_token(client):
    r = client.post(
        "/admin/kai-chat",
        json={"message": "hi"},
        headers={"X-Admin-Token": "not-it"},
    )
    assert r.status_code == 403


# ─── operator profile upsert ─────────────────────────────────────────


def test_resolve_uses_env_uuid_when_profile_exists(db_session, monkeypatch):
    # Seed a real profile and point the env var at it.
    test_uuid = _uuid.uuid4()
    db_session.add(Profile(id=test_uuid, email=f"op-{test_uuid.hex[:8]}@kai.local", tier="free"))
    db_session.commit()

    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: test_uuid)
    prof = ac._resolve_operator_profile(db_session)
    assert prof.id == test_uuid
    # Tier should self-heal to ultra
    assert prof.tier == "ultra"


def test_resolve_env_uuid_unknown_raises(db_session, monkeypatch):
    """We refuse to invent a new profile — profiles.id is FK to auth.users."""
    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: _uuid.uuid4())
    with pytest.raises(ac.OperatorNotConfigured):
        ac._resolve_operator_profile(db_session)


def test_resolve_falls_back_to_existing_ultra_profile(db_session, monkeypatch):
    # Env unset; seed two ultra profiles and expect the oldest (first) chosen.
    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: None)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    older = _uuid.uuid4()
    newer = _uuid.uuid4()
    db_session.add(Profile(id=older, email=f"old-{older.hex[:6]}@kai.local",
                           tier="ultra", created_at=now - timedelta(days=5)))
    db_session.add(Profile(id=newer, email=f"new-{newer.hex[:6]}@kai.local",
                           tier="ultra", created_at=now))
    db_session.commit()

    prof = ac._resolve_operator_profile(db_session)
    assert prof.id == older   # oldest-first heuristic


def test_resolve_with_no_operator_at_all_raises(db_session, monkeypatch):
    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: None)
    # No ultra profile in DB — must raise with a helpful message
    with pytest.raises(ac.OperatorNotConfigured, match="KAI_OPERATOR_USER_ID"):
        ac._resolve_operator_profile(db_session)


# ─── happy path with mocked Brain ────────────────────────────────────


class _FakeMessage:
    role = "assistant"
    content = "hello from KAI"
    adapter = "openai"
    model = "gpt-4o-mini"


class _FakeConv:
    def __init__(self):
        self.id = _uuid.uuid4()


@pytest.fixture()
def mock_brain(monkeypatch, db_session):
    """Patch Brain so the endpoint runs without needing real router/adapters.

    Also seed an ultra-tier profile so _resolve_operator_profile() returns
    something — otherwise the endpoint short-circuits to 503.
    """
    fake_conv = _FakeConv()
    fake_msg = _FakeMessage()
    fake_cost = 0.0042

    # Seed operator profile that the fallback path will find
    op_uuid = _uuid.uuid4()
    db_session.add(Profile(
        id=op_uuid,
        email=f"op-{op_uuid.hex[:8]}@kai.local",
        tier="ultra",
    ))
    db_session.commit()

    captured = {}

    class FakeBrain:
        def __init__(self, *a, **kw):
            pass

        def chat(self, *, user_id, conversation_id, user_message,
                 use_tools, prefer_local, max_tokens):
            captured["user_id"] = user_id
            captured["message"] = user_message
            captured["use_tools"] = use_tools
            captured["prefer_local"] = prefer_local
            return fake_conv, fake_msg, fake_cost

    monkeypatch.setattr(ac, "Brain", FakeBrain)
    # The router/registry builders are also called — short-circuit to MagicMocks.
    monkeypatch.setattr(ac, "build_default_router", lambda s: MagicMock())
    monkeypatch.setattr(ac, "build_default_registry", lambda: MagicMock())
    # Ensure the env-var path doesn't accidentally win in tests
    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: None)
    return SimpleNamespace(
        captured=captured, conv=fake_conv, msg=fake_msg, cost=fake_cost,
        operator_uuid=op_uuid,
    )


def test_admin_chat_happy_path(client, mock_brain):
    r = client.post(
        "/admin/kai-chat",
        json={"message": "hello"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == str(mock_brain.conv.id)
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "hello from KAI"
    assert body["message"]["adapter"] == "openai"
    assert body["total_cost_usd"] == pytest.approx(0.0042)
    # Confirm the call went to Brain with use_tools=True by default
    assert mock_brain.captured["use_tools"] is True
    assert mock_brain.captured["prefer_local"] is False


def test_admin_chat_forwards_flags(client, mock_brain):
    r = client.post(
        "/admin/kai-chat",
        json={
            "message": "hi",
            "use_tools": False,
            "prefer_local": True,
            "max_tokens": 256,
        },
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 200
    assert mock_brain.captured["use_tools"] is False
    assert mock_brain.captured["prefer_local"] is True


def _seed_operator(db_session):
    """Helper — most tests need an ultra profile so resolution succeeds."""
    op = _uuid.uuid4()
    db_session.add(Profile(
        id=op, email=f"op-{op.hex[:8]}@kai.local", tier="ultra",
    ))
    db_session.commit()


def test_admin_chat_unknown_conversation_returns_404(client, monkeypatch, db_session):
    _seed_operator(db_session)
    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: None)

    class FakeBrain:
        def __init__(self, *a, **kw): pass
        def chat(self, **kw):
            raise ValueError("conversation not found")
    monkeypatch.setattr(ac, "Brain", FakeBrain)
    monkeypatch.setattr(ac, "build_default_router", lambda s: MagicMock())
    monkeypatch.setattr(ac, "build_default_registry", lambda: MagicMock())

    r = client.post(
        "/admin/kai-chat",
        json={
            "message": "hi",
            "conversation_id": str(_uuid.uuid4()),
        },
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 404


def test_admin_chat_returns_503_when_operator_not_configured(client, monkeypatch):
    """No ultra profile + no env var → 503 with remediation hint, not 500."""
    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: None)
    r = client.post(
        "/admin/kai-chat",
        json={"message": "hi"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 503
    assert "KAI_OPERATOR_USER_ID" in r.json()["detail"]


def test_admin_chat_brain_failure_returns_502(client, monkeypatch, db_session):
    _seed_operator(db_session)
    monkeypatch.setattr(ac, "_operator_uuid_from_env", lambda: None)

    class FakeBrain:
        def __init__(self, *a, **kw): pass
        def chat(self, **kw):
            raise RuntimeError("upstream provider boom")
    monkeypatch.setattr(ac, "Brain", FakeBrain)
    monkeypatch.setattr(ac, "build_default_router", lambda s: MagicMock())
    monkeypatch.setattr(ac, "build_default_registry", lambda: MagicMock())

    r = client.post(
        "/admin/kai-chat",
        json={"message": "hi"},
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 502


# ─── clean URL redirect ──────────────────────────────────────────────


def test_admin_redirect_to_dashboard(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/kai-ui/admin.html"
