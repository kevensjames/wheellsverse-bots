"""Stage 2 tests — Sol v1 group lifecycle.

Two layers:
  1. Pure-logic unit tests (no DB): the scheduling algorithm — interval math,
     payout-order assignment, calendar construction, invite codes. This is the
     real business logic and it is fully exercised offline.
  2. A DB-gated end-to-end test (skipif no TEST_DATABASE_URL): create → join →
     lock → detail against real Postgres, driving the service directly in an
     isolated schema so it never touches real data.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from uuid import UUID, uuid4

import pytest

from app.services.sol_v1 import lifecycle as L
from app.services.sol_v1.lifecycle import SolError

# ── interval math ─────────────────────────────────────────────────────────────


def test_add_interval_weekly_biweekly():
    base = date(2026, 1, 1)
    assert L.add_interval(base, "weekly", 1) == date(2026, 1, 8)
    assert L.add_interval(base, "weekly", 3) == date(2026, 1, 22)
    assert L.add_interval(base, "biweekly", 1) == date(2026, 1, 15)
    assert L.add_interval(base, "biweekly", 2) == date(2026, 1, 29)


def test_add_interval_monthly_rolls_year():
    assert L.add_interval(date(2026, 11, 15), "monthly", 3) == date(2027, 2, 15)


def test_add_months_clamps_short_month():
    # Jan 31 + 1 month → Feb 28 (2026 is not a leap year), not an invalid date.
    assert L._add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert L._add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap year


def test_add_interval_unknown_frequency():
    with pytest.raises(ValueError):
        L.add_interval(date(2026, 1, 1), "daily", 1)


# ── payout-order assignment ───────────────────────────────────────────────────


def _ids(n: int) -> list[UUID]:
    return [uuid4() for _ in range(n)]


def test_random_order_is_a_permutation():
    ids = _ids(5)
    pos = L.build_payout_positions(ids, "random", rng=Random(42))
    assert set(pos.keys()) == set(ids)
    assert sorted(pos.values()) == [1, 2, 3, 4, 5]


def test_random_order_deterministic_with_seed():
    ids = _ids(4)
    a = L.build_payout_positions(ids, "random", rng=Random(7))
    b = L.build_payout_positions(list(ids), "random", rng=Random(7))
    assert a == b


def test_organizer_assigned_accepts_valid_permutation():
    ids = _ids(3)
    assignment = {ids[0]: 2, ids[1]: 1, ids[2]: 3}
    assert L.build_payout_positions(ids, "organizer_assigned", assignment) == assignment


def test_organizer_assigned_rejects_non_permutation():
    ids = _ids(3)
    with pytest.raises(SolError):  # 1,2,2 is not a permutation of 1..3
        L.build_payout_positions(ids, "organizer_assigned", {ids[0]: 1, ids[1]: 2, ids[2]: 2})


def test_organizer_assigned_rejects_wrong_members():
    ids = _ids(3)
    stranger = uuid4()
    with pytest.raises(SolError):
        L.build_payout_positions(
            ids, "organizer_assigned", {ids[0]: 1, ids[1]: 2, stranger: 3}
        )


def test_positions_requires_two_members():
    with pytest.raises(SolError):
        L.build_payout_positions(_ids(1), "random")


def test_unknown_order_mode():
    with pytest.raises(SolError):
        L.build_payout_positions(_ids(2), "sideways")


# ── calendar construction ─────────────────────────────────────────────────────


def test_build_calendar_orders_and_dates():
    a, b, c = _ids(3)
    positions = {a: 2, b: 1, c: 3}  # b receives first, a second, c third
    cal = L.build_calendar(positions, date(2026, 1, 1), "weekly")
    assert [row[0] for row in cal] == [1, 2, 3]
    assert [row[1] for row in cal] == [b, a, c]  # recipient by position
    assert [row[2] for row in cal] == [date(2026, 1, 8), date(2026, 1, 15), date(2026, 1, 22)]


def test_build_calendar_covers_every_member_once():
    ids = _ids(6)
    positions = L.build_payout_positions(ids, "random", rng=Random(1))
    cal = L.build_calendar(positions, date(2026, 3, 1), "monthly")
    assert len(cal) == 6
    assert {row[1] for row in cal} == set(ids)  # each member is a recipient exactly once


# ── invite codes ──────────────────────────────────────────────────────────────


def test_invite_code_shape():
    code = L.generate_invite_code()
    assert len(code) == 8
    assert set(code) <= set(L._INVITE_ALPHABET)
    assert not (set("01OIL") & set(code))  # ambiguous chars excluded


def test_invite_codes_vary():
    codes = {L.generate_invite_code() for _ in range(200)}
    assert len(codes) > 190  # collisions vanishingly rare over a 30^8 space


# ── router wiring (no DB) ─────────────────────────────────────────────────────


def test_router_registers_expected_paths():
    from app.routers.sol_v1 import router

    paths = {r.path for r in router.routes}
    assert paths == {
        "/sol/v1/groups",
        "/sol/v1/groups/join",
        "/sol/v1/groups/{group_id}",
        "/sol/v1/groups/{group_id}/lock",
    }


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB lifecycle DEFERRED",
)
def test_full_lifecycle_on_real_db():
    """create → join → lock → detail, in an isolated schema on real Postgres."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import SolCircleTemplate, SolCycle, SolGroup, SolMembership

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_e2e_test"
    organizer, alice, bob = uuid4(), uuid4(), uuid4()

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in (SolCircleTemplate, SolGroup, SolMembership, SolCycle):
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
        for uid in (organizer, alice, bob):
            conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)

        group = L.create_group(
            db, organizer_id=organizer, name="Rent circle",
            contribution_amount=Decimal("100.00"), frequency="monthly", member_limit=3,
        )
        assert group.status == "open" and group.invite_code

        L.join_group(db, user_id=alice, invite_code=group.invite_code)
        L.join_group(db, user_id=bob, invite_code=group.invite_code)

        # non-organizer cannot lock
        with pytest.raises(SolError):
            L.lock_group(db, group_id=group.id, actor_id=alice)

        L.lock_group(db, group_id=group.id, actor_id=organizer,
                     order_mode="random", start_date=date(2026, 1, 1), rng=Random(3))

        g, members, cycles = L.get_group_for_member(db, group_id=group.id, user_id=bob)
        assert g.status == "locked" and g.locked_at is not None
        assert len(members) == 3
        assert {m.payout_position for m in members} == {1, 2, 3}
        assert len(cycles) == 3
        assert [c.cycle_number for c in cycles] == [1, 2, 3]
        assert all(c.recipient_membership_id is not None for c in cycles)

        # a stranger cannot read the group
        with pytest.raises(SolError):
            L.get_group_for_member(db, group_id=group.id, user_id=uuid4())

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
