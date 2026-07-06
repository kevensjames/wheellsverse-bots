"""Stage 24 tests — Sol v1 late policy (grace period + delinquency escalation).

A member is DELINQUENT once a contribution is unpaid beyond the circle's grace
period; the organizer is then escalated. NON-CUSTODIAL: reads + a coordination
alert only. Pure classifier/validation tests + a DB-gated e2e.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import delinquency as D
from app.services.sol_v1 import lifecycle as LC
from app.services.sol_v1.lifecycle import SolError


# ── pure ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "due,today,expected",
    [
        (date(2026, 6, 1), date(2026, 6, 1), 0),   # due today
        (date(2026, 6, 5), date(2026, 6, 1), 0),   # not yet due → 0
        (date(2026, 5, 25), date(2026, 6, 1), 7),  # a week over
    ],
)
def test_days_overdue(due, today, expected):
    assert D.days_overdue(due, today) == expected


@pytest.mark.parametrize(
    "due,grace,expected",
    [
        (date(2026, 5, 25), 5, True),    # 7 days over, 5 grace → delinquent
        (date(2026, 5, 28), 5, False),   # 4 days over, 5 grace → within grace
        (date(2026, 5, 27), 5, False),   # exactly 5 over → NOT past grace (strictly greater)
        (date(2026, 5, 26), 5, True),    # 6 over > 5
        (date(2026, 6, 1), 0, False),    # due today, 0 grace → not overdue
    ],
)
def test_is_delinquent(due, grace, expected):
    assert D.is_delinquent(due_date=due, today=date(2026, 6, 1), grace_days=grace) is expected


def test_create_group_rejects_bad_grace():
    # validation fires before any DB use, so db can be None here
    for bad in (-1, 91, 1000):
        with pytest.raises(SolError) as e:
            LC.create_group(None, organizer_id=uuid4(), name="x",
                            contribution_amount=Decimal("10"), frequency="weekly",
                            member_limit=2, grace_period_days=bad)
        assert e.value.status_code == 400


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB delinquency flow DEFERRED",
)
def test_delinquency_end_to_end_on_real_db(monkeypatch):
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate, SolCycle, SolGroup, SolMembership,
        SolPayment, SolPaymentProfile, SolPaymentProof,
    )
    from app.services.sol_v1 import ledger as LG

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    # NullPool: each connection is truly CLOSED on return (not pool-retained), so a
    # read txn can't linger idle-in-transaction and deadlock the teardown DROP SCHEMA
    # when the suite's pool is warm (this test passed standalone but hung in-suite).
    engine = create_engine(url, future=True, poolclass=NullPool)
    schema = "sol_v1_delinquency_e2e"
    org, alice, bob = uuid4(), uuid4(), uuid4()
    all_models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof)

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in all_models:
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (org, alice, bob):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    today = date(2026, 6, 1)  # cycles below are due in May → well overdue

    def build(grace):
        g = LC.create_group(db, organizer_id=org, name=f"Circle g{grace}",
                            contribution_amount=Decimal("40.00"), frequency="weekly",
                            member_limit=3, grace_period_days=grace)
        LC.join_group(db, user_id=alice, invite_code=g.invite_code)
        LC.join_group(db, user_id=bob, invite_code=g.invite_code)
        LC.lock_group(db, group_id=g.id, actor_id=org, order_mode="random",
                      start_date=date(2026, 5, 1), rng=Random(4))
        _, _, cycles = LC.get_group_for_member(db, group_id=g.id, user_id=org)
        # activate the FIRST cycle (due 2026-05-08 → 24 days overdue as of `today`)
        LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=org)
        return g, cycles[0]

    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)
        # This e2e exercises the DB LOGIC in an isolated localhost schema. The notify
        # hooks fired by activate/mark/confirm open their OWN app SessionLocal (which
        # points at the remote prod pooler) — no-op them so the test never touches an
        # external DB and stays fast + deterministic. Delivery is unit-tested elsewhere.
        monkeypatch.setattr("app.services.sol_v1.notifications._emit_event_soft", lambda **kw: None)

        # Circle A: 5-day grace → the 24-day-overdue payers ARE delinquent.
        ga, cyc_a = build(5)
        delq = D.find_delinquencies(db, group_id=ga.id, actor_id=org, today=today)
        assert len(delq) == 2  # both payers of the activated cycle
        assert all(d["max_days_overdue"] == 24 and d["overdue_count"] == 1 for d in delq)
        assert all(d["total_owed"] == Decimal("40.00") for d in delq)
        # sorted worst-first, oldest_due is the cycle due date
        assert delq[0]["oldest_due_date"] == date(2026, 5, 8)

        # authz: a non-organizer cannot view delinquencies
        with pytest.raises(SolError) as e:
            D.find_delinquencies(db, group_id=ga.id, actor_id=alice, today=today)
        assert e.value.status_code == 403

        # a payer who settles up drops off the delinquency list
        pay = db.scalar(
            select(SolPayment).where(SolPayment.cycle_id == cyc_a.id).limit(1)
        )
        LG.mark_paid(db, payment_id=pay.id, actor_id=pay.payer_id, method="zelle")
        LG.confirm_received(db, payment_id=pay.id, actor_id=pay.payee_id)
        after = D.find_delinquencies(db, group_id=ga.id, actor_id=org, today=today)
        assert len(after) == 1 and after[0]["user_id"] != pay.payer_id

        # Circle B: 30-day grace → the SAME 24-day-overdue is still within grace.
        gb, _ = build(30)
        assert D.find_delinquencies(db, group_id=gb.id, actor_id=org, today=today) == []

        # escalation LOGIC — monkeypatch the notify hook so this asserts WHO gets
        # escalated without depending on the app SessionLocal (which the stage
        # verifier deliberately points at a dead host). The organizer is never
        # escalated to themselves.
        escalated = []
        monkeypatch.setattr(
            "app.services.sol_v1.notifications.notify_member_delinquent",
            lambda **kw: escalated.append(kw["member_id"]),
        )
        sent = D.notify_organizer_delinquencies(db, today)
        assert sent >= 1 and len(escalated) == sent
        assert org not in escalated  # organizer never escalated to themselves

        db.rollback()  # end the open read txn so teardown's DROP SCHEMA can't deadlock on its locks
        db.close()
        conn.close()
    finally:
        engine.dispose()  # close pooled connections (release any lingering locks) BEFORE dropping
        cleanup = create_engine(url, future=True, poolclass=NullPool)
        with cleanup.begin() as c2:
            # pytest runs serially, so at THIS teardown any idle-in-transaction backend
            # is a stray connection holding this isolated schema — clear it so the DROP
            # can't deadlock (this test passed standalone but hung in the warm-pool suite).
            c2.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND state = 'idle in transaction'"
            ))
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        cleanup.dispose()
