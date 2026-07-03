"""Stage 5 tests — Sol v1 reputation (trust score from payer history)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import reputation as REP

DUE = date(2026, 1, 10)
TODAY = date(2026, 2, 1)


# ── pure: classification ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,marked_on,expected",
    [
        ("confirmed", date(2026, 1, 8), "on_time"),    # paid before due
        ("confirmed", date(2026, 1, 10), "on_time"),   # paid on due date
        ("confirmed", date(2026, 1, 12), "late_paid"), # paid after due
        ("confirmed", None, "on_time"),                # confirmed w/o timestamp
        ("disputed", date(2026, 1, 9), "disputed"),
        # 'marked' depends on due-vs-today (anti-gaming) — see the dedicated test.
    ],
)
def test_classify_by_status(status, marked_on, expected):
    assert REP.classify_payment(status=status, due_date=DUE, today=TODAY, marked_on=marked_on) == expected


def test_classify_pending_overdue_vs_in_flight():
    # pending + past due → overdue; pending + future due → in_flight
    assert REP.classify_payment(status="pending", due_date=DUE, today=TODAY, marked_on=None) == "overdue"
    future_due = TODAY + timedelta(days=10)
    assert REP.classify_payment(status="pending", due_date=future_due, today=TODAY, marked_on=None) == "in_flight"
    assert REP.classify_payment(status="late", due_date=DUE, today=TODAY, marked_on=None) == "overdue"


def test_classify_marked_past_due_is_overdue_not_neutral():
    # anti-gaming: an unconfirmed 'marked' claim past its due date earns NO credit
    assert REP.classify_payment(status="marked", due_date=DUE, today=TODAY, marked_on=None) == "overdue"
    future_due = TODAY + timedelta(days=10)  # …but a not-yet-due marked is neutral
    assert REP.classify_payment(status="marked", due_date=future_due, today=TODAY, marked_on=None) == "in_flight"


def test_classify_disputes_are_sticky():
    # ever-disputed + still open → 'disputed' (no credit); a re-mark can't hide it
    assert REP.classify_payment(
        status="marked", due_date=DUE, today=TODAY, marked_on=None, ever_disputed=True
    ) == "disputed"
    # ever-disputed but genuinely resolved (payee re-confirmed) → only partial credit
    assert REP.classify_payment(
        status="confirmed", due_date=DUE, today=TODAY, marked_on=date(2026, 1, 8), ever_disputed=True
    ) == "late_paid"


# ── pure: scoring ─────────────────────────────────────────────────────────────


def test_score_all_on_time_is_100_excellent():
    r = REP.score_from_counts({"on_time": 3})
    assert r["score"] == 100 and r["label"] == "excellent" and r["provisional"] is False


def test_score_unrated_when_no_actionable_history():
    r = REP.score_from_counts({"in_flight": 5})  # in_flight excluded from denominator
    assert r["score"] is None and r["label"] == "unrated" and r["actionable"] == 0


def test_score_provisional_below_threshold():
    r = REP.score_from_counts({"on_time": 1})
    assert r["score"] == 100 and r["provisional"] is True  # 1 < PROVISIONAL_BELOW


def test_score_late_paid_partial_credit():
    r = REP.score_from_counts({"late_paid": 2})  # 0.6 each → 60
    assert r["score"] == 60 and r["label"] == "fair"


def test_score_overdue_and_disputed_drag_to_zero():
    assert REP.score_from_counts({"overdue": 3})["score"] == 0
    assert REP.score_from_counts({"disputed": 2})["score"] == 0
    mixed = REP.score_from_counts({"on_time": 5, "disputed": 5})
    assert mixed["score"] == 50 and mixed["label"] == "fair"


def test_score_mostly_good():
    r = REP.score_from_counts({"on_time": 9, "late_paid": 1})  # (9 + 0.6)/10 = 96
    assert r["score"] == 96 and r["label"] == "excellent"
    g = REP.score_from_counts({"on_time": 7, "overdue": 3})    # 70
    assert g["score"] == 70 and g["label"] == "good"


# ── router wiring ─────────────────────────────────────────────────────────────


def test_reputation_router_paths():
    from app.routers.sol_v1_reputation import router

    assert {r.path for r in router.routes} == {
        "/sol/v1/reputation/me",
        "/sol/v1/groups/{group_id}/reputation",
    }


# ── DB end-to-end (gated) ─────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB reputation flow DEFERRED",
)
def test_reputation_on_real_db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import SolCycle, SolGroup, SolMembership, SolPayment
    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_reputation_e2e"
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    models = (SolGroup, SolMembership, SolCycle, SolPayment)

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
        today = datetime.now(timezone.utc).date()

        group = LC.create_group(
            db, organizer_id=organizer, name="Rep circle",
            contribution_amount=Decimal("20.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        # lock starting today → cycle 1 due today+7 (in the future)
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=today, rng=Random(4))

        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        p_paid, p_unpaid = payments[0], payments[1]

        # p_paid: paid on time (marked now ≤ due today+7) and confirmed → 100
        LG.mark_paid(db, payment_id=p_paid.id, actor_id=p_paid.payer_id, method="zelle")
        LG.confirm_received(db, payment_id=p_paid.id, actor_id=p_paid.payee_id)
        rep_good = REP.compute_reputation(db, user_id=p_paid.payer_id, today=today)
        assert rep_good["breakdown"]["on_time"] == 1 and rep_good["score"] == 100

        # p_unpaid pending: neutral now (future due) → unrated; overdue when later
        assert REP.compute_reputation(db, user_id=p_unpaid.payer_id, today=today)["score"] is None
        future = today + timedelta(days=60)
        assert REP.compute_reputation(db, user_id=p_unpaid.payer_id, today=future)["breakdown"]["overdue"] == 1

        # sticky dispute: payer marks → payee disputes → payer re-marks. The
        # dispute persists (disputed_at) and re-marking does NOT restore credit.
        LG.mark_paid(db, payment_id=p_unpaid.id, actor_id=p_unpaid.payer_id, method="zelle")
        LG.dispute(db, payment_id=p_unpaid.id, actor_id=p_unpaid.payee_id)
        LG.mark_paid(db, payment_id=p_unpaid.id, actor_id=p_unpaid.payer_id, method="cashapp")  # re-mark
        assert db.get(SolPayment, p_unpaid.id).disputed_at is not None
        rep_bad = REP.compute_reputation(db, user_id=p_unpaid.payer_id, today=today)
        assert rep_bad["breakdown"]["disputed"] == 1 and rep_bad["score"] == 0

        # group reputations: one entry per member
        reps = REP.group_reputations(db, group_id=group.id, today=today)
        assert len(reps) == 3
        assert any(r["score"] == 100 for r in reps)   # the on-time payer
        assert any(r["score"] == 0 for r in reps)      # the disputed payer

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
