"""Admin security hardening: prod boot-guard + constant-time compare + throttle."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import Settings
from app.dependencies import admin as admindep
from app.config import settings as app_settings


# ── config boot-guard ─────────────────────────────────────────────────────
def _mk(**kw):
    base = dict(
        DATABASE_URL="postgresql://u:p@localhost:5432/x",
        APP_ENV="production",
        ADMIN_TOKEN="",
        JWT_SECRET_KEY="",
    )
    base.update(kw)
    return Settings(**base)


def test_prod_refuses_short_admin_token():
    with pytest.raises(ValidationError):
        _mk(ADMIN_TOKEN="too-short")


def test_prod_refuses_default_admin_token():
    with pytest.raises(ValidationError):
        _mk(ADMIN_TOKEN="change_me_to_a_long_random_string")


def test_prod_refuses_absent_token_with_weak_jwt():
    with pytest.raises(ValidationError):
        _mk(ADMIN_TOKEN="", JWT_SECRET_KEY="")


def test_prod_accepts_strong_admin_token():
    s = _mk(ADMIN_TOKEN="A" * 40)
    assert s.admin_token == "A" * 40


def test_prod_accepts_strong_jwt_fallback():
    s = _mk(ADMIN_TOKEN="", JWT_SECRET_KEY="B" * 40)
    assert s.admin_token == "B" * 40


@pytest.mark.parametrize("env", ["development", "dev", "local", "test", "ci"])
def test_non_prod_envs_are_exempt(env):
    # Weak token tolerated outside production.
    s = _mk(APP_ENV=env, ADMIN_TOKEN="", JWT_SECRET_KEY="")
    assert s.APP_ENV == env


# ── admin dependency: constant-time compare + throttle ─────────────────────
def _req(host="127.0.0.1", headers=None):
    # Default peer is loopback = the trusted local tunnel, so CF-Connecting-IP is
    # honoured (matches the real Mac-mini-behind-Cloudflare deployment).
    r = type("R", (), {})()
    r.client = type("C", (), {"host": host})()
    r.headers = headers or {}
    return r


@pytest.fixture(autouse=True)
def _clean_throttle():
    admindep._reset_throttle()
    yield
    admindep._reset_throttle()


def test_correct_token_passes(monkeypatch):
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    # No exception == authorized.
    admindep.require_admin_token(request=_req(), x_admin_token="s3cret-token-value")


def test_wrong_token_403(monkeypatch):
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    with pytest.raises(HTTPException) as ei:
        admindep.require_admin_token(request=_req(), x_admin_token="nope")
    assert ei.value.status_code == 403


def test_missing_token_403(monkeypatch):
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    with pytest.raises(HTTPException) as ei:
        admindep.require_admin_token(request=_req(), x_admin_token=None)
    assert ei.value.status_code == 403


def test_throttle_off_in_test_env(monkeypatch):
    # APP_ENV defaults to 'test' → throttle disabled, so it's always 403 (never 429).
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    req = _req(host="6.6.6.6")
    for _ in range(admindep._MAX_FAILURES + 3):
        with pytest.raises(HTTPException) as ei:
            admindep.require_admin_token(request=req, x_admin_token="bad")
        assert ei.value.status_code == 403


def test_throttle_kicks_in_after_max_failures(monkeypatch):
    monkeypatch.setattr(app_settings, "APP_ENV", "production")
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    req = _req(host="5.5.5.5")
    for _ in range(admindep._MAX_FAILURES):
        with pytest.raises(HTTPException) as ei:
            admindep.require_admin_token(request=req, x_admin_token="bad")
        assert ei.value.status_code == 403
    # Budget exhausted → 429 before the token is even checked.
    with pytest.raises(HTTPException) as ei:
        admindep.require_admin_token(request=req, x_admin_token="bad")
    assert ei.value.status_code == 429


def test_success_clears_failure_streak(monkeypatch):
    monkeypatch.setattr(app_settings, "APP_ENV", "production")
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    req = _req(host="7.7.7.7")
    for _ in range(admindep._MAX_FAILURES - 1):
        with pytest.raises(HTTPException):
            admindep.require_admin_token(request=req, x_admin_token="bad")
    # A correct token resets the counter…
    admindep.require_admin_token(request=req, x_admin_token="s3cret-token-value")
    # …so the next bad attempt is a normal 403, not an immediate 429.
    with pytest.raises(HTTPException) as ei:
        admindep.require_admin_token(request=req, x_admin_token="bad")
    assert ei.value.status_code == 403


def test_throttle_is_per_client(monkeypatch):
    monkeypatch.setattr(app_settings, "APP_ENV", "production")
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    # Exhaust one client's budget via CF-Connecting-IP (peer is loopback = trusted).
    attacker = _req(headers={"cf-connecting-ip": "1.1.1.1"})
    for _ in range(admindep._MAX_FAILURES):
        with pytest.raises(HTTPException):
            admindep.require_admin_token(request=attacker, x_admin_token="bad")
    with pytest.raises(HTTPException) as ei:
        admindep.require_admin_token(request=attacker, x_admin_token="bad")
    assert ei.value.status_code == 429
    # A different client is unaffected → still a 403, not 429.
    other = _req(headers={"cf-connecting-ip": "2.2.2.2"})
    with pytest.raises(HTTPException) as ei:
        admindep.require_admin_token(request=other, x_admin_token="bad")
    assert ei.value.status_code == 403


def test_forwarded_header_from_untrusted_peer_is_ignored(monkeypatch):
    # Origin reached DIRECTLY (public peer, not the tunnel): a rotated/spoofed
    # CF-Connecting-IP must NOT let an attacker evade the throttle. All attempts
    # key on the real socket peer, so the budget still applies.
    monkeypatch.setattr(app_settings, "APP_ENV", "production")
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    for i in range(admindep._MAX_FAILURES):
        req = _req(host="8.8.8.8", headers={"cf-connecting-ip": f"9.9.9.{i}"})
        with pytest.raises(HTTPException) as ei:
            admindep.require_admin_token(request=req, x_admin_token="bad")
        assert ei.value.status_code == 403
    # Header rotation did not help — keyed on the real peer 8.8.8.8 → now throttled.
    req = _req(host="8.8.8.8", headers={"cf-connecting-ip": "9.9.9.254"})
    with pytest.raises(HTTPException) as ei:
        admindep.require_admin_token(request=req, x_admin_token="bad")
    assert ei.value.status_code == 429


def test_valid_token_never_locked_out(monkeypatch):
    # A fat-fingering operator: many wrong attempts must NOT lock out the
    # correct token (the check runs first, and success clears the streak).
    monkeypatch.setattr(app_settings, "APP_ENV", "production")
    monkeypatch.setattr(app_settings, "ADMIN_TOKEN", "s3cret-token-value")
    req = _req(host="4.4.4.4")
    for _ in range(admindep._MAX_FAILURES + 5):
        with pytest.raises(HTTPException):
            admindep.require_admin_token(request=req, x_admin_token="bad")
    # Even past the limit, the RIGHT token still works (no self-lockout).
    admindep.require_admin_token(request=req, x_admin_token="s3cret-token-value")


def test_uses_constant_time_compare():
    # Guard the headline anti-timing-attack property: a regression to `==` would
    # otherwise leave every functional test green. See finding [15].
    import inspect
    src = inspect.getsource(admindep.require_admin_token)
    assert "compare_digest" in src, "admin token check must use hmac.compare_digest"
