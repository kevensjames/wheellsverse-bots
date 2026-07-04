"""Stage 18 tests — Sol v1 template waitlist.

Offline: router wiring + non-custodial (no bank fields). DB: join is idempotent,
leave works, list is creator-scoped (a stranger is 403), my-waitlists, and — the
payoff — spawning a new instance NOTIFIES everyone waiting (circle_opening).
NON-CUSTODIAL: waitlist rows + notifications carry no money.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest


# ── offline ─────────────────────────────────────────────────────────────────


def test_waitlist_routes_registered():
    from app.routers.sol_v1_templates import router

    paths = {r.path for r in router.routes}
    assert "/sol/v1/templates/{template_id}/waitlist" in paths
    assert "/sol/v1/waitlists" in paths


def test_waitlist_model_has_no_bank_fields():
    from app.models.sol import SolWaitlist

    cols = {c.name for c in SolWaitlist.__table__.columns}
    assert not (cols & {"routing_number", "account_number", "card_number", "cvv", "iban", "balance"})
    assert cols == {"id", "template_id", "user_id", "created_at"}


# ── DB ──────────────────────────────────────────────────────────────────────


def _db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate, SolCycle, SolGroup, SolMembership, SolNotification,
        SolPayment, SolWaitlist,
    )

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_waitlist_e2e"
    # FK order: template/group/cycle/payment before waitlist + notification
    # (sol_notifications.payment_id -> sol_payments)
    models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment,
              SolWaitlist, SolNotification)
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
    reason="TEST_DATABASE_URL not set — waitlist DB flow DEFERRED",
)
def test_join_leave_owner_scope_and_notify_on_spawn():
    from sqlalchemy import text

    from app.services.sol_v1 import templates as T
    from app.services.sol_v1 import waitlist as W
    from app.services.sol_v1 import notifications as N
    from app.services.sol_v1.lifecycle import SolError

    engine, conn, db, schema = _db()
    creator, alice, bob, stranger = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        _add_profiles(conn, creator, alice, bob, stranger)
        tpl = T.create_template(
            db, creator_id=creator, name="Rent",
            contribution_amount=Decimal("100.00"), frequency="monthly", member_limit=5,
            visibility="public",
        )

        # only PUBLIC templates are self-serve waitlistable (review fix)
        priv = T.create_template(
            db, creator_id=creator, name="Private",
            contribution_amount=Decimal("100.00"), frequency="monthly", member_limit=5,
            visibility="invite_only",
        )
        with pytest.raises(SolError) as ep:
            W.join_waitlist(db, template_id=priv.id, user_id=alice)
        assert ep.value.status_code == 403

        # join is idempotent (one entry per user)
        e1 = W.join_waitlist(db, template_id=tpl.id, user_id=alice)
        e1b = W.join_waitlist(db, template_id=tpl.id, user_id=alice)
        assert e1.id == e1b.id
        W.join_waitlist(db, template_id=tpl.id, user_id=bob)

        # creator sees the waitlist (FIFO); a stranger is 403
        wl = W.list_waitlist(db, template_id=tpl.id, creator_id=creator)
        assert {w.user_id for w in wl} == {alice, bob}
        with pytest.raises(SolError) as e:
            W.list_waitlist(db, template_id=tpl.id, creator_id=stranger)
        assert e.value.status_code == 403

        # alice's my-waitlists shows the template; leaving removes her
        assert {w.template_id for w in W.my_waitlists(db, user_id=alice)} == {tpl.id}
        assert W.leave_waitlist(db, template_id=tpl.id, user_id=alice) is True
        assert W.leave_waitlist(db, template_id=tpl.id, user_id=alice) is False  # idempotent
        assert W.my_waitlists(db, user_id=alice) == []

        # THE PAYOFF: spawning a new instance notifies everyone still waiting (bob)
        group = T.spawn_instance(db, template_id=tpl.id, actor_id=creator)
        bob_notifs = N.list_for_user(db, user_id=bob)
        assert any(n.kind == "circle_opening" for n in bob_notifs)
        opening = next(n for n in bob_notifs if n.kind == "circle_opening")
        assert group.invite_code in opening.body  # the join code is in the nudge
        # alice already left → no circle_opening for her
        assert not any(n.kind == "circle_opening" for n in N.list_for_user(db, user_id=alice))

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
