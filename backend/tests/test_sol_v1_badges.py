"""Stage 26 tests — Sol v1 SOL profile + badges (derived read-only achievements).

Badges are computed on demand from real history (circles completed, on-time record,
organizing) — no table, no writes. NON-CUSTODIAL. Pure predicate tests + a
DB-gated e2e that completes a real circle (hardened teardown; no remote pooler).
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import badges as B


# ── pure: the badge catalog ─────────────────────────────────────────────────────


def _stats(**over):
    base = {"circles_completed": 0, "circles_organized": 0, "actionable": 0,
            "on_time": 0, "reputation_label": "unrated"}
    base.update(over)
    return base


def test_new_member_earns_nothing():
    earned = {b["key"] for b in B.award_badges(_stats()) if b["earned"]}
    assert earned == set()
    # the catalog is still fully returned (locked), so the UI can show a wall
    assert len(B.award_badges(_stats())) == 6


def test_veteran_earns_everything():
    s = _stats(circles_completed=5, circles_organized=2, actionable=10,
               on_time=10, reputation_label="excellent")
    earned = {b["key"] for b in B.award_badges(s) if b["earned"]}
    assert earned == {"first_circle", "gold_saver", "elite_saver", "organizer",
                      "reliable_saver", "perfect_payer"}


@pytest.mark.parametrize(
    "stats,expect_earned,expect_locked",
    [
        # 1 circle, good record but one blemish (on_time < actionable) → no perfect_payer
        (_stats(circles_completed=1, actionable=5, on_time=4, reputation_label="good"),
         {"first_circle", "reliable_saver"}, {"perfect_payer", "gold_saver", "elite_saver", "organizer"}),
        # spotless but too little history (< 3 counted) → record badges stay locked
        (_stats(circles_completed=1, actionable=2, on_time=2, reputation_label="excellent"),
         {"first_circle"}, {"reliable_saver", "perfect_payer"}),
        # organizer of an in-progress circle (nothing completed yet)
        (_stats(circles_completed=0, circles_organized=1),
         {"organizer"}, {"first_circle", "gold_saver"}),
    ],
)
def test_badge_thresholds(stats, expect_earned, expect_locked):
    result = {b["key"]: b["earned"] for b in B.award_badges(stats)}
    assert all(result[k] for k in expect_earned)
    assert all(not result[k] for k in expect_locked)


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB badges flow DEFERRED",
)
def test_badges_end_to_end_on_real_db(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate, SolCycle, SolGroup, SolMembership,
        SolPayment, SolPaymentProfile, SolPaymentProof,
    )
    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True, poolclass=NullPool)
    schema = "sol_v1_badges_e2e"
    org, alice, bob, carol = uuid4(), uuid4(), uuid4(), uuid4()
    all_models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof)

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in all_models:
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (org, alice, bob, carol):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    today = date(2026, 7, 15)  # BEFORE the future due dates → payments read on-time
    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)
        # activate/mark/confirm fire notify hooks → app SessionLocal (remote pooler);
        # no-op them so this e2e stays local + deterministic.
        monkeypatch.setattr("app.services.sol_v1.notifications._emit_event_soft", lambda **kw: None)

        # a 4-member circle → each member is a payer in 3 cycles (>= 3 counted history)
        g = LC.create_group(db, organizer_id=org, name="Badge circle",
                            contribution_amount=Decimal("20.00"), frequency="weekly", member_limit=4)
        for u in (alice, bob, carol):
            LC.join_group(db, user_id=u, invite_code=g.invite_code)
        LC.lock_group(db, group_id=g.id, actor_id=org, order_mode="random",
                      start_date=date(2027, 1, 1), rng=Random(7))  # future due dates

        _, _, cycles = LC.get_group_for_member(db, group_id=g.id, user_id=org)
        for cyc in cycles:
            _, payments = LG.activate_cycle(db, cycle_id=cyc.id, actor_id=org)
            for p in payments:  # everyone pays on time and it's confirmed
                LG.mark_paid(db, payment_id=p.id, actor_id=p.payer_id, method="zelle")
                LG.confirm_received(db, payment_id=p.id, actor_id=p.payee_id)

        assert db.get(SolGroup, g.id).status == "complete"  # all cycles settled → group done

        # alice: completed 1 circle, 3 on-time payments, not the organizer
        prof = B.member_profile(db, user_id=alice, today=today)
        earned = {b["key"] for b in prof["badges"] if b["earned"]}
        assert prof["stats"]["circles_completed"] == 1
        assert prof["stats"]["actionable"] == 3 and prof["stats"]["on_time"] == 3
        assert prof["stats"]["sol_score"] == 100  # spotless
        assert {"first_circle", "reliable_saver", "perfect_payer"} <= earned
        assert "gold_saver" not in earned and "organizer" not in earned

        # the organizer additionally earns the organizer badge
        org_earned = {b["key"] for b in B.member_profile(db, user_id=org, today=today)["badges"] if b["earned"]}
        assert "organizer" in org_earned and "first_circle" in org_earned

        # a stranger: unrated, nothing earned
        st = B.member_profile(db, user_id=uuid4(), today=today)
        assert st["stats"]["sol_score"] is None and st["stats"]["circles_completed"] == 0
        assert not any(b["earned"] for b in st["badges"])

        db.rollback()
        db.close()
        conn.close()
    finally:
        engine.dispose()
        cleanup = create_engine(url, future=True, poolclass=NullPool)
        with cleanup.begin() as c2:
            c2.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND state = 'idle in transaction'"
            ))
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        cleanup.dispose()
