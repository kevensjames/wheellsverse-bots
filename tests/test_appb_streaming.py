"""Unit tests for the governed streaming endpoint's testable pieces (Phase B):
context sanitization, the anti-abuse rate-limit key, DEBUG safe default, and the
ollama-only router opt-in. Import-only (no live App B / ollama).
"""
import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://stub/stub")

from app.routers.admin_chat import _sanitize_context, _operator_rate_key  # noqa: E402
from app.config import Settings  # noqa: E402
from core.operator_session import mint_session  # noqa: E402


# ── §2 context sanitization: allowlist only, drop secrets ────────────────────
def test_sanitize_context_allowlist():
    raw = {
        "route": "/admin/security", "module": "security", "surface": "drawer",
        "entity_type": "finding", "entity_id": "472", "environment": "staging",
        # forbidden — must be dropped:
        "cookie": "wv_session=abc", "authorization": "Bearer x", "api_key": "sk-1",
        "dom": "<html>...</html>", "password": "hunter2", "note": "unrelated",
    }
    out = _sanitize_context(raw)
    assert out == {"route": "/admin/security", "module": "security",
                   "surface": "drawer", "entity_type": "finding",
                   "entity_id": "472", "environment": "staging"}
    for bad in ("cookie", "authorization", "api_key", "dom", "password", "note"):
        assert bad not in out


def test_sanitize_context_non_dict_and_caps():
    assert _sanitize_context(None) == {}
    assert _sanitize_context("nope") == {}
    assert _sanitize_context(["a"]) == {}
    long = _sanitize_context({"route": "x" * 500})
    assert len(long["route"]) <= 200


# ── §6 rate-limit key: derived from VERIFIED principal, not bearer text ───────
def _req(cookie=None):
    return SimpleNamespace(cookies=({"wv_session": cookie} if cookie else {}), headers={})


def test_rate_key_owner_session(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "OPERATOR_SESSION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SESSION_SIGNING_SECRET", "s3cret", raising=False)
    tok = mint_session("owner", secret="s3cret", ttl_seconds=3600)
    assert _operator_rate_key(_req(tok)) == "kai-op:owner"


def test_rate_key_rotating_junk_cannot_mint_buckets(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "OPERATOR_SESSION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SESSION_SIGNING_SECRET", "s3cret", raising=False)
    # Every rotated/forged/absent credential collapses to ONE shared bucket —
    # an attacker can't farm fresh buckets by varying request data.
    keys = {
        _operator_rate_key(_req(None)),
        _operator_rate_key(_req("garbage")),
        _operator_rate_key(_req("a.b")),
        _operator_rate_key(_req(mint_session("owner", secret="WRONG", ttl_seconds=3600))),
        _operator_rate_key(_req(mint_session("owner", secret="s3cret", ttl_seconds=10, now=1000))),  # expired
    }
    assert keys == {"kai-op:admin"}


# ── §11 DEBUG safe default ───────────────────────────────────────────────────
def test_debug_default_false(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    assert Settings(DATABASE_URL="x").DEBUG is False


def test_debug_explicit_true(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    assert Settings(DATABASE_URL="x").DEBUG is True


# ── §12 ollama-only router opt-in (prod requirement unchanged) ───────────────
def test_router_requires_openai_by_default(monkeypatch):
    from app.services.router.router import Router
    monkeypatch.delenv("KAI_LLM_ALLOW_LOCAL_ONLY", raising=False)
    with pytest.raises(ValueError):
        Router(adapters={"ollama": object()}, spend_tracker=object())


def test_router_allows_ollama_only_with_optin(monkeypatch):
    from app.services.router.router import Router
    monkeypatch.setenv("KAI_LLM_ALLOW_LOCAL_ONLY", "1")
    r = Router(adapters={"ollama": object()}, spend_tracker=object())
    assert "ollama" in r.adapters


def test_router_still_rejects_empty(monkeypatch):
    from app.services.router.router import Router
    monkeypatch.setenv("KAI_LLM_ALLOW_LOCAL_ONLY", "1")
    with pytest.raises(ValueError):
        Router(adapters={}, spend_tracker=object())
