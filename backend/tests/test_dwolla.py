"""Dwolla client + governed ops + read-only tool — mocked HTTP, no network.

Covers the four safety locks (sandbox-lock, read-only tool surface, scope gate,
approval gate) plus token caching, amount normalisation, and webhook HMAC.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.dwolla import client as dc
from app.services.dwolla.client import (
    DwollaClient,
    DwollaError,
    DwollaProductionLocked,
    verify_webhook,
)
from app.services.dwolla import operations as ops
from app.services.governance.actions import PendingApproval, ScopeDenied
from app.services.tools.dwolla_tool import DwollaTool, _ACTIONS
from app.services.tools.base import ToolError


class _Resp:
    """Minimal urlopen() context-manager stand-in."""
    def __init__(self, body, location=None):
        self._raw = json.dumps(body).encode() if not isinstance(body, (bytes, bytes)) else body
        self.headers = {"Location": location} if location else {}
    # dict-like .headers.get used in client
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._raw


class _Hdrs(dict):
    def get(self, k, d=None): return super().get(k, d)


def _resp(body, location=None):
    r = _Resp(body)
    r.headers = _Hdrs({"Location": location} if location else {})
    return r


@pytest.fixture(autouse=True)
def _sandbox_env(monkeypatch):
    monkeypatch.setenv("DWOLLA_ENV", "sandbox")
    monkeypatch.setenv("DWOLLA_KEY", "test-key")
    monkeypatch.setenv("DWOLLA_SECRET", "test-secret")
    monkeypatch.delenv("DWOLLA_ALLOW_PRODUCTION", raising=False)
    dc._TOKEN_CACHE.clear()
    yield
    dc._TOKEN_CACHE.clear()


# ── sandbox-lock ─────────────────────────────────────────────────────────
def test_production_is_locked_without_optin(monkeypatch):
    monkeypatch.setenv("DWOLLA_ENV", "production")
    with pytest.raises(DwollaProductionLocked):
        DwollaClient()


def test_production_allowed_with_explicit_optin(monkeypatch):
    monkeypatch.setenv("DWOLLA_ENV", "production")
    monkeypatch.setenv("DWOLLA_ALLOW_PRODUCTION", "1")
    c = DwollaClient()
    assert c.base == "https://api.dwolla.com"


def test_missing_creds_raises(monkeypatch):
    monkeypatch.delenv("DWOLLA_KEY", raising=False)
    c = DwollaClient()  # construction is fine; creds checked at auth time
    with pytest.raises(DwollaError):
        c._token()


# ── token caching ────────────────────────────────────────────────────────
def test_token_is_cached(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        return _resp({"access_token": "AT", "expires_in": 3600})

    with patch.object(dc.urllib.request, "urlopen", fake_urlopen):
        c = DwollaClient()
        assert c._token() == "AT"
        assert c._token() == "AT"  # second call served from cache
    assert calls["n"] == 1  # only one network auth


# ── amount normalisation ───────────────────────────────────────────────────
@pytest.mark.parametrize("val,out", [(200, "200.00"), ("3600", "3600.00"), (12.5, "12.50")])
def test_money_normalises(val, out):
    assert dc._money(val) == out


@pytest.mark.parametrize("bad", [0, -5, "abc", None])
def test_money_rejects_junk(bad):
    with pytest.raises(DwollaError):
        dc._money(bad)


def test_hal_accept_header_is_versioned():
    # Regression: the version token is vnd.dwolla.v1 — NOT vnd.dhs.dwolla.v1,
    # which 406s "InvalidVersion" (verified live 2026-06-16).
    assert dc._HAL == "application/vnd.dwolla.v1.hal+json"
    assert ".dhs." not in dc._HAL


def test_request_sends_hal_accept_header():
    captured = {}

    def fake_urlopen(req, timeout=0):
        if req.full_url.endswith("/token"):
            return _resp({"access_token": "AT", "expires_in": 3600})
        captured["accept"] = req.get_header("Accept")
        return _resp({"_links": {}})

    with patch.object(dc.urllib.request, "urlopen", fake_urlopen):
        DwollaClient()._request("GET", "/customers")
    assert captured["accept"] == "application/vnd.dwolla.v1.hal+json"


def test_offhost_url_refused(monkeypatch):
    with patch.object(dc.urllib.request, "urlopen", lambda *a, **k: _resp({"access_token": "AT", "expires_in": 3600})):
        c = DwollaClient()
        with pytest.raises(DwollaError):
            c._request("GET", "https://evil.example.com/customers")


# ── webhook HMAC ───────────────────────────────────────────────────────────
def test_webhook_verifies_good_signature():
    body = b'{"topic":"transfer_completed"}'
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    assert verify_webhook(body, sig, secret="whsec") is True


def test_webhook_rejects_bad_signature():
    assert verify_webhook(b"{}", "deadbeef", secret="whsec") is False


def test_webhook_rejects_missing_secret_or_sig():
    assert verify_webhook(b"{}", None, secret="whsec") is False
    assert verify_webhook(b"{}", "abc", secret="") is False


# ── read-only tool surface (no money movement) ─────────────────────────────
def test_tool_has_no_money_movement_action():
    # The whole point: the LLM-facing tool can only READ.
    forbidden = {"create_transfer", "transfer", "create_customer", "send", "pay"}
    assert not (_ACTIONS & forbidden)
    assert _ACTIONS == {
        "account", "list_customers", "get_customer",
        "list_funding_sources", "list_transfers", "get_transfer",
    }


def test_tool_list_customers_parses_embedded():
    def fake_urlopen(req, timeout=0):
        url = req.full_url
        if url.endswith("/token"):
            return _resp({"access_token": "AT", "expires_in": 3600})
        return _resp({"_embedded": {"customers": [{"id": "c1"}, {"id": "c2"}]}})

    with patch.object(dc.urllib.request, "urlopen", fake_urlopen):
        out = DwollaTool().execute(MagicMock(), action="list_customers")
    assert out["count"] == 2
    assert out["env"] == "sandbox"


def test_tool_rejects_unknown_action():
    with pytest.raises(ToolError):
        DwollaTool().execute(MagicMock(), action="wire_money")


def test_tool_requires_id_args():
    with patch.object(dc.urllib.request, "urlopen",
                      lambda *a, **k: _resp({"access_token": "AT", "expires_in": 3600})):
        with pytest.raises(ToolError):
            DwollaTool().execute(MagicMock(), action="get_transfer")  # no transfer_id


# ── governed money movement (scope + approval gates) ───────────────────────
def test_initiate_transfer_denied_without_scope(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_DWOLLA", raising=False)
    monkeypatch.delenv("KAI_SCOPE_DWOLLA_TRANSFER", raising=False)
    with pytest.raises(ScopeDenied):
        ops.initiate_transfer("src", "dst", "200.00", approved=True)


def test_initiate_transfer_pending_without_approval(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_DWOLLA_TRANSFER", "1")
    with pytest.raises(PendingApproval):
        ops.initiate_transfer("src", "dst", "200.00")  # approved defaults False


def test_initiate_transfer_runs_when_scoped_and_approved(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_DWOLLA_TRANSFER", "1")

    def fake_urlopen(req, timeout=0):
        if req.full_url.endswith("/token"):
            return _resp({"access_token": "AT", "expires_in": 3600})
        return _resp({}, location="https://api-sandbox.dwolla.com/transfers/tx1")

    with patch.object(dc.urllib.request, "urlopen", fake_urlopen):
        res = ops.initiate_transfer("src", "dst", 200, approved=True)
    assert res["ok"] is True
    assert res["transfer_url"].endswith("/transfers/tx1")
