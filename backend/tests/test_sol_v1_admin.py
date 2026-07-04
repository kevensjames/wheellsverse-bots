"""Stage 13 tests — Sol v1 admin (operator) dashboard.

Two concerns:
  1. AUTHZ (the security boundary): every /admin/sol-v1/* route is admin-token
     gated. No token / wrong token → 403. A member session (Supabase cookie, no
     admin token) can never reach these. Driven over HTTP via the TestClient.
  2. Aggregation correctness: overview/risk/disputes/groups/group_detail/activity
     computed over a seeded circle on real Postgres (service-level, isolated schema).

NON-CUSTODIAL: read-only, no money.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.config import settings

ADMIN = {"X-Admin-Token": settings.admin_token}
ROUTES = [
    "/admin/sol-v1/overview",
    "/admin/sol-v1/risk",
    "/admin/sol-v1/disputes",
    "/admin/sol-v1/groups",
    "/admin/sol-v1/groups/" + str(uuid4()),
    "/admin/sol-v1/activity",
]


# ── authz: the security boundary ───────────────────────────────────────────────


def test_every_admin_route_requires_a_token(client):
    for path in ROUTES:
        r = client.get(path)  # no X-Admin-Token header
        assert r.status_code == 403, f"UNGATED: {path} returned {r.status_code}"


def test_wrong_token_is_rejected(client):
    for path in ROUTES:
        r = client.get(path, headers={"X-Admin-Token": "definitely-not-the-token"})
        assert r.status_code == 403, f"{path} accepted a bad token"


def test_overview_ok_with_admin_token(client):
    r = client.get("/admin/sol-v1/overview", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {
        "groups", "members_total", "payments", "cycles",
        "recorded_confirmed_volume", "attention",
    }
    assert body["attention"]["disputed"] == 0  # empty DB


def test_group_detail_404_with_token(client):
    r = client.get("/admin/sol-v1/groups/" + str(uuid4()), headers=ADMIN)
    assert r.status_code == 404


def test_admin_router_paths():
    from app.routers.sol_v1_admin import router

    assert {r.path for r in router.routes} == {
        "/admin/sol-v1/overview",
        "/admin/sol-v1/risk",
        "/admin/sol-v1/disputes",
        "/admin/sol-v1/groups",
        "/admin/sol-v1/groups/{group_id}",
        "/admin/sol-v1/activity",
        "/admin/sol-v1/supervisor",
        "/admin/sol-v1/health",
        "/admin/sol-v1/metrics",
    }


def test_router_is_token_gated_at_the_router_level():
    # the dependency is declared on the router (gates EVERY route), not per-route
    from app.dependencies.admin import require_admin_token
    from app.routers.sol_v1_admin import router

    dep_calls = [d.dependency for d in router.dependencies]
    assert require_admin_token in dep_calls


# ── aggregation correctness (isolated schema) ──────────────────────────────────


def _db():
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
        SolPaymentProof,
    )

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_admin_e2e"
    models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProof)
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
    reason="TEST_DATABASE_URL not set — admin aggregation flow DEFERRED",
)
def test_aggregations_over_a_seeded_circle():
    from sqlalchemy import text

    from app.services.sol_v1 import admin_metrics as M
    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    engine, conn, db, schema = _db()
    organizer, alice, bob, carol, dave = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    today = date(2026, 7, 2)
    try:
        _add_profiles(conn, organizer, alice, bob, carol, dave)

        g = LC.create_group(
            db, organizer_id=organizer, name="Rent circle",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=5,
        )
        for u in (alice, bob, carol, dave):
            LC.join_group(db, user_id=u, invite_code=g.invite_code)
        # start far in the past so the first cycle is already overdue
        LC.lock_group(db, group_id=g.id, actor_id=organizer,
                      order_mode="random", start_date=date(2020, 1, 1), rng=Random(3))
        _, _, cycles = LC.get_group_for_member(db, group_id=g.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        assert len(payments) == 4
        p0, p1, p2, p3 = payments

        # p0 → confirmed; p1 → disputed (w/ proof); p2 → pending (overdue);
        # p3 → marked-but-unconfirmed (past due) = the "mark-to-vanish" case
        LG.mark_paid(db, payment_id=p0.id, actor_id=p0.payer_id, method="zelle")
        LG.confirm_received(db, payment_id=p0.id, actor_id=p0.payee_id)
        LG.mark_paid(db, payment_id=p1.id, actor_id=p1.payer_id, method="cash",
                     proof_image_url="https://example.test/proof.png")
        LG.dispute(db, payment_id=p1.id, actor_id=p1.payee_id)
        LG.mark_paid(db, payment_id=p3.id, actor_id=p3.payer_id, method="venmo")

        ov = M.overview(db, today)
        assert ov["payments"]["confirmed"] == 1
        assert ov["payments"]["disputed"] == 1
        assert ov["payments"]["pending"] == 1
        assert ov["payments"]["marked"] == 1
        assert ov["payments"]["total"] == 4
        assert ov["groups"]["locked"] == 1 and ov["members_total"] == 5
        # the fix: a past-due 'marked' payment surfaces as 'unconfirmed', NOT hidden
        assert ov["attention"]["overdue"] == 1      # p2 (pending, past due)
        assert ov["attention"]["unconfirmed"] == 1  # p3 (marked, past due) — the reopened hole
        assert ov["attention"]["disputed"] == 1     # p1
        assert ov["recorded_confirmed_volume"] == Decimal("30.00")  # only p0

        risk = M.risk_items(db, today)
        assert risk[0]["kind"] == "disputed"  # disputed triaged first
        assert {i["kind"] for i in risk} == {"disputed", "overdue", "unconfirmed"}
        assert {i["payment_id"] for i in risk} == {p1.id, p2.id, p3.id}

        disp = M.disputes(db)
        assert len(disp) == 1 and disp[0]["payment_id"] == p1.id and disp[0]["proof_count"] == 1

        grps = M.groups(db)
        assert len(grps) == 1 and grps[0]["member_count"] == 5 and grps[0]["cycles_total"] >= 1

        detail = M.group_detail(db, group_id=g.id, today=today)
        assert len(detail["members"]) == 5
        assert len(detail["payments"]) == 4
        assert len(detail["reputations"]) == 5

        act = M.recent_activity(db, limit=50)
        assert {"created", "marked", "confirmed", "disputed"} <= {a["event"] for a in act}
        # newest-first
        assert all(act[i]["at"] >= act[i + 1]["at"] for i in range(len(act) - 1))

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
