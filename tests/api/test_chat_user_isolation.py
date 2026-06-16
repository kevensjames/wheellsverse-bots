"""Week 4-C: end-to-end JWT → user_id → BrainClient isolation regression.

The originally-deferred Week 1 follow-up. Verifies the full chain:
  1. create_token('test-user-xyz') mints a JWT
  2. require_auth decodes it back to 'test-user-xyz'
  3. get_brain receives that as Depends(require_auth) and produces a
     BrainClient bound to user_id='test-user-xyz'
  4. Two different subs ('alice', 'bob') get two different BrainClient
     instances, proving per-user isolation at the dependency layer

This guards against silent regressions if any future change accidentally
re-hardcodes user_id (e.g., a "convenience" shortcut that defaults to
'owner', restoring the single-user Week 0 behavior).
"""
from __future__ import annotations

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from narai.api.auth import create_token, require_auth
from narai.api.dependencies import brain as brain_dep


@pytest.fixture(autouse=True)
def _clear_brain_cache():
    brain_dep._cache.clear()
    yield
    brain_dep._cache.clear()


def _make_creds(user_id: str) -> HTTPAuthorizationCredentials:
    """Mint a JWT for user_id and wrap it as bearer creds the way FastAPI's
    HTTPBearer auto_error=True dependency would have produced."""
    token = create_token(user_id)
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_jwt_round_trip_yields_brain_keyed_to_sub():
    """The end-to-end happy path. JWT → sub → BrainClient.user_id."""
    creds = _make_creds("test-user-xyz")
    user_id = require_auth(creds=creds)
    assert user_id == "test-user-xyz"

    brain = brain_dep.get_brain(user_id=user_id)
    assert brain.user_id == "test-user-xyz"
    assert brain.mode == "narai"


def test_two_different_jwts_produce_two_different_brain_instances():
    """The isolation guarantee: Alice and Bob's tokens must not share
    a BrainClient. Same-user JWT round-trips share one (cache hit)."""
    alice_id = require_auth(creds=_make_creds("alice-uuid"))
    bob_id = require_auth(creds=_make_creds("bob-uuid"))
    assert alice_id != bob_id

    alice_brain = brain_dep.get_brain(user_id=alice_id)
    bob_brain = brain_dep.get_brain(user_id=bob_id)
    assert alice_brain is not bob_brain
    assert alice_brain.user_id == "alice-uuid"
    assert bob_brain.user_id == "bob-uuid"

    # Same user re-resolved → cache hit (same instance)
    alice_brain_again = brain_dep.get_brain(user_id=alice_id)
    assert alice_brain is alice_brain_again


def test_isolation_guard_no_default_to_owner():
    """Regression guard: if anyone ever reintroduces a 'default to owner'
    code path, the test that creates a non-owner sub would still resolve
    to 'owner', breaking this assertion."""
    creds = _make_creds("definitely-not-owner-12345")
    user_id = require_auth(creds=creds)
    assert user_id == "definitely-not-owner-12345"
    assert user_id != "owner"

    brain = brain_dep.get_brain(user_id=user_id)
    assert brain.user_id != "owner"
    assert brain.user_id == "definitely-not-owner-12345"
