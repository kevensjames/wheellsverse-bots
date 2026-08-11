"""Stripe money-mode latch: the sk_test_/sk_live_ prefix must match APP_ENV so a
mismatch can't silently charge real cards (or hand out $0 upgrades)."""
import pytest

from app.config import Settings

_STRONG = "a-strong-admin-token-of-at-least-32-chars-xxx"
_BASE = dict(DATABASE_URL="postgresql://localhost/x", ADMIN_TOKEN=_STRONG)


def _settings(**kw):
    return Settings(**{**_BASE, **kw})


def test_live_key_in_non_prod_is_refused():
    with pytest.raises(ValueError, match="LIVE Stripe key"):
        _settings(APP_ENV="development", STRIPE_SECRET_KEY="sk_live_abc")


def test_test_key_in_prod_is_refused():
    with pytest.raises(ValueError, match="TEST Stripe key"):
        _settings(APP_ENV="production", STRIPE_SECRET_KEY="sk_test_abc")


def test_live_key_in_prod_is_allowed():
    s = _settings(APP_ENV="production", STRIPE_SECRET_KEY="sk_live_abc")
    assert s.STRIPE_SECRET_KEY == "sk_live_abc"


def test_test_key_in_dev_is_allowed():
    assert _settings(APP_ENV="development", STRIPE_SECRET_KEY="sk_test_abc")


def test_empty_key_allowed_anywhere():
    assert _settings(APP_ENV="production", STRIPE_SECRET_KEY="")
    assert _settings(APP_ENV="development", STRIPE_SECRET_KEY="")


def test_unrecognized_key_mode_refused():
    with pytest.raises(ValueError, match="recognized mode"):
        _settings(APP_ENV="development", STRIPE_SECRET_KEY="pk_live_wrongtype")
