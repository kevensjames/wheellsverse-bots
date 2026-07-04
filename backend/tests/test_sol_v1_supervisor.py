"""Stage 15 tests — Sol v1 supervisor (read-only integrity + health monitor).

Offline: the alert builder + noteworthy gate + scheduler gating. Authz: the
/admin/sol-v1/supervisor endpoint is admin-token gated. DB: a normally-progressing
circle has NO integrity violations; INJECTED corruption (raw SQL — the normal API
can't produce it) is caught; health counts are correct. READ-ONLY, NON-CUSTODIAL.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.config import settings
from app.services.sol_v1 import supervisor as S

ADMIN = {"X-Admin-Token": settings.admin_token}


# ── offline: alert + gate + scheduler ──────────────────────────────────────────


def test_build_alert_and_noteworthy():
    clean = {"ok": True, "integrity_violations": [],
             "health": {"overdue": 0, "unconfirmed": 0, "stuck_disputes": 0},
             "checked_at": "2026-07-04"}
    assert S.is_noteworthy(clean) is False
    assert "all invariants hold" in S.build_alert(clean)

    dirty = {"ok": False,
             "integrity_violations": [{"check": "confirmed_without_timestamp",
                 "description": "x", "sample_ids": ["a", "b"], "has_more": False}],
             "health": {"overdue": 3, "unconfirmed": 1, "stuck_disputes": 0},
             "checked_at": "2026-07-04"}
    assert S.is_noteworthy(dirty) is True
    txt = S.build_alert(dirty)
    assert "integrity violation" in txt and "confirmed_without_timestamp" in txt

    # health-only (no integrity violation) is still noteworthy
    health_only = {"ok": True, "integrity_violations": [],
                   "health": {"overdue": 2, "unconfirmed": 0, "stuck_disputes": 0},
                   "checked_at": "x"}
    assert S.is_noteworthy(health_only) is True


def test_scheduler_off_by_default(monkeypatch):
    from app.services.sol_v1 import supervisor_scheduler as SCHED

    monkeypatch.delenv("SOL_V1_SUPERVISOR_ENABLED", raising=False)
    assert SCHED.start() is False and SCHED.is_running() is False
    st = SCHED.status()
    assert st["enabled"] is False and st["running"] is False


def test_scheduler_hour_parsing(monkeypatch):
    from app.services.sol_v1 import supervisor_scheduler as SCHED

    monkeypatch.setenv("SOL_V1_SUPERVISOR_HOUR_UTC", "9")
    assert SCHED._scheduled_hour() == 9
    monkeypatch.setenv("SOL_V1_SUPERVISOR_HOUR_UTC", "99")
    assert SCHED._scheduled_hour() == 23
    monkeypatch.setenv("SOL_V1_SUPERVISOR_HOUR_UTC", "bad")
    assert SCHED._scheduled_hour() == 15


# ── authz ───────────────────────────────────────────────────────────────────────


def test_supervisor_endpoint_requires_admin_token(client):
    assert client.get("/admin/sol-v1/supervisor").status_code == 403


def test_supervisor_endpoint_ok_with_token_empty_db(client):
    r = client.get("/admin/sol-v1/supervisor", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["integrity_violations"] == []
    assert body["health"] == {"overdue": 0, "unconfirmed": 0, "stuck_disputes": 0}


# ── DB: clean vs injected corruption ───────────────────────────────────────────


def _db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate,
        SolCycle, SolGroup, SolMembership, SolPayment, SolStripeAccount, SolStripePayment,
    )

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_supervisor_e2e"
    models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolStripeAccount, SolStripePayment)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for m in models:
            conn.execute(text(str(CreateTable(m.__table__).compile(dialect=postgresql.dialect()))))
    conn = engine.connect()
    conn.execute(text(f"SET search_path TO {schema}"))
    return engine, conn, Session(bind=conn), schema


def _add_profiles(conn, *uids):
    from sqlalchemy import text

    for uid in uids:
        conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})
    conn.commit()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — supervisor DB flow DEFERRED",
)
def test_clean_circle_has_no_violations_then_corruption_is_caught():
    from sqlalchemy import text

    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    engine, conn, db, schema = _db()
    organizer, alice, bob, carol = uuid4(), uuid4(), uuid4(), uuid4()
    today = date(2026, 7, 2)
    try:
        _add_profiles(conn, organizer, alice, bob, carol)
        g = LC.create_group(db, organizer_id=organizer, name="Clean",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=4)
        for u in (alice, bob, carol):
            LC.join_group(db, user_id=u, invite_code=g.invite_code)
        LC.lock_group(db, group_id=g.id, actor_id=organizer,
                      order_mode="random", start_date=date(2020, 1, 1), rng=Random(7))
        _, _, cycles = LC.get_group_for_member(db, group_id=g.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        p0, p1, p2 = payments
        LG.mark_paid(db, payment_id=p0.id, actor_id=p0.payer_id, method="zelle")
        LG.confirm_received(db, payment_id=p0.id, actor_id=p0.payee_id)

        # A normally-progressing circle is self-consistent → no integrity violations.
        rep = S.run_checks(db, today)
        assert rep["ok"] is True, rep["integrity_violations"]
        assert rep["health"]["overdue"] == 2  # p1, p2 (pending, past due)

        # INJECT corruption the API can't produce: a confirmed payment with a NULL
        # confirmation timestamp. The supervisor must catch it.
        db.execute(text("UPDATE sol_payments SET payee_confirmed_at = NULL WHERE id = :id"),
                   {"id": p0.id})
        db.commit()
        rep2 = S.run_checks(db, today)
        assert rep2["ok"] is False
        checks = {v["check"] for v in rep2["integrity_violations"]}
        assert "confirmed_without_timestamp" in checks
        v = next(v for v in rep2["integrity_violations"] if v["check"] == "confirmed_without_timestamp")
        assert str(p0.id) in v["sample_ids"]

        # A second injected inconsistency: mark the cycle 'complete' while payments
        # are still unconfirmed → the completed-cycle invariant fires too.
        db.execute(text("UPDATE sol_cycles SET status = 'complete' WHERE id = :id"),
                   {"id": cycles[0].id})
        db.commit()
        rep3 = S.run_checks(db, today)
        assert "completed_cycle_unconfirmed_payment" in {v["check"] for v in rep3["integrity_violations"]}

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — supervisor refund-case DEFERRED",
)
def test_disputed_payment_on_complete_cycle_is_not_corruption():
    """Review fix: a post-completion Stripe refund/chargeback flips a payment to
    'disputed' on an already-'complete' cycle. That's a handled business event,
    NOT an integrity violation — the supervisor must not raise a red alarm."""
    from sqlalchemy import text

    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    engine, conn, db, schema = _db()
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    today = date(2026, 7, 2)
    try:
        _add_profiles(conn, organizer, alice, bob)
        g = LC.create_group(db, organizer_id=organizer, name="Refund",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=3)
        LC.join_group(db, user_id=alice, invite_code=g.invite_code)
        LC.join_group(db, user_id=bob, invite_code=g.invite_code)
        LC.lock_group(db, group_id=g.id, actor_id=organizer,
                      order_mode="random", start_date=date(2020, 1, 1), rng=Random(1))
        _, _, cycles = LC.get_group_for_member(db, group_id=g.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)

        # complete the cycle the Stripe way: all payments confirmed, cycle complete
        db.execute(text("UPDATE sol_payments SET status='confirmed', payee_confirmed_at=now() "
                        "WHERE cycle_id = :c"), {"c": cycles[0].id})
        db.execute(text("UPDATE sol_cycles SET status='complete' WHERE id = :c"),
                   {"c": cycles[0].id})
        db.commit()
        assert S.run_checks(db, today)["ok"] is True  # all-confirmed complete cycle is clean

        # a refund/chargeback: one payment → 'disputed', cycle stays 'complete'
        db.execute(text("UPDATE sol_payments SET status='disputed', disputed_at=now() "
                        "WHERE id = :p"), {"p": payments[0].id})
        db.commit()
        rep = S.run_checks(db, today)
        assert "completed_cycle_unconfirmed_payment" not in {
            v["check"] for v in rep["integrity_violations"]
        }

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
