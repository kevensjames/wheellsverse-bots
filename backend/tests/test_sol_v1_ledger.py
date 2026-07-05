"""Stage 3 tests — Sol v1 ledger (double-confirmed member payments).

Layers:
  1. Pure-logic (no DB): the payment state machine (`next_status`) and the
     non-custodial handle guard (`validate_handle`), plus router wiring.
  2. DB-gated end-to-end (skipif no TEST_DATABASE_URL): activate → mark →
     confirm → cycle/group completion, dispute + re-mark, authz, and payment
     profiles, in an isolated schema on real Postgres.
"""
from __future__ import annotations

import os
from decimal import Decimal
from datetime import date
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import ledger as LG
from app.services.sol_v1.lifecycle import SolError

# ── pure: payment state machine ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "current,action,expected",
    [
        ("pending", "mark", "marked"),
        ("late", "mark", "marked"),
        ("disputed", "mark", "marked"),
        ("marked", "confirm", "confirmed"),
        ("marked", "dispute", "disputed"),
    ],
)
def test_next_status_allowed(current, action, expected):
    assert LG.next_status(current, action) == expected


@pytest.mark.parametrize(
    "current,action",
    [
        ("confirmed", "confirm"),   # already confirmed
        ("confirmed", "dispute"),
        ("pending", "confirm"),     # can't confirm before it's marked
        ("pending", "dispute"),
        ("marked", "mark"),         # can't re-mark a marked payment
        ("complete", "mark"),
    ],
)
def test_next_status_rejects_bad_transition(current, action):
    with pytest.raises(SolError) as e:
        LG.next_status(current, action)
    assert e.value.status_code == 409


def test_next_status_unknown_action():
    with pytest.raises(SolError) as e:
        LG.next_status("pending", "teleport")
    assert e.value.status_code == 400


# ── pure: non-custodial handle guard ──────────────────────────────────────────


@pytest.mark.parametrize(
    "method,handle,expected",
    [
        ("zelle", "user@example.com", "user@example.com"),
        ("zelle", "  user@example.com  ", "user@example.com"),  # trimmed
        ("venmo", "@coolhandle", "@coolhandle"),
        ("cashapp", "$moneytag", "$moneytag"),
        ("zelle", "555-123-4567", "555-123-4567"),   # 10-digit phone OK
        ("zelle", "+1 555 123 4567", "+1 555 123 4567"),  # +country phone OK
    ],
)
def test_validate_handle_accepts_external_rails(method, handle, expected):
    assert LG.validate_handle(method, handle) == expected


@pytest.mark.parametrize(
    "handle",
    [
        "021000021",        # 9-digit ABA routing number
        "123456789012",     # 12-digit account number
        "12345678901234567",  # 17-digit account number
        "1234-5678-9012",   # account with hyphen separators
        "021.000.021",      # routing number with dots (was a guard bypass)
        "(021)000-021",     # routing number with parens
        "1234.5678.9012",   # account with dots
        "021_000_021",      # routing number with underscores
    ],
)
def test_validate_handle_rejects_bank_numbers(handle):
    with pytest.raises(SolError) as e:
        LG.validate_handle("zelle", handle)
    assert e.value.status_code == 400


def test_validate_handle_rejects_empty_and_bad_method():
    with pytest.raises(SolError):
        LG.validate_handle("zelle", "   ")
    with pytest.raises(SolError):
        LG.validate_handle("bitcoin", "x@y.com")  # not a PROFILE_METHOD


# ── router wiring (no DB) ─────────────────────────────────────────────────────


