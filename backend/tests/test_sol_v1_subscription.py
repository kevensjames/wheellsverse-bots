"""Connect Stage B tests — member subscription + optional access gate."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
import stripe

from app.services.sol_v1 import subscription as SUB
from app.services.sol_v1.lifecycle import SolError

PRICE = "price_sol_member"


def _sub(sid, status, price_id=PRICE, cpe=1893456000):
    return {"id": sid, "status": status, "current_period_end": cpe,
            "items": {"data": [{"price": {"id": price_id}}]}}


# ── pure ──────────────────────────────────────────────────────────────────────

def test_is_active():
    assert SUB.is_active("active") and SUB.is_active("trialing")
    for s in ("past_due", "canceled", "incomplete", "none", None):
        assert SUB.is_active(s) is False


def test_pick_subscription_filters_price_and_prefers_active():
    other = _sub("sub_other", "active", price_id="price_kai")   # different product
    canceled = _sub("sub_c", "canceled")
    active = _sub("sub_a", "active")
    assert SUB._pick_subscription([other, canceled, active], PRICE)["id"] == "sub_a"
    assert SUB._pick_subscription([canceled], PRICE)["id"] == "sub_c"   # only ours, not active
    assert SUB._pick_subscription([other], PRICE) is None               # none of ours


def test_has_price():
    assert SUB._has_price(_sub("s", "active"), PRICE) is True
    assert SUB._has_price(_sub("s", "active", price_id="price_x"), PRICE) is False


def test_access_gate_off_is_noop(monkeypatch):
    monkeypatch.setattr(SUB.settings, "SOL_REQUIRE_SUBSCRIPTION", False)
    # no DB touched when the gate is off
    SUB.require_active_if_enabled(None, user_id=uuid4())


def test_checkout_needs_a_configured_price(monkeypatch):
    monkeypatch.setattr(SUB.settings, "STRIPE_PRICE_SOL_MEMBER", "")
    with pytest.raises(SolError) as e:
        SUB._price_or_raise()
    assert e.value.status_code == 503


# ── router wiring ─────────────────────────────────────────────────────────────

def test_subscription_router_paths():
    from app.routers.sol_v1_subscription import router
    assert {r.path for r in router.routes} == {
        "/sol/v1/subscription",
        "/sol/v1/subscription/checkout",
        "/sol/v1/subscription/refresh",
        "/sol/v1/subscription/portal",
    }


# ── DB + mocked Stripe (gated) ────────────────────────────────────────────────

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set — DB flow DEFERRED")
def test_subscription_flow_and_gate(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import SolMemberSubscription

    monkeypatch.setattr(SUB.settings, "STRIPE_PRICE_SOL_MEMBER", PRICE)
    monkeypatch.setattr(SUB.settings, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(SUB.stripe_service, "get_or_create_customer", lambda **kw: "cus_test_1")
    monkeypatch.setattr(SUB.stripe_service, "create_checkout_session", lambda **kw: "https://checkout.stripe.test/pay")
    # stateful Stripe: what the customer's subscriptions currently look like
    stripe_state = {"subs": []}
    def fake_list(**kw):
        return {"data": list(stripe_state["subs"])}
    monkeypatch.setattr(stripe.Subscription, "list", staticmethod(fake_list), raising=True)

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_sub_e2e"
    uid = uuid4()
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        conn.execute(text(str(CreateTable(SolMemberSubscription.__table__).compile(dialect=postgresql.dialect()))))
        conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})
    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)

        assert SUB.status(db, user_id=uid) == {
            "status": "none", "active": False, "current_period_end": None, "available": True, "required": False,
        }

        # checkout stores the customer + returns a URL (Stripe has no sub yet)
        assert SUB.create_checkout(db, user_id=uid, email="m@test.dev").startswith("https://checkout.stripe.test/")
        assert SUB._row(db, user_id=uid).stripe_customer_id == "cus_test_1"

        # refresh before payment: no active sub
        SUB.refresh(db, user_id=uid)
        assert SUB.status(db, user_id=uid)["active"] is False

        # payment completes → Stripe now reports an active sub
        stripe_state["subs"] = [_sub("sub_a", "active")]

        # ACCESS GATE re-syncs from Stripe: a just-paid member is allowed even
        # WITHOUT a manual /refresh (stored row is still "none" here).
        monkeypatch.setattr(SUB.settings, "SOL_REQUIRE_SUBSCRIPTION", True)
        assert SUB._row(db, user_id=uid).status == "none"
        SUB.require_active_if_enabled(db, user_id=uid)                 # no raise
        assert SUB._row(db, user_id=uid).status == "active"           # gate synced it

        # member cancels in the portal → Stripe reports canceled → gate revokes
        stripe_state["subs"] = [_sub("sub_a", "canceled")]
        with pytest.raises(SolError) as e:
            SUB.require_active_if_enabled(db, user_id=uid)
        assert e.value.status_code == 402

        # fail-soft: if Stripe can't be reached, fall back to the stored status
        stripe_state["subs"] = [_sub("sub_a", "active")]
        SUB.refresh(db, user_id=uid)                                   # store active
        def boom(**kw):
            raise stripe.StripeError("stripe down")
        monkeypatch.setattr(stripe.Subscription, "list", staticmethod(boom), raising=True)
        SUB.require_active_if_enabled(db, user_id=uid)                 # no raise (stored active)

        db.close(); conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
