"""Connect Stage C tests — non-custodial destination-charge contribution flow.

The non-custodial invariant (every charge carries transfer_data.destination) is
unit-tested; the full pay→settle→cycle-complete flow runs against real Postgres
with Stripe mocked (no network, no real charge).
"""
from __future__ import annotations

import os
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest
import stripe

from app.services.sol_v1 import stripe_charges as CH
from app.services.sol_v1.lifecycle import SolError


# ── pure: the non-custodial invariant ────────────────────────────────────────

def test_to_cents():
    assert CH.to_cents(Decimal("40.00")) == 4000
    assert CH.to_cents("9.99") == 999
    assert CH.to_cents(Decimal("0.10")) == 10


def test_direct_charge_is_on_the_recipient_account_no_destination_transfer():
    p = CH.build_direct_charge_call(
        connected_account_id="acct_recipient", amount_cents=4000,
        payment_id=uuid4(), payer_id=uuid4(),
        success_url="https://s", cancel_url="https://c",
    )
    # NON-CUSTODIAL: DIRECT charge ON the recipient's account (they are merchant
    # of record) — never a destination/transfer charge that routes through Sol.
    assert p["stripe_account"] == "acct_recipient"
    assert "transfer_data" not in p.get("payment_intent_data", {})
    assert p["line_items"][0]["price_data"]["unit_amount"] == 4000
    # Sol takes no cut
    assert "application_fee_amount" not in p and "application_fee_amount" not in p["payment_intent_data"]


def test_direct_charge_refuses_no_connected_account():
    for bad in (None, "", "   "):
        with pytest.raises(SolError) as e:
            CH.build_direct_charge_call(connected_account_id=bad, amount_cents=4000,
                                        payment_id=uuid4(), payer_id=uuid4(),
                                        success_url="https://s", cancel_url="https://c")
        assert e.value.status_code == 500  # invariant violation, never silently proceed


def test_direct_charge_rejects_nonpositive_amount():
    with pytest.raises(SolError):
        CH.build_direct_charge_call(connected_account_id="acct_x", amount_cents=0,
                                    payment_id=uuid4(), payer_id=uuid4(),
                                    success_url="s", cancel_url="c")


# ── router wiring ─────────────────────────────────────────────────────────────

def test_charges_router_paths():
    from app.routers.sol_v1_charges import router
    assert {r.path for r in router.routes} == {
        "/sol/v1/stripe/payments/{payment_id}/checkout",
        "/sol/v1/stripe/payments/{payment_id}/reconcile",
        "/sol/v1/stripe/payments/{payment_id}",
    }


# ── DB + mocked Stripe (gated) ────────────────────────────────────────────────

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set — DB flow DEFERRED")
def test_contribution_flow_on_real_db(monkeypatch):
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate,
        SolCycle, SolGroup, SolMembership, SolPayment, SolStripeAccount, SolStripePayment,
    )
    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC
    from app.services.sol_v1 import stripe_connect as SConn

    # sandbox: enabled + test key so _guard passes
    monkeypatch.setattr(SConn.settings, "STRIPE_CONNECT_ENABLED", True)
    monkeypatch.setattr(SConn.settings, "STRIPE_SECRET_KEY", "sk_test_x")

    sessions: dict = {}
    def fake_create(**kw):
        n = len(sessions) + 1
        sid, pi = f"cs_{n}", f"pi_{n}"
        sessions[sid] = {"id": sid, "payment_intent": pi, "kw": kw}
        return {"id": sid, "payment_intent": pi, "url": f"https://checkout.stripe.test/{sid}"}
    def fake_session_retrieve(sid, **kw):
        return {"id": sid, "payment_intent": sessions[sid]["payment_intent"], "payment_status": "paid"}
    def fake_pi_retrieve(pi_id, **kw):
        # a clean, fully-succeeded, un-refunded, un-disputed charge
        return {"id": pi_id, "status": "succeeded",
                "latest_charge": {"refunded": False, "amount_refunded": 0, "disputed": False}}
    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(fake_create), raising=True)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", staticmethod(fake_session_retrieve), raising=True)
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", staticmethod(fake_pi_retrieve), raising=True)

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_charges_e2e"
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolStripeAccount, SolStripePayment)
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

        group = LC.create_group(db, organizer_id=organizer, name="Stripe circle",
                                contribution_amount=Decimal("40.00"), frequency="weekly", member_limit=3)
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        LC.lock_group(db, group_id=group.id, actor_id=organizer, order_mode="random", rng=Random(6))
        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        assert len(payments) == 2
        p0, p1 = payments
        recipient_user = p0.payee_id

        # recipient NOT onboarded yet → checkout refused
        with pytest.raises(SolError) as e:
            CH.create_contribution_checkout(db, payment_id=p0.id, payer_id=p0.payer_id)
        assert e.value.status_code == 409

        # onboard the recipient (charges enabled)
        db.add(SolStripeAccount(user_id=recipient_user, stripe_account_id="acct_recip",
                                charges_enabled=True, payouts_enabled=True, details_submitted=True))
        db.commit()

        # payer checkout → destination charge to the recipient's account
        u = CH.create_contribution_checkout(db, payment_id=p0.id, payer_id=p0.payer_id)
        assert u.startswith("https://checkout.stripe.test/")
        params = sessions["cs_1"]["kw"]
        # NON-CUSTODIAL: DIRECT charge ON the recipient's connected account
        assert params["stripe_account"] == "acct_recip"
        assert "transfer_data" not in params.get("payment_intent_data", {})
        assert params["line_items"][0]["price_data"]["unit_amount"] == 4000
        sp = db.scalar(select(SolStripePayment).where(SolStripePayment.payment_id == p0.id))
        assert sp.destination_account_id == "acct_recip" and sp.status == "pending"

        # only the payer can pay
        with pytest.raises(SolError) as e:
            CH.create_contribution_checkout(db, payment_id=p0.id, payer_id=uuid4())
        assert e.value.status_code == 403

        # reconcile → Stripe reports paid → ledger payment confirmed via 'stripe'
        st = CH.reconcile(db, payment_id=p0.id, actor_id=p0.payer_id)
        assert st["status"] == "paid"
        reloaded0 = db.get(SolPayment, p0.id)
        assert reloaded0.status == "confirmed" and reloaded0.method == "stripe"
        assert db.get(SolCycle, cycles[0].id).status == "active"   # p1 still pending

        # double-charge guard: can't re-checkout a paid contribution
        with pytest.raises(SolError) as e:
            CH.create_contribution_checkout(db, payment_id=p0.id, payer_id=p0.payer_id)
        assert e.value.status_code == 409
        # IDOR: charge status is party-only
        with pytest.raises(SolError) as e:
            CH.charge_status(db, payment_id=p0.id, actor_id=uuid4())
        assert e.value.status_code == 403
        assert CH.charge_status(db, payment_id=p0.id, actor_id=p0.payer_id)["status"] == "paid"

        # settle the second → cycle completes
        CH.create_contribution_checkout(db, payment_id=p1.id, payer_id=p1.payer_id)
        CH.reconcile(db, payment_id=p1.id, actor_id=p1.payer_id)
        assert db.get(SolPayment, p1.id).status == "confirmed"
        assert db.get(SolCycle, cycles[0].id).status == "complete"

        db.close(); conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
