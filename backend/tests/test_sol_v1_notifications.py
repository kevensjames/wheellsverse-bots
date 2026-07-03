"""Stage 8 tests — Sol v1 notifications (durable in-app inbox + member nudges).

Offline: pure content builders (bucket→kind, dedup keys, amount fmt), the
fail-soft external-channel guards, router wiring. DB-gated (TEST_DATABASE_URL):
emit idempotency (ON CONFLICT DO NOTHING), ownership-scoped reads/marks, and the
due/overdue scan actually creating one notification per payer per bucket.

NON-CUSTODIAL: notifications carry text + a deep-link only; nothing here moves
money. These tests assert no amounts settle — they only get *mentioned*.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from random import Random
from uuid import uuid4

import pytest

from app.services.sol_v1 import notifications as N

TODAY = date(2026, 7, 2)
PID = uuid4()


# ── pure: content builders ─────────────────────────────────────────────────────


def test_bucket_overdue_builds_overdue_kind():
    c = N.content_for_payer_obligation(
        payment_id=PID, amount=Decimal("100.00"), due_date=date(2026, 6, 1), bucket="overdue"
    )
    assert c["kind"] == "payment_overdue"
    assert c["dedup_key"] == f"payment_overdue:{PID}"
    assert c["payment_id"] == PID
    assert c["link"] == f"#/payment/{PID}"
    assert "$100.00" in c["body"] and "2026-06-01" in c["body"]


def test_bucket_due_today_and_upcoming_build_due_kind():
    today = N.content_for_payer_obligation(
        payment_id=PID, amount=Decimal("50"), due_date=TODAY, bucket="due_today"
    )
    upcoming = N.content_for_payer_obligation(
        payment_id=PID, amount=Decimal("50"), due_date=TODAY + timedelta(days=3), bucket="upcoming"
    )
    assert today["kind"] == "payment_due" and "today" in today["body"]
    assert upcoming["kind"] == "payment_due"
    # Distinct dedup keys per bucket so the due-today nudge is NOT swallowed by
    # the earlier "upcoming" one (they'd otherwise share payment_due:<pid>).
    assert upcoming["dedup_key"] == f"upcoming:{PID}"
    assert today["dedup_key"] == f"due_today:{PID}"
    assert upcoming["dedup_key"] != today["dedup_key"]


def test_scheduled_bucket_does_not_notify():
    assert N.content_for_payer_obligation(
        payment_id=PID, amount=Decimal("10"), due_date=TODAY + timedelta(days=90), bucket="scheduled"
    ) is None
    assert N.content_for_payer_obligation(
        payment_id=PID, amount=Decimal("10"), due_date=TODAY, bucket="nonsense"
    ) is None


def test_fmt_amount():
    assert N._fmt_amount(Decimal("100")) == "$100.00"
    assert N._fmt_amount("42.5") == "$42.50"
    assert N._fmt_amount("garbage").startswith("$")   # never raises


def test_ledger_event_builders():
    m = N.content_payment_marked(payment_id=PID, amount=Decimal("30"))
    assert m["kind"] == "payment_marked" and m["link"] == f"#/payment/{PID}" and "$30.00" in m["body"]
    c = N.content_payment_confirmed(payment_id=PID, amount=Decimal("30"))
    assert c["kind"] == "payment_confirmed" and c["payment_id"] == PID
    d = N.content_payment_disputed(payment_id=PID, amount=Decimal("30"))
    assert d["kind"] == "payment_disputed"
    cs = N.content_cycle_started(payment_id=PID, amount=Decimal("30"), due_date=date(2026, 7, 10))
    assert cs["kind"] == "cycle_started" and "2026-07-10" in cs["body"]
    po = N.content_payout_incoming(group_id=PID, cycle_number=2, amount=Decimal("30"))
    # payout_incoming links to the group (recipient has no payment row) + carries no payment_id
    assert po["kind"] == "payout_incoming" and po["link"] == f"#/group/{PID}" and "payment_id" not in po


# ── external channels: fail-soft + off by default ──────────────────────────────


def test_channels_off_by_default(monkeypatch):
    monkeypatch.delenv("SOL_NOTIFY_EMAIL_ENABLED", raising=False)
    monkeypatch.delenv("SOL_NOTIFY_SMS_ENABLED", raising=False)
    # settings are cached; assert the helper reads them as false-y regardless
    assert N._email_enabled() in (False, None) or N._email_enabled() is False


def test_deliver_external_never_raises():
    # even if a future provider throws, the caller must be shielded
    N._deliver_external(user_id=uuid4(), kind="payment_due", title="t", body="b")  # no raise


# ── router wiring ──────────────────────────────────────────────────────────────


def test_notifications_router_paths():
    from app.routers.sol_v1_notifications import router

    paths = {r.path for r in router.routes}
    assert paths == {
        "/sol/v1/notifications",
        "/sol/v1/notifications/unread-count",
        "/sol/v1/notifications/{notification_id}/read",
        "/sol/v1/notifications/read-all",
    }


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


def _db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCycle,
        SolGroup,
        SolMembership,
        SolNotification,
        SolPayment,
    )

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_notifications_e2e"
    models = (SolGroup, SolMembership, SolCycle, SolPayment, SolNotification)
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
    reason="TEST_DATABASE_URL not set — DB notifications flow DEFERRED",
)
def test_emit_is_idempotent_and_ownership_scoped():
    from sqlalchemy import text

    engine, conn, db, schema = _db()
    a, b = uuid4(), uuid4()
    try:
        _add_profiles(conn, a, b)

        first = N.emit(db, user_id=a, kind="payment_due", title="t", body="b",
                       dedup_key="payment_due:x")
        second = N.emit(db, user_id=a, kind="payment_due", title="t", body="b",
                        dedup_key="payment_due:x")
        assert first is not None
        assert second is None                      # ON CONFLICT DO NOTHING
        assert N.unread_count(db, user_id=a) == 1  # exactly one row

        # a DIFFERENT user with the same dedup_key is a distinct notification
        other = N.emit(db, user_id=b, kind="payment_due", title="t", body="b",
                       dedup_key="payment_due:x")
        assert other is not None
        assert N.unread_count(db, user_id=b) == 1

        # ownership: b cannot mark a's notification read
        assert N.mark_read(db, user_id=b, notification_id=first) is False
        assert N.unread_count(db, user_id=a) == 1
        # a can
        assert N.mark_read(db, user_id=a, notification_id=first) is True
        assert N.unread_count(db, user_id=a) == 0
        # idempotent second mark
        assert N.mark_read(db, user_id=a, notification_id=first) is False

        # distinct dedup_keys for the SAME user coexist (escalation: upcoming vs
        # due_today are different keys, so both nudges land — the confirmed fix)
        assert N.emit(db, user_id=a, kind="payment_due", title="t", body="b",
                      dedup_key="due_today:x") is not None
        assert N.unread_count(db, user_id=a) == 1  # the new due_today row

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB scan flow DEFERRED",
)
def test_scan_emits_one_overdue_per_payer_and_is_idempotent():
    from sqlalchemy import text

    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    engine, conn, db, schema = _db()
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    try:
        _add_profiles(conn, organizer, alice, bob)

        group = LC.create_group(
            db, organizer_id=organizer, name="Overdue circle",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2020, 1, 1), rng=Random(2))
        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        _, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        assert len(payments) == 2  # two payers owe the cycle-1 recipient

        created = N.emit_due_overdue_scan(db, TODAY)
        assert created == 2  # one overdue nudge per payer
        for p in payments:
            items = N.list_for_user(db, user_id=p.payer_id)
            assert len(items) == 1 and items[0].kind == "payment_overdue"
            assert items[0].payment_id == p.id

        # re-run: dedup means NO new rows
        assert N.emit_due_overdue_scan(db, TODAY) == 0
        total_unread = sum(N.unread_count(db, user_id=p.payer_id) for p in payments)
        assert total_unread == 2

        # mark_all_read clears one payer's inbox
        assert N.mark_all_read(db, user_id=payments[0].payer_id) == 1
        assert N.unread_count(db, user_id=payments[0].payer_id) == 0

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()


def test_notify_hooks_route_to_the_right_party(monkeypatch):
    # offline: the hooks emit in their OWN session, so capture the emit args by
    # patching _emit_event_soft and feed a plain object (no DB, no session).
    import types
    from datetime import datetime, timezone

    captured: list[dict] = []
    monkeypatch.setattr(N, "_emit_event_soft", lambda **kw: captured.append(kw))

    pid, payer, payee = uuid4(), uuid4(), uuid4()
    payment = types.SimpleNamespace(
        id=pid, payer_id=payer, payee_id=payee, amount=Decimal("30"),
        payer_marked_at=datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc),
    )
    N.notify_payment_marked(payment)     # → payee, dedup carries the mark time
    N.notify_payment_confirmed(payment)  # → payer
    N.notify_payment_disputed(payment)   # → payer

    marked = next(c for c in captured if c["content"]["kind"] == "payment_marked")
    assert marked["user_id"] == payee
    assert str(pid) in marked["dedup_key"] and "2026-07-03" in marked["dedup_key"]
    confirmed = next(c for c in captured if c["content"]["kind"] == "payment_confirmed")
    assert confirmed["user_id"] == payer and confirmed["dedup_key"] == f"payment_confirmed:{pid}"
    disputed = next(c for c in captured if c["content"]["kind"] == "payment_disputed")
    assert disputed["user_id"] == payer and disputed["dedup_key"] == f"payment_disputed:{pid}"


def test_notify_cycle_activated_fans_out(monkeypatch):
    import types

    captured: list[dict] = []
    monkeypatch.setattr(N, "_emit_event_soft", lambda **kw: captured.append(kw))

    gid, cid, recip = uuid4(), uuid4(), uuid4()
    p1 = types.SimpleNamespace(id=uuid4(), payer_id=uuid4())
    p2 = types.SimpleNamespace(id=uuid4(), payer_id=uuid4())
    cycle = types.SimpleNamespace(id=cid, group_id=gid, cycle_number=1, due_date=date(2026, 7, 10))
    N.notify_cycle_activated(cycle=cycle, payments=[p1, p2], recipient_user_id=recip, amount=Decimal("30"))

    kinds = [c["content"]["kind"] for c in captured]
    assert kinds.count("cycle_started") == 2 and kinds.count("payout_incoming") == 1
    assert {c["user_id"] for c in captured if c["content"]["kind"] == "cycle_started"} == {p1.payer_id, p2.payer_id}
    payout = next(c for c in captured if c["content"]["kind"] == "payout_incoming")
    assert payout["user_id"] == recip and payout["dedup_key"] == f"payout_incoming:{cid}"


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — ledger-transition wiring DEFERRED",
)
def test_ledger_transitions_invoke_notify_hooks(monkeypatch):
    from sqlalchemy import text

    from app.services.sol_v1 import ledger as LG
    from app.services.sol_v1 import lifecycle as LC

    # Patch the hooks to RECORD calls (no emit, no side session) so this proves
    # the wiring — ledger transition → correct hook with the right payment —
    # without any cross-session DB writes.
    calls: list = []
    monkeypatch.setattr(N, "notify_cycle_activated", lambda **kw: calls.append(("cycle", kw)))
    monkeypatch.setattr(N, "notify_payment_marked", lambda p: calls.append(("marked", p.id)))
    monkeypatch.setattr(N, "notify_payment_confirmed", lambda p: calls.append(("confirmed", p.id)))
    monkeypatch.setattr(N, "notify_payment_disputed", lambda p: calls.append(("disputed", p.id)))

    engine, conn, db, schema = _db()
    organizer, alice, bob = uuid4(), uuid4(), uuid4()
    try:
        _add_profiles(conn, organizer, alice, bob)
        group = LC.create_group(
            db, organizer_id=organizer, name="Notif circle",
            contribution_amount=Decimal("30.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2026, 7, 1), rng=Random(1))
        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        cycle, payments = LG.activate_cycle(db, cycle_id=cycles[0].id, actor_id=organizer)
        assert len(payments) == 2
        assert any(c[0] == "cycle" for c in calls)  # activation fired the fan-out

        p0, p1 = payments[0], payments[1]
        LG.mark_paid(db, payment_id=p0.id, actor_id=p0.payer_id, method="zelle")
        assert ("marked", p0.id) in calls
        LG.confirm_received(db, payment_id=p0.id, actor_id=p0.payee_id)
        assert ("confirmed", p0.id) in calls
        LG.mark_paid(db, payment_id=p1.id, actor_id=p1.payer_id, method="cash")
        LG.dispute(db, payment_id=p1.id, actor_id=p1.payee_id)
        assert ("disputed", p1.id) in calls

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
