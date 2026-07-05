"""Stage 23 tests — Sol v1 member timeline (the "what's next" projection).

Read-only: assembles contributions + payouts + milestones from existing rows.
Pure classifier/label tests + a DB-gated e2e (skipif no TEST_DATABASE_URL).
NON-CUSTODIAL: no writes, no money movement.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import timeline as T

TODAY = date(2026, 6, 1)


# ── pure: contribution status ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,due,expected",
    [
        ("confirmed", date(2026, 5, 1), "paid"),
        ("waived", date(2026, 5, 1), "waived"),
        ("disputed", date(2026, 5, 1), "disputed"),
        ("marked", date(2026, 5, 1), "awaiting_confirmation"),
        ("pending", date(2026, 5, 1), "overdue"),      # unpaid, past due
        ("late", date(2026, 5, 1), "overdue"),
        ("pending", date(2026, 6, 1), "due_today"),    # unpaid, due today
        ("pending", date(2026, 7, 1), "upcoming"),     # unpaid, future
    ],
)
def test_contribution_status(status, due, expected):
    assert T.contribution_status(payment_status=status, due_date=due, today=TODAY) == expected


@pytest.mark.parametrize(
    "cstatus,due,expected",
    [
        ("complete", date(2026, 5, 1), "received"),
        ("active", date(2026, 6, 1), "incoming"),
        ("pending", date(2026, 6, 1), "awaiting_start"),   # due but organizer hasn't started it
        ("pending", date(2026, 5, 1), "awaiting_start"),   # past due, still not started
        ("pending", date(2026, 7, 1), "scheduled"),        # future
    ],
)
def test_payout_status(cstatus, due, expected):
    assert T.payout_status(cycle_status=cstatus, due_date=due, today=TODAY) == expected


def test_labels_are_populated():
    for s in T.CONTRIBUTION_STATUSES:
        lab = T.contribution_labels(status=s, circle="Sunset Savers", amount=Decimal("50"), due_date=TODAY)
        assert lab["title"] and "Sunset Savers" in lab["detail"]
    for s in T.PAYOUT_STATUSES:
        lab = T.payout_labels(status=s, circle="Sunset Savers", amount=Decimal("100"), due_date=TODAY)
        assert lab["title"] and "$100.00" in lab["detail"]


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB timeline flow DEFERRED",
)
def test_timeline_end_to_end_on_real_db():
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate, SolCycle, SolGroup, SolMembership,
        SolPayment, SolPaymentProfile, SolPaymentProof,
    )
    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_timeline_e2e"
    organizer, alice, bob, stranger = uuid4(), uuid4(), uuid4(), uuid4()
    all_models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof)

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in all_models:
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (organizer, alice, bob, stranger):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)

        group = LC.create_group(
            db, organizer_id=organizer, name="Timeline circle",
            contribution_amount=Decimal("50.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2026, 1, 1), rng=Random(2))
        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        for cyc in cycles:
            LG.activate_cycle(db, cycle_id=cyc.id, actor_id=organizer)

        today = date(2026, 6, 1)

        # A non-member sees an empty timeline.
        empty = T.build_timeline(db, user_id=stranger, today=today)
        assert empty["events"] == []

        # The organizer: 2 contributions (payer in the 2 cycles they don't receive)
        # + 1 payout (the cycle they receive). All 3 cycles activated.
        tl = T.build_timeline(db, user_id=organizer, today=today)
        evs = tl["events"]
        contribs = [e for e in evs if e["kind"] == "contribution"]
        payouts = [e for e in evs if e["kind"] == "payout"]
        assert len(contribs) == 2
        assert len(payouts) == 1
        # payout is the nominal pot: contribution x (members - 1) = 50 x 2
        assert payouts[0]["amount"] == Decimal("100.00")
        # chronological, ascending by date
        assert [e["date"] for e in evs] == sorted(e["date"] for e in evs)
        # deep-link: contribution events carry a payment_id; payouts don't
        assert all(c["payment_id"] is not None for c in contribs)
        assert payouts[0]["payment_id"] is None

        # Confirm one of the organizer's contributions → it reads 'paid'.
        a_payment = db.scalar(
            select(SolPayment).join(SolCycle, SolPayment.cycle_id == SolCycle.id)
            .where(SolPayment.payer_id == organizer, SolCycle.group_id == group.id)
        )
        LG.mark_paid(db, payment_id=a_payment.id, actor_id=organizer, method="zelle")
        LG.confirm_received(db, payment_id=a_payment.id, actor_id=a_payment.payee_id)
        tl2 = T.build_timeline(db, user_id=organizer, today=today)
        paid = [e for e in tl2["events"] if e["kind"] == "contribution" and e["payment_id"] == a_payment.id]
        assert paid and paid[0]["status"] == "paid"

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