def test_ledger_router_registers_expected_paths():
    from app.routers.sol_v1_ledger import router

    paths = {r.path for r in router.routes}
    assert paths == {
        "/sol/v1/cycles/{cycle_id}/activate",
        "/sol/v1/payments",
        "/sol/v1/payments/{payment_id}",
        "/sol/v1/payments/{payment_id}/mark",
        "/sol/v1/payments/{payment_id}/confirm",
        "/sol/v1/payments/{payment_id}/dispute",
        "/sol/v1/payments/{payment_id}/dispute/withdraw",
        "/sol/v1/payments/{payment_id}/resolve",
        "/sol/v1/payments/{payment_id}/proofs",
        "/sol/v1/payment-profiles",
        "/sol/v1/payment-profiles/{profile_id}",
    }


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB ledger flow DEFERRED",
)
def test_ledger_end_to_end_on_real_db():
    """Full manual-rail flow in an isolated schema on real Postgres."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate,
        SolCycle,
        SolGroup,
        SolMembership,
        SolPayment,
        SolPaymentProfile,
        SolPaymentProof,
    )
    from app.services.sol_v1 import lifecycle as LC

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_ledger_e2e"
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    all_models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof)

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in all_models:
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (organizer, alice, bob):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)

        group = LC.create_group(
            db, organizer_id=organizer, name="Test circle",
            contribution_amount=Decimal("50.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2026, 1, 1), rng=Random(5))

        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        assert len(cycles) == 3

        # Non-organizer cannot activate a cycle.
        with pytest.raises(SolError):
            LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=alice)

        # Drive ALL cycles to completion → the group should complete.
        first_payment = None
        for i, cyc in enumerate(cycles):
            _, payments = LG.activate_cycle(db, cycle_id=cyc.id, actor_id=organizer)
            assert len(payments) == 2                       # 3 members - 1 recipient
            assert all(p.status == "pending" and p.method is None for p in payments)
            assert all(p.amount == Decimal("50.00") for p in payments)

            if i == 0:  # re-activating an active cycle is a clean 409, never a dup
                with pytest.raises(SolError):
                    LG.activate_cycle(db, cycle_id=cyc.id, actor_id=organizer)

            for j, p in enumerate(payments):
                # authz: only the payer may mark
                with pytest.raises(SolError):
                    LG.mark_paid(db, payment_id=p.id, actor_id=p.payee_id, method="zelle")
                if i == 0 and j == 0:
                    first_payment = p
                    # exercise the dispute → re-mark path once, with a proof photo
                    LG.mark_paid(db, payment_id=p.id, actor_id=p.payer_id, method="zelle",
                                 proof_image_url="https://img/p.png")
                    LG.dispute(db, payment_id=p.id, actor_id=p.payee_id)
                    assert db.get(SolPayment, p.id).status == "disputed"
                LG.mark_paid(db, payment_id=p.id, actor_id=p.payer_id, method="cashapp")
                # authz: neither the payer nor a stranger may confirm — only the payee
                with pytest.raises(SolError):
                    LG.confirm_received(db, payment_id=p.id, actor_id=p.payer_id)
                with pytest.raises(SolError):
                    LG.confirm_received(db, payment_id=p.id, actor_id=uuid4())
                LG.confirm_received(db, payment_id=p.id, actor_id=p.payee_id)

            assert db.get(SolCycle, cyc.id).status == "complete"

        assert db.get(SolGroup, group.id).status == "complete"

        fp = first_payment
        assert fp is not None

        # list_payments: role scoping + status filter + invalid-role guard
        payer_rows = LG.list_payments(db, user_id=fp.payer_id, role="payer")
        assert payer_rows and all(r.payer_id == fp.payer_id for r in payer_rows)
        payee_rows = LG.list_payments(db, user_id=fp.payee_id, role="payee")
        assert payee_rows and all(r.payee_id == fp.payee_id for r in payee_rows)
        all_rows = LG.list_payments(db, user_id=fp.payer_id, role="all")
        assert all(fp.payer_id in (r.payer_id, r.payee_id) for r in all_rows)
        confirmed_rows = LG.list_payments(db, user_id=fp.payer_id, role="payer", status="confirmed")
        assert confirmed_rows and all(r.status == "confirmed" for r in confirmed_rows)
        with pytest.raises(SolError):
            LG.list_payments(db, user_id=fp.payer_id, role="bogus")

        # get_payment_detail: how-to-pay handles are the PAYEE's, proof present, authz
        LG.upsert_payment_profile(db, user_id=fp.payee_id, method="venmo",
                                  handle="@payee", is_default=True)
        detail_payment, proofs, pay_to, org_id = LG.get_payment_detail(
            db, payment_id=fp.id, user_id=fp.payer_id
        )
        assert detail_payment.id == fp.id
        assert org_id == organizer  # the circle organizer id is surfaced
        assert pay_to and all(pp.user_id == fp.payee_id for pp in pay_to)
        assert any(pr.image_url == "https://img/p.png" for pr in proofs)  # proof persisted
        with pytest.raises(SolError):  # a non-party cannot read the payment
            LG.get_payment_detail(db, payment_id=fp.id, user_id=uuid4())

        # add_proof: payer-only + non-empty url
        extra = LG.add_proof(db, payment_id=fp.id, actor_id=fp.payer_id,
                             image_url="https://img/extra.png")
        assert extra.payment_id == fp.id
        with pytest.raises(SolError):  # a non-payer cannot attach proof
            LG.add_proof(db, payment_id=fp.id, actor_id=fp.payee_id, image_url="https://img/x.png")
        with pytest.raises(SolError):  # empty url rejected
            LG.add_proof(db, payment_id=fp.id, actor_id=fp.payer_id, image_url="   ")

        # payment profiles: default-flip keeps exactly one default; guard; delete
        LG.upsert_payment_profile(db, user_id=alice, method="zelle",
                                  handle="alice@example.com", is_default=True)
        LG.upsert_payment_profile(db, user_id=alice, method="cashapp",
                                  handle="$alice", is_default=True)  # flips default
        profs = LG.list_payment_profiles(db, user_id=alice)
        assert len(profs) == 2
        assert sum(1 for p in profs if p.is_default) == 1          # exactly one default
        assert next(p for p in profs if p.method == "cashapp").is_default is True

        with pytest.raises(SolError):  # bank-number handle rejected
            LG.upsert_payment_profile(db, user_id=alice, method="zelle", handle="021000021")

        LG.delete_payment_profile(db, user_id=alice, profile_id=profs[0].id)
        assert len(LG.list_payment_profiles(db, user_id=alice)) == 1

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
