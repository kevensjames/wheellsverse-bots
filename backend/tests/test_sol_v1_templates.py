"""Stage 17 tests — Sol v1 templates (blueprint) + instances + rounds.

Offline: router wiring + the non-custodial (no bank fields) guarantee. DB: create
a blueprint, spawn an instance (a group carrying template_id + round 1), owner
scoping (another user is 403), and start_next_round cloning the cohort into a new
round-2 group. NON-CUSTODIAL: blueprints/instances are coordination records only.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest


# ── offline ─────────────────────────────────────────────────────────────────


def test_templates_router_paths():
    from app.routers.sol_v1_templates import router

    assert {r.path for r in router.routes} == {
        "/sol/v1/templates",
        "/sol/v1/templates/{template_id}",
        "/sol/v1/templates/{template_id}/spawn",
        "/sol/v1/groups/{group_id}/next-round",
    }


def test_template_model_has_no_bank_fields():
    from app.models.sol import SolCircleTemplate

    cols = {c.name for c in SolCircleTemplate.__table__.columns}
    assert not (cols & {"routing_number", "account_number", "card_number", "cvv", "iban", "balance"})


# ── DB ──────────────────────────────────────────────────────────────────────


def _db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import SolCircleTemplate, SolGroup, SolMembership

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_templates_e2e"
    models = (SolCircleTemplate, SolGroup, SolMembership)  # template before group (FK)
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
    reason="TEST_DATABASE_URL not set — templates DB flow DEFERRED",
)
def test_create_spawn_and_owner_scoping():
    from sqlalchemy import text

    from app.services.sol_v1 import templates as T
    from app.services.sol_v1.lifecycle import SolError

    engine, conn, db, schema = _db()
    creator, stranger = uuid4(), uuid4()
    try:
        _add_profiles(conn, creator, stranger)

        tpl = T.create_template(
            db, creator_id=creator, name="Rent $100/mo",
            contribution_amount=Decimal("100.00"), frequency="monthly", member_limit=5,
        )
        assert tpl.visibility == "invite_only" and tpl.active is True

        # spawn an instance → a group carrying template_id + round 1, organizer enrolled
        g1 = T.spawn_instance(db, template_id=tpl.id, actor_id=creator)
        assert g1.template_id == tpl.id and g1.round_number == 1 and g1.status == "open"
        assert g1.contribution_amount == Decimal("100.00") and g1.member_limit == 5
        g2 = T.spawn_instance(db, template_id=tpl.id, actor_id=creator, name="Rent — cohort 2")
        assert g2.name == "Rent — cohort 2"

        # instances_of lists both, newest first
        insts = T.instances_of(db, template_id=tpl.id, creator_id=creator)
        assert {g.id for g in insts} == {g1.id, g2.id}

        # owner scoping: a stranger can neither read nor spawn from the template
        with pytest.raises(SolError) as e1:
            T.get_template(db, template_id=tpl.id, creator_id=stranger)
        assert e1.value.status_code == 403
        with pytest.raises(SolError) as e2:
            T.spawn_instance(db, template_id=tpl.id, actor_id=stranger)
        assert e2.value.status_code == 403

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — next-round DB flow DEFERRED",
)
def test_next_round_clones_the_cohort():
    from sqlalchemy import text

    from app.models.sol import SolMembership
    from app.services.sol_v1 import lifecycle as LC
    from app.services.sol_v1 import templates as T
    from app.services.sol_v1.lifecycle import SolError

    engine, conn, db, schema = _db()
    organizer, alice, bob, stranger = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        _add_profiles(conn, organizer, alice, bob, stranger)

        g = LC.create_group(db, organizer_id=organizer, name="Round 1",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=3)
        LC.join_group(db, user_id=alice, invite_code=g.invite_code)
        LC.join_group(db, user_id=bob, invite_code=g.invite_code)

        # can't start the next round until the current one is complete
        with pytest.raises(SolError) as e:
            T.start_next_round(db, group_id=g.id, actor_id=organizer)
        assert e.value.status_code == 409

        # simulate completion, then start the next round
        db.execute(text("UPDATE sol_groups SET status='complete' WHERE id=:i"), {"i": g.id})
        db.commit()

        # only the organizer may
        with pytest.raises(SolError) as e2:
            T.start_next_round(db, group_id=g.id, actor_id=stranger)
        assert e2.value.status_code == 403

        g2 = T.start_next_round(db, group_id=g.id, actor_id=organizer)
        assert g2.round_number == 2 and g2.previous_group_id == g.id and g2.status == "open"
        assert g2.contribution_amount == Decimal("30.00") and g2.member_limit == 3
        # the SAME cohort carried over (organizer + alice + bob)
        members = db.scalars(select_members(SolMembership, g2.id)).all()
        assert {m.user_id for m in members} == {organizer, alice, bob}

        # idempotent: a second next-round on the same completed group is rejected
        # (the review fix — otherwise it would fork into two divergent round-2s)
        with pytest.raises(SolError) as e3:
            T.start_next_round(db, group_id=g.id, actor_id=organizer)
        assert e3.value.status_code == 409

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()


def select_members(SolMembership, group_id):
    from sqlalchemy import select

    return select(SolMembership).where(SolMembership.group_id == group_id)
