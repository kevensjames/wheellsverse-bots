"""Stage 14 tests — Sol member API rate limits.

Every other Sol suite runs with the slowapi limiter DISABLED (the autouse
`_disable_rate_limiter` fixture) so the shared counter can't make them flaky.
This suite RE-ENABLES it and proves the caps actually fire — most importantly
the invite-code BRUTE-FORCE defense on POST /sol/v1/groups/join.

Note: the Sol routes auth via get_current_user (a dependency), which runs BEFORE
the slowapi wrapper. So each request must be authenticated to reach — and
increment — the limiter. We sign up once (its own bucket) to get a session
cookie, then hammer. The endpoint body may 4xx (e.g. consent gate / not-found),
but that still counts against the per-route/IP bucket, exactly like a real
attacker's failed attempts — so the (N+1)th request returns 429.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.rate_limit import limiter


@pytest.fixture
def _rate_limiter_on():
    """Override the autouse disabler for this suite only (fresh bucket each test)."""
    limiter.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter.reset()


def _signup(client, faker_fixture) -> dict:
    body = {
        "email": faker_fixture.unique.email().lower(),
        "password": "testpass123",
        "full_name": faker_fixture.name(),
    }
    r = client.post("/auth/signup", json=body)  # authenticates the client (its own bucket)
    assert r.status_code == 201, r.text
    return body


def test_join_blocks_after_10_per_minute(client, faker_fixture, _rate_limiter_on):
    """BRUTE-FORCE DEFENSE: the 11th invite-code guess from one IP → 429."""
    _signup(client, faker_fixture)
    for i in range(10):
        r = client.post("/sol/v1/groups/join", json={"invite_code": "NOPE0000"})
        assert r.status_code != 429, f"throttled too early at guess {i}: {r.status_code}"
    r = client.post("/sol/v1/groups/join", json={"invite_code": "NOPE0000"})
    assert r.status_code == 429, r.text


def test_create_group_blocks_after_15_per_minute(client, faker_fixture, _rate_limiter_on):
    _signup(client, faker_fixture)
    body = {"name": "C", "contribution_amount": "10.00", "frequency": "weekly", "member_limit": 3}
    for i in range(15):
        r = client.post("/sol/v1/groups", json=body)
        assert r.status_code != 429, f"throttled too early at create {i}: {r.status_code}"
    r = client.post("/sol/v1/groups", json=body)
    assert r.status_code == 429, r.text


def test_ledger_write_blocks_after_30_per_minute(client, faker_fixture, _rate_limiter_on):
    """A different router (ledger): the 31st mark from one IP → 429."""
    _signup(client, faker_fixture)
    pid = str(uuid4())
    for i in range(30):
        r = client.post(f"/sol/v1/payments/{pid}/mark", json={"method": "zelle"})
        assert r.status_code != 429, f"throttled too early at mark {i}: {r.status_code}"
    r = client.post(f"/sol/v1/payments/{pid}/mark", json={"method": "zelle"})
    assert r.status_code == 429, r.text
