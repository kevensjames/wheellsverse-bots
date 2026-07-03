"""Connect Stage A tests — sandbox lock + connected-account onboarding.

The sandbox lock (the safety core) and capability mapping are unit-tested
offline. Onboarding/refresh are exercised against real Postgres with Stripe
mocked (no network, no real account) — proving the DB flow without ever
touching live Stripe.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
import stripe

from app.services.sol_v1 import stripe_connect as SC
from app.services.sol_v1.lifecycle import SolError


def _cfg(monkeypatch, *, enabled=True, key="sk_test_x", approved=False):
    monkeypatch.setattr(SC.settings, "STRIPE_CONNECT_ENABLED", enabled)
    monkeypatch.setattr(SC.settings, "STRIPE_SECRET_KEY", key)
    monkeypatch.setattr(SC.settings, "STRIPE_CONNECT_LIVE_APPROVED", approved)


# ── pure: sandbox state ───────────────────────────────────────────────────────

def test_sandbox_state_modes(monkeypatch):
    _cfg(monkeypatch, key="")
    assert SC.sandbox_state()["mode"] == "unconfigured"
    _cfg(monkeypatch, key="sk_test_abc")
    assert SC.sandbox_state()["mode"] == "test"
    _cfg(monkeypatch, key="rk_test_abc")           # restricted TEST key → test
    assert SC.sandbox_state()["mode"] == "test"
    _cfg(monkeypatch, key="sk_live_abc", approved=False)
    assert SC.sandbox_state()["mode"] == "blocked_live"
    _cfg(monkeypatch, key="sk_live_abc", approved=True)
    assert SC.sandbox_state()["mode"] == "live"


def test_sandbox_fails_closed(monkeypatch):
    # restricted LIVE key (Stripe's recommended prod key) must NOT read as test
    _cfg(monkeypatch, key="rk_live_abc", approved=False)
    assert SC.sandbox_state()["mode"] == "blocked_live"
    _cfg(monkeypatch, key="rk_live_abc", approved=True)
    assert SC.sandbox_state()["mode"] == "live"
    # leading-whitespace live key (quoted .env artifact) → stripped → blocked
    _cfg(monkeypatch, key="  sk_live_abc  ", approved=False)
    assert SC.sandbox_state()["mode"] == "blocked_live"
    # unknown/unrecognized key format → treated as live (fail-closed)
    _cfg(monkeypatch, key="totally-unknown-key", approved=False)
    assert SC.sandbox_state()["mode"] == "blocked_live"


def test_guard_blocks_disabled_unconfigured_and_live(monkeypatch):
    _cfg(monkeypatch, enabled=False)
    with pytest.raises(SolError) as e:
        SC._guard()
    assert e.value.status_code == 403           # not enabled

    _cfg(monkeypatch, enabled=True, key="")
    with pytest.raises(SolError) as e:
        SC._guard()
    assert e.value.status_code == 503           # not configured

    _cfg(monkeypatch, enabled=True, key="sk_live_x", approved=False)
    with pytest.raises(SolError) as e:
        SC._guard()
    assert e.value.status_code == 403           # live but not approved → sandbox-only


def test_guard_allows_test_key(monkeypatch):
    _cfg(monkeypatch, enabled=True, key="sk_test_x")
    SC._guard()  # no raise
    assert stripe.api_key == "sk_test_x"


def test_map_capabilities_dict_and_object():
    assert SC.map_capabilities({"charges_enabled": True, "payouts_enabled": False, "details_submitted": True}) == {
        "charges_enabled": True, "payouts_enabled": False, "details_submitted": True,
    }
    class A:
        charges_enabled = False; payouts_enabled = True; details_submitted = False
    assert SC.map_capabilities(A())["payouts_enabled"] is True


# ── router wiring ─────────────────────────────────────────────────────────────

def test_stripe_router_paths():
    from app.routers.sol_v1_stripe import router
    assert {r.path for r in router.routes} == {
        "/sol/v1/stripe/account",
        "/sol/v1/stripe/account/onboard",
        "/sol/v1/stripe/account/refresh",
    }


# ── DB + mocked Stripe (gated) ────────────────────────────────────────────────

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set — DB flow DEFERRED")
def test_onboarding_and_refresh_with_mocked_stripe(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import SolStripeAccount

    _cfg(monkeypatch, enabled=True, key="sk_test_x")
    created = {"n": 0}

    def fake_account_create(**kw):
        created["n"] += 1
        assert kw["type"] == "express"
        assert kw.get("idempotency_key")  # dedupe concurrent/retried creates
        return {"id": "acct_test_1", "charges_enabled": False, "payouts_enabled": False, "details_submitted": False}

    monkeypatch.setattr(stripe.Account, "create", staticmethod(fake_account_create), raising=True)
    monkeypatch.setattr(stripe.AccountLink, "create", staticmethod(lambda **kw: {"url": "https://connect.stripe.test/onboard/x"}), raising=True)
    monkeypatch.setattr(stripe.Account, "retrieve", staticmethod(lambda acct_id, **kw: {"id": acct_id, "charges_enabled": True, "payouts_enabled": True, "details_submitted": True}), raising=True)

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_stripe_e2e"
    uid = uuid4()
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        conn.execute(text(str(CreateTable(SolStripeAccount.__table__).compile(dialect=postgresql.dialect()))))
        conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})
    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)

        # before onboarding: not connected
        st0 = SC.account_status(db, user_id=uid)
        assert st0["connected"] is False and st0["mode"] == "test"

        # onboarding creates the account once (idempotent)
        link = SC.onboarding_link(db, user_id=uid, email="m@test.dev")
        assert link.startswith("https://connect.stripe.test/")
        SC.create_or_get_account(db, user_id=uid)  # again
        assert created["n"] == 1                    # only created once

        st1 = SC.account_status(db, user_id=uid)
        assert st1["connected"] is True and st1["onboarding_complete"] is False

        # refresh pulls Stripe's flags → onboarding complete
        SC.refresh_status(db, user_id=uid)
        st2 = SC.account_status(db, user_id=uid)
        assert st2["charges_enabled"] is True and st2["onboarding_complete"] is True

        db.close(); conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
