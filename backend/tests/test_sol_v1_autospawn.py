"""Stage 19 tests — auto-spawn a template's next instance on fill.

When a join FILLS a template instance, the next open instance is auto-spawned
(and the waitlist notified) — UNLESS another open instance of the template still
has room, or the group is standalone (no template). Best-effort + fail-soft.
NON-CUSTODIAL: only coordination records are created.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest


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
    schema = "sol_v1_autospawn_e2e"
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


def _instances(db, template_id):
    from sqlalchemy import select

    from app.models.sol import SolGroup

    return list(db.scalars(select(SolGroup).where(SolGroup.template_id == template_id)).all())


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — auto-spawn DB flow DEFERRED",
)
def test_fill_auto_spawns_next_instance_and_notifies_waitlist():
    from sqlalchemy import text

    from app.services.sol_v1 import lifecycle as LC
    from app.services.sol_v1 import notifications as N
    from app.services.sol_v1 import templates as T
    from app.services.sol_v1 import waitlist as W

    engine, conn, db, schema = _db()
    creator, joiner, waiter = uuid4(), uuid4(), uuid4()
    try:
        _add_profiles(conn, creator, joiner, waiter)
        tpl = T.create_template(db, creator_id=creator, name="Rent",
            contribution_amount=Decimal("100.00"), frequency="monthly",
            member_limit=2, visibility="public")
        W.join_waitlist(db, template_id=tpl.id, user_id=waiter)
        g1 = T.spawn_instance(db, template_id=tpl.id, actor_id=creator)  # 1 member (creator)
        assert len(_instances(db, tpl.id)) == 1

        # joiner joins g1 → g1 full (2/2) → auto-spawn g2
        LC.join_group(db, user_id=joiner, invite_code=g1.invite_code)
        insts = _instances(db, tpl.id)
        assert len(insts) == 2
        g2 = next(g for g in insts if g.id != g1.id)
        assert g2.status == "open" and g2.template_id == tpl.id and g2.round_number == 1

        # the waiter was nudged for BOTH the manual spawn (g1) and the auto-spawn (g2)
        openings = [n for n in N.list_for_user(db, user_id=waiter) if n.kind == "circle_opening"]
        assert len(openings) == 2

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — auto-spawn guard DEFERRED",
)
def test_no_auto_spawn_when_another_open_instance_has_room():
    from sqlalchemy import text

    from app.services.sol_v1 import lifecycle as LC
    from app.services.sol_v1 import templates as T

    engine, conn, db, schema = _db()
    creator, joiner = uuid4(), uuid4()
    try:
        _add_profiles(conn, creator, joiner)
        tpl = T.create_template(db, creator_id=creator, name="Rent",
            contribution_amount=Decimal("100.00"), frequency="monthly",
            member_limit=2, visibility="public")
        g1 = T.spawn_instance(db, template_id=tpl.id, actor_id=creator)
        T.spawn_instance(db, template_id=tpl.id, actor_id=creator)  # g2, open, has room
        assert len(_instances(db, tpl.id)) == 2

        # filling g1 must NOT spawn a third — g2 can still take members
        LC.join_group(db, user_id=joiner, invite_code=g1.invite_code)
        assert len(_instances(db, tpl.id)) == 2

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — standalone DEFERRED",
)
def test_standalone_group_fill_does_not_auto_spawn():
    from sqlalchemy import func, select, text

    from app.models.sol import SolCircleTemplate
    from app.services.sol_v1 import lifecycle as LC

    engine, conn, db, schema = _db()
    organizer, joiner = uuid4(), uuid4()
    try:
        _add_profiles(conn, organizer, joiner)
        g = LC.create_group(db, organizer_id=organizer, name="Standalone",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=2)
        assert g.template_id is None
        # filling a NON-template group must not create any template/instance
        LC.join_group(db, user_id=joiner, invite_code=g.invite_code)
        assert db.scalar(select(func.count(SolCircleTemplate.id))) == 0

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
