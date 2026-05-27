"""Stage 6 rate-limit tests.

Other suites (test_auth, test_cookie_auth) run with the slowapi limiter
*disabled* via the autouse `_disable_rate_limiter` fixture so they aren't
flaky against the global counter. This suite re-enables the limiter and
proves it actually fires.

Configured limits (see app/routers/auth.py):
- /auth/signup   5/minute
- /auth/login   10/minute
- /auth/refresh 20/minute
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import limiter


@pytest.fixture
def _rate_limiter_on():
    """Override the autouse disabler for this suite only."""
    limiter.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter.reset()


def _payload(faker):
    return {
        "email": faker.unique.email().lower(),
        "password": "testpass123",
        "full_name": faker.name(),
    }


def test_signup_blocks_after_5_per_minute(client, faker_fixture, _rate_limiter_on):
    """6th signup from the same IP within a minute must return 429."""
    # First 5 succeed (unique emails so the User layer doesn't 409 first).
    for _ in range(5):
        r = client.post("/auth/signup", json=_payload(faker_fixture))
        assert r.status_code == 201, r.text

    # 6th: throttled. slowapi's default handler returns 429 with a JSON body
    # and content-type=application/json (no Retry-After header by default —
    # if we want one, we'd set a custom handler).
    r = client.post("/auth/signup", json=_payload(faker_fixture))
    assert r.status_code == 429, r.text


def test_login_blocks_after_10_per_minute(client, faker_fixture, _rate_limiter_on):
    """11th login attempt from the same IP within a minute must return 429."""
    # Pre-create one user so login has a real account to target.
    body = _payload(faker_fixture)
    # signup itself counts against the signup bucket, not login — fine.
    r = client.post("/auth/signup", json=body)
    assert r.status_code == 201

    # 10 login attempts with wrong password — all should 401 (not rate-limited yet).
    for _ in range(10):
        r = client.post(
            "/auth/login",
            json={"email": body["email"], "password": "wrong-on-purpose"},
        )
        assert r.status_code == 401, r.text

    # 11th: throttled, not 401.
    r = client.post(
        "/auth/login",
        json={"email": body["email"], "password": "wrong-on-purpose"},
    )
    assert r.status_code == 429, r.text


def test_reset_between_tests_works(client, faker_fixture, _rate_limiter_on):
    """The fixture's `limiter.reset()` must give each test a fresh bucket —
    otherwise the previous test's signups would carry over and this one fails."""
    r = client.post("/auth/signup", json=_payload(faker_fixture))
    assert r.status_code == 201
