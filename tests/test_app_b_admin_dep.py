"""App B side of the P2 wiring: `require_admin_token` must accept the shared
wv_session cookie when the flag is on, keep rejecting otherwise, and never
regress the legacy X-Admin-Token path. Runs isolated — only app.config +
app.dependencies.admin are imported (no DB/router boot), with DATABASE_URL
stubbed so pydantic Settings validates.
"""
import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

# App B expects `backend/` on the path; the shared core lives at the repo root.
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://stub/stub")  # satisfy Settings

from app.config import settings                       # noqa: E402
from app.dependencies.admin import require_admin_token  # noqa: E402
from fastapi import HTTPException                      # noqa: E402
from core.operator_session import mint_session         # noqa: E402

SECRET = "shared-signing-secret"
ADMIN_TOKEN = "operator-admin-token"


def _req(cookie=None):
    return SimpleNamespace(cookies=({"wv_session": cookie} if cookie else {}))


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", ADMIN_TOKEN, raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "", raising=False)
    monkeypatch.setattr(settings, "SESSION_SIGNING_SECRET", SECRET, raising=False)
    return settings


def test_legacy_token_still_works(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", False, raising=False)
    # No raise = authorized.
    assert require_admin_token(_req(), x_admin_token=ADMIN_TOKEN) is None


def test_wrong_token_flag_off_rejected(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", False, raising=False)
    with pytest.raises(HTTPException) as e:
        require_admin_token(_req(), x_admin_token="wrong")
    assert e.value.status_code == 403


def test_cookie_ignored_when_flag_off(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", False, raising=False)
    good = mint_session("operator", secret=SECRET, ttl_seconds=3600)
    with pytest.raises(HTTPException):
        require_admin_token(_req(good), x_admin_token=None)  # flag off → cookie unused


def test_valid_cookie_accepted_when_flag_on(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", True, raising=False)
    good = mint_session("operator", secret=SECRET, ttl_seconds=3600)
    assert require_admin_token(_req(good), x_admin_token=None) is None


def test_owner_cookie_accepted_when_flag_on(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", True, raising=False)
    good = mint_session("owner", secret=SECRET, ttl_seconds=3600)
    assert require_admin_token(_req(good), x_admin_token=None) is None


def test_tampered_cookie_rejected(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", True, raising=False)
    good = mint_session("owner", secret=SECRET, ttl_seconds=3600)
    body, sig = good.split(".", 1)
    # Flip the FIRST sig char (always significant); the last carries dropped
    # base64url padding bits, so flipping it can decode to identical bytes.
    forged = body + "." + (("A" if sig[0] != "A" else "B") + sig[1:])
    with pytest.raises(HTTPException):
        require_admin_token(_req(forged), x_admin_token=None)


def test_expired_cookie_rejected(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", True, raising=False)
    expired = mint_session("owner", secret=SECRET, ttl_seconds=10, now=1000)
    with pytest.raises(HTTPException):
        require_admin_token(_req(expired), x_admin_token=None)


def test_cookie_from_wrong_secret_rejected(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", True, raising=False)
    foreign = mint_session("owner", secret="other-secret", ttl_seconds=3600)
    with pytest.raises(HTTPException):
        require_admin_token(_req(foreign), x_admin_token=None)


def test_flag_on_but_no_secret_ignores_cookie(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg, "SESSION_SIGNING_SECRET", "", raising=False)
    good = mint_session("owner", secret=SECRET, ttl_seconds=3600)
    with pytest.raises(HTTPException):
        require_admin_token(_req(good), x_admin_token=None)


def test_valid_token_still_wins_when_flag_on(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "OPERATOR_SESSION_ENABLED", True, raising=False)
    assert require_admin_token(_req(), x_admin_token=ADMIN_TOKEN) is None
