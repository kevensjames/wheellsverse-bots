"""Stage 22 tests — Sol v1 open-circle membership management (leave + remove).

Before a circle locks, a member may LEAVE and the organizer may REMOVE another
member — both free the seat. After lock the rotation is fixed, so both are 409'd.
NON-CUSTODIAL: a membership is pure coordination; nothing is owed before lock.

Pure router-wiring check + a DB-gated e2e (skipif no TEST_DATABASE_URL).
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import lifecycle as LC
from app.services.sol_v1.lifecycle import SolError


def test_router_registers_membership_delete_routes():
    from app.routers.sol_v1 import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes if "members" in r.path}
    assert ("/sol/v1/groups/{group_id}/members/me", ("DELETE",)) in paths
    assert ("/sol/v1/groups/{group_id}/members/{user_id}", ("DELETE",)) in paths


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB membership flow DEFERRED",
)
def test_membership_leave_and_remove_on_real_db():
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate, SolCycle, SolGroup, SolMembership,
        SolPayment, SolPaymentProfile, SolPaymentProof,
    )

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_membership_e2e"
    organizer, alice, bob, carol = uuid4(), uuid4(), uuid4(), uuid4()
    all_models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof)

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in all_models:
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (organizer, alice, bob, carol):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    def _count(db, gid):
        return db.scalar(select(func.count(SolMembership.id)).where(SolMembership.group_id == gid))

    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)

        group = LC.create_group(
            db, organizer_id=organizer, name="Membership circle",
            contribution_amount=Decimal("40.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        assert _count(db, group.id) == 3  # organizer + alice + bob (full)

        # ── self-leave: a member backs out; the seat frees up ─────────────────
        # organizer cannot leave their own circle
        with pytest.raises(SolError) as e:
            LC.leave_group(db, group_id=group.id, user_id=organizer)
        assert e.value.status_code == 409
        # a non-member leaving is a 404
        with pytest.raises(SolError) as e:
            LC.leave_group(db, group_id=group.id, user_id=carol)
        assert e.value.status_code == 404
        LC.leave_group(db, group_id=group.id, user_id=bob)
        assert _count(db, group.id) == 2
        # the freed seat is joinable again (was full at 3)
        LC.join_group(db, user_id=carol, invite_code=group.invite_code)
        assert _count(db, group.id) == 3

        # ── organizer remove (kick) ───────────────────────────────────────────
        # a non-organizer cannot remove anyone
        with pytest.raises(SolError) as e:
            LC.remove_member(db, group_id=group.id, actor_id=alice, target_user_id=carol)
        assert e.value.status_code == 403
        # the organizer cannot remove themselves
        with pytest.raises(SolError) as e:
            LC.remove_member(db, group_id=group.id, actor_id=organizer, target_user_id=organizer)
        assert e.value.status_code == 400
        # removing a non-member is a 404
        with pytest.raises(SolError) as e:
            LC.remove_member(db, group_id=group.id, actor_id=organizer, target_user_id=bob)
        assert e.value.status_code == 404
        # the organizer removes carol → seat frees
        LC.remove_member(db, group_id=group.id, actor_id=organizer, target_user_id=carol)
        assert _count(db, group.id) == 2

        # ── after lock, membership is frozen ──────────────────────────────────
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2026, 1, 1), rng=Random(3))
        with pytest.raises(SolError) as e:
            LC.leave_group(db, group_id=group.id, user_id=alice)      # can't leave a locked circle
        assert e.value.status_code == 409
        with pytest.raises(SolError) as e:
            LC.remove_member(db, group_id=group.id, actor_id=organizer, target_user_id=alice)
        assert e.value.status_code == 409
        # the roster is intact after all that (organizer + alice, both with a cycle)
        assert _count(db, group.id) == 2
        n_cycles = db.scalar(select(func.count(SolCycle.id)).where(SolCycle.group_id == group.id))
        assert n_cycles == 2

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
