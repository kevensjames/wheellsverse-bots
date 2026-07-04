"""Connect Stage D tests — Stripe webhook handlers."""
from __future__ import annotations

import os
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest
import stripe

from app.services.sol_v1 import stripe_webhooks as WH

PRICE = "price_sol_member"


def _evt(t, obj):
    return {"id": "evt_" + t, "type": t, "data": {"object": obj}}


# ── pure: dispatch ────────────────────────────────────────────────────────────

def test_unhandled_type_is_noop():
    assert WH.handle_event(None, _evt("invoice.paid", {}))["handled"] is False


def test_handled_types_cover_the_surfaces():
    for t in ("checkout.session.completed", "customer.subscription.updated",
              "customer.subscription.deleted", "account.updated",
              "charge.refunded", "charge.dispute.created"):
        assert t in WH.HANDLED_TYPES


def test_router_registers_webhook():
    from app.routers.sol_v1_webhook import router
    assert "/sol/v1/stripe/webhook" in {r.path for r in router.routes}


# ── DB: the four handlers (gated) ─────────────────────────────────────────────

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set — DB flow DEFERRED")
def test_webhook_handlers_on_real_db(monkeypatch):
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate,
        SolCycle, SolGroup, SolMemberSubscription, SolMembership, SolPayment,
        SolStripeAccount, SolStripePayment,
    )
    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    monkeypatch.setattr(WH.settings, "STRIPE_PRICE_SOL_MEMBER", PRICE)
    # the settle handler now verifies the LIVE PaymentIntent — mock a clean success
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", staticmethod(
        lambda pi_id, **kw: {"id": pi_id, "status": "succeeded",
                             "latest_charge": {"refunded": False, "amount_refunded": 0, "disputed": False}}),
        raising=True)

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_webhook_e2e"
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolStripeAccount,
              SolStripePayment, SolMemberSubscription)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for m in models:
            conn.execute(text(str(CreateTable(m.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (organizer, alice, bob):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})
    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)

        group = LC.create_group(db, organizer_id=organizer, name="WH circle",
                                contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=3)
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        LC.lock_group(db, group_id=group.id, actor_id=organizer, order_mode="random", rng=Random(9))
        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        p0, p1 = payments

        # a pending Stripe payment for p0 (as create_contribution_checkout would leave it)
        db.add(SolStripePayment(payment_id=p0.id, payer_id=p0.payer_id,
                                destination_account_id="acct_recip", amount=p0.amount,
                                stripe_checkout_session_id="cs_1", stripe_payment_intent_id="pi_1", status="pending"))
        db.commit()

        # 1) checkout.session.completed → settle → ledger payment confirmed
        r = WH.handle_event(db, _evt("checkout.session.completed",
                                     {"metadata": {"sol_payment_id": str(p0.id)}, "payment_intent": "pi_1", "payment_status": "paid"}))
        assert r["handled"] is True
        assert db.get(SolPayment, p0.id).status == "confirmed"
        assert db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == p0.id)).status == "paid"

        # 2) account.updated → capability flags mirrored
        db.add(SolStripeAccount(user_id=alice, stripe_account_id="acct_a",
                                charges_enabled=False, payouts_enabled=False, details_submitted=False))
        db.commit()
        WH.handle_event(db, _evt("account.updated",
                                 {"id": "acct_a", "charges_enabled": True, "payouts_enabled": True, "details_submitted": True}))
        acct = db.scalar(select(SolStripeAccount).where(SolStripeAccount.stripe_account_id == "acct_a"))
        assert acct.charges_enabled is True and acct.details_submitted is True

        # 3) customer.subscription.updated → mirrored ONLY for our price
        db.add(SolMemberSubscription(user_id=bob, stripe_customer_id="cus_1", status="none"))
        db.commit()
        # wrong price → ignored
        assert WH.handle_event(db, _evt("customer.subscription.updated",
            {"id": "sub_x", "customer": "cus_1", "status": "active", "current_period_end": 1893456000,
             "items": {"data": [{"price": {"id": "price_other"}}]}}))["handled"] is False
        # our price → mirrored
        WH.handle_event(db, _evt("customer.subscription.updated",
            {"id": "sub_1", "customer": "cus_1", "status": "active", "current_period_end": 1893456000,
             "items": {"data": [{"price": {"id": PRICE}}]}}))
        sub = db.scalar(select(SolMemberSubscription).where(SolMemberSubscription.stripe_customer_id == "cus_1"))
        assert sub.status == "active" and sub.stripe_subscription_id == "sub_1"

        # 3b) out-of-order guard: deleted→canceled, a late 'active' must NOT resurrect
        WH.handle_event(db, _evt("customer.subscription.deleted",
            {"id": "sub_1", "customer": "cus_1", "status": "canceled", "current_period_end": 1893456000,
             "items": {"data": [{"price": {"id": PRICE}}]}}))
        assert db.scalar(select(SolMemberSubscription).where(SolMemberSubscription.stripe_customer_id == "cus_1")).status == "canceled"
        assert WH.handle_event(db, _evt("customer.subscription.updated",
            {"id": "sub_1", "customer": "cus_1", "status": "active", "current_period_end": 1893456000,
             "items": {"data": [{"price": {"id": PRICE}}]}}))["handled"] is False
        assert db.scalar(select(SolMemberSubscription).where(SolMemberSubscription.stripe_customer_id == "cus_1")).status == "canceled"

        # 4) charge.refunded → un-count the settled contribution (payment disputed)
        WH.handle_event(db, _evt("charge.refunded", {"payment_intent": "pi_1"}))
        assert db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == p0.id)).status == "refunded"
        reloaded = db.get(SolPayment, p0.id)
        assert reloaded.status == "disputed" and reloaded.disputed_at is not None

        # 4b) re-confirm guard: a retried checkout.session.completed AFTER a refund
        # must NOT re-settle the reversed contribution
        WH.handle_event(db, _evt("checkout.session.completed",
            {"metadata": {"sol_payment_id": str(p0.id)}, "payment_intent": "pi_1", "payment_status": "paid"}))
        assert db.get(SolPayment, p0.id).status == "disputed"
        assert db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == p0.id)).status == "refunded"

        db.close(); conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
