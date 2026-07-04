"""Stage 4 tests — Sol v1 reminders (due/overdue sweep + member view).

Offline: due-date bucketing, digest text, scheduler gating/parsing, router
wiring. DB-gated: mark_overdue_late + scan_summary + member_reminders against
real Postgres (overdue cycle → payments flip to 'late').
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import reminder_scheduler as SCHED
from app.services.sol_v1 import reminders as RM

TODAY = date(2026, 7, 2)


# ── pure: due-date bucketing ──────────────────────────────────────────────────


def test_classify_due_buckets():
    assert RM.classify_due(date(2020, 1, 1), TODAY) == "overdue"
    assert RM.classify_due(TODAY, TODAY) == "due_today"
    assert RM.classify_due(TODAY + timedelta(days=3), TODAY, upcoming_within_days=7) == "upcoming"
    assert RM.classify_due(TODAY + timedelta(days=7), TODAY, upcoming_within_days=7) == "upcoming"
    assert RM.classify_due(TODAY + timedelta(days=8), TODAY, upcoming_within_days=7) == "scheduled"


def test_build_operator_digest_mentions_counts():
    txt = RM.build_operator_digest(
        marked_late=2,
        summary={"overdue": 3, "due_today": 1, "upcoming": 4, "awaiting_confirmation": 5},
    )
    assert "late" in txt
    for token in ("3", "1", "4", "5"):
        assert token in txt


def test_digest_surfaces_disputes():
    txt = RM.build_operator_digest(
        marked_late=0,
        summary={"overdue": 0, "due_today": 0, "upcoming": 0,
                 "awaiting_confirmation": 0, "disputed": 2},
    )
    assert "disputed" in txt and "2" in txt


# ── scheduler: gating + parsing (no thread started) ──────────────────────────


def test_scheduler_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SOL_V1_REMINDERS_ENABLED", raising=False)
    assert SCHED.start() is False          # never starts a thread when unset
    assert SCHED.is_running() is False
    st = SCHED.status()
    assert st["enabled"] is False and st["running"] is False


def test_scheduler_run_marker_roundtrip(tmp_path, monkeypatch):
    # durable per-day marker survives a process restart so the digest can't
    # re-fire within the same scheduled hour
    marker = tmp_path / "sol_marker"
    monkeypatch.setattr(SCHED, "_marker_path", lambda: marker)
    assert SCHED._read_marker() is None
    SCHED._write_marker("20260703")
    assert SCHED._read_marker() == "20260703"


def test_scheduler_hour_parsing(monkeypatch):
    monkeypatch.setenv("SOL_V1_REMINDERS_HOUR_UTC", "9")
    assert SCHED._scheduled_hour() == 9
    monkeypatch.setenv("SOL_V1_REMINDERS_HOUR_UTC", "99")   # clamp to 23
    assert SCHED._scheduled_hour() == 23
    monkeypatch.setenv("SOL_V1_REMINDERS_HOUR_UTC", "nope")  # bad → default 14
    assert SCHED._scheduled_hour() == 14


# ── router wiring ─────────────────────────────────────────────────────────────


def test_reminders_router_registers_path():
    from app.routers.sol_v1_reminders import router

    assert {r.path for r in router.routes} == {"/sol/v1/reminders"}


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB reminders flow DEFERRED",
)
def test_reminders_flow_on_real_db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import SolCircleTemplate, SolCycle, SolGroup, SolMembership, SolPayment
    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_reminders_e2e"
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment)

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

        group = LC.create_group(
            db, organizer_id=organizer, name="Overdue circle",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        # Lock far in the past so cycle 1 is already overdue.
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2020, 1, 1), rng=Random(2))

        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        assert len(payments) == 2 and all(p.status == "pending" for p in payments)

        today = date(2026, 7, 2)
        flipped = RM.mark_overdue_late(db, today)
        assert flipped == 2
        assert all(db.get(SolPayment, p.id).status == "late" for p in payments)

        summary = RM.scan_summary(db, today)
        assert summary["overdue"] == 2

        # a payer sees the item they owe (overdue, late); the recipient sees it incoming
        payer_id = payments[0].payer_id
        payee_id = payments[0].payee_id
        payer_view = RM.member_reminders(db, user_id=payer_id, today=today)
        assert any(
            i["kind"] == "overdue" and i["status"] == "late" and i["role"] == "payer"
            for i in payer_view["as_payer"]
        )
        payee_view = RM.member_reminders(db, user_id=payee_id, today=today)
        assert len(payee_view["as_payee"]) == 2 and payee_view["as_payer"] == []

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
