"""Stage 25 tests — Sol v1 invite-code rotation (organizer resets the invite link).

Regenerating the code IMMEDIATELY invalidates the old link. Organizer-only, open
circles only. NON-CUSTODIAL: rotates a random token; no money, no member data.

Router-wiring check + a DB-gated e2e (skipif no TEST_DATABASE_URL). The e2e uses
the hardened teardown pattern (NullPool + no-op notify + terminate strays) so it
never dials the app's remote pooler and can't deadlock its own DROP SCHEMA.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.sol_v1 import lifecycle as LC
from app.services.sol_v1.lifecycle import SolError


def test_router_registers_rotate_route():
    from app.routers.sol_v1 import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes if "invite-code" in r.path}
    assert ("/sol/v1/groups/{group_id}/invite-code/rotate", ("POST",)) in paths


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB invite-rotation flow DEFERRED",
)
def test_invite_rotation_end_to_end_on_real_db(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate, SolCycle, SolGroup, SolMembership,
        SolPayment, SolPaymentProfile, SolPaymentProof,
    )

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True, poolclass=NullPool)
    schema = "sol_v1_invite_rotation_e2e"
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    all_models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolPaymentProfile, SolPaymentProof)

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in all_models:
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (organizer, alice, bob):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)
        # join_group can fire a fill/waitlist notify → app SessionLocal (remote pooler);
        # no-op it so this e2e stays local + fast.
        monkeypatch.setattr("app.services.sol_v1.notifications._emit_event_soft", lambda **kw: None)

        group = LC.create_group(
            db, organizer_id=organizer, name="Invite circle",
            contribution_amount=Decimal("25.00"), frequency="weekly", member_limit=5,
        )
        old_code = group.invite_code

        # a non-organizer can't reset the link
        with pytest.raises(SolError) as e:
            LC.rotate_invite_code(db, group_id=group.id, actor_id=alice)
        assert e.value.status_code == 403

        # alice joins on the ORIGINAL code (proving it works pre-rotation)
        LC.join_group(db, user_id=alice, invite_code=old_code)

        # organizer rotates → a fresh, different code
        rotated = LC.rotate_invite_code(db, group_id=group.id, actor_id=organizer)
        new_code = rotated.invite_code
        assert new_code != old_code

        # the OLD link no longer works
        with pytest.raises(SolError) as e2:
            LC.join_group(db, user_id=bob, invite_code=old_code)
        assert e2.value.status_code == 404
        # the NEW link does
        LC.join_group(db, user_id=bob, invite_code=new_code)

        # after lock, rotation is a clean 409 (the link is moot)
        from random import Random
        from datetime import date
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2026, 1, 1), rng=Random(1))
        with pytest.raises(SolError) as e3:
            LC.rotate_invite_code(db, group_id=group.id, actor_id=organizer)
        assert e3.value.status_code == 409

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
