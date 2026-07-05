"""Stage 21 tests — Sol v1 dispute resolution (payee withdraw + organizer waive).

A disputed payment used to be a dead-end (only the payer re-marking could exit it),
so one unresolved dispute stranded its cycle and then the whole group forever. This
stage adds two exits: the payee can WITHDRAW a mistaken dispute (→ 'marked'), and the
organizer can WAIVE it (→ terminal 'waived', which counts as settled for completion
and is neutral for reputation). NON-CUSTODIAL: records only status + note/actor/time.

Layers:
  1. Pure (no DB): the two new state-machine edges, the reputation neutrality of
     'waived', and the notification content + fan-out (monkeypatched).
  2. DB-gated e2e (skipif no TEST_DATABASE_URL): withdraw, waive, cycle/group
     completion via waive, authz (403), 409 guards, and reputation exclusion.
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from random import Random
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.sol_v1 import ledger as LG
from app.services.sol_v1 import notifications as N
from app.services.sol_v1 import reputation as REP
from app.services.sol_v1.lifecycle import SolError

TODAY = date(2026, 6, 1)


# ── pure: the two new state-machine edges ─────────────────────────────────────


@pytest.mark.parametrize(
    "current,action,expected",
    [
        ("disputed", "withdraw", "marked"),  # payee retracts a mistaken dispute
        ("disputed", "waive", "waived"),     # organizer writes it off (terminal)
    ],
)
def test_resolution_transitions_allowed(current, action, expected):
    assert LG.next_status(current, action) == expected


@pytest.mark.parametrize("action", ["withdraw", "waive"])
@pytest.mark.parametrize("current", ["pending", "marked", "confirmed", "late", "waived"])
def test_resolution_actions_reject_non_disputed(current, action):
    # only a 'disputed' payment can be withdrawn or waived — everything else 409s
    with pytest.raises(SolError) as e:
        LG.next_status(current, action)
    assert e.value.status_code == 409


# ── pure: reputation neutrality of 'waived' ───────────────────────────────────


def test_classify_waived_is_neutral_even_when_ever_disputed():
    # a waived payment is ALWAYS 'waived' (excluded), even though it was disputed
    # (ever_disputed=True). The forgiveness must not re-penalize via the sticky
    # dispute signal.
    cat = REP.classify_payment(
        status="waived", due_date=date(2026, 1, 1), today=TODAY,
        marked_on=None, ever_disputed=True,
    )
    assert cat == "waived"


def test_score_excludes_waived_from_denominator():
    # one on-time + one waived → score reflects ONLY the on-time payment; the
    # waived one is neither credited nor counted (actionable == 1, not 2).
    r = REP.score_from_counts({"on_time": 1, "waived": 1})
    assert r["actionable"] == 1
    assert r["score"] == 100
    assert r["breakdown"]["waived"] == 1


def test_score_all_waived_is_unrated():
    # a member whose only obligation was waived has no actionable history
    r = REP.score_from_counts({"waived": 2})
    assert r["actionable"] == 0
    assert r["score"] is None and r["provisional"] is True


# ── pure: notification content + fan-out ──────────────────────────────────────


def test_content_payment_resolved_shapes():
    waived = N.content_payment_resolved(payment_id=uuid4(), amount=Decimal("30.00"), outcome="waived")
    assert waived["kind"] == "payment_resolved"
    assert "waived" in waived["body"].lower() and "$30.00" in waived["body"]
    withdrawn = N.content_payment_resolved(payment_id=uuid4(), amount=Decimal("30.00"), outcome="withdrawn")
    assert withdrawn["kind"] == "payment_resolved"
    assert "withdrawn" in withdrawn["body"].lower()


def _fake_payment(**over):
    base = dict(
        id=uuid4(), amount=Decimal("30.00"), payer_id=uuid4(), payee_id=uuid4(),
        resolved_at=None, payer_marked_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_notify_dispute_resolved_notifies_both_parties(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "_emit_event_soft", lambda **kw: calls.append(kw))
    p = _fake_payment()
    N.notify_dispute_resolved(p, outcome="waived")
    got = {c["user_id"] for c in calls}
    assert got == {p.payer_id, p.payee_id}                     # both parties
    assert all(c["content"]["kind"] == "payment_resolved" for c in calls)


def test_notify_dispute_resolved_dedup_discriminator(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "_emit_event_soft", lambda **kw: calls.append(kw))
    from datetime import datetime, timezone

    # waive keys the dedup on resolved_at (so a re-dispute→re-waive re-notifies)
    ra = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    N.notify_dispute_resolved(_fake_payment(resolved_at=ra), outcome="waived")
    assert all(ra.isoformat() in c["dedup_key"] and c["dedup_key"].startswith("payment_resolved:waived:") for c in calls)

    # withdraw keys on payer_marked_at (mirrors notify_payment_disputed)
    calls.clear()
    pm = datetime(2026, 5, 30, 9, 0, tzinfo=timezone.utc)
    N.notify_dispute_resolved(_fake_payment(payer_marked_at=pm), outcome="withdrawn")
    assert all(pm.isoformat() in c["dedup_key"] and c["dedup_key"].startswith("payment_resolved:withdrawn:") for c in calls)


def test_notify_payment_disputed_also_notifies_organizer(monkeypatch):
    # Fix C: a non-party organizer must be told about a dispute so they can reach
    # the waive action (their only in-app discovery path).
    calls = []
    monkeypatch.setattr(N, "_emit_event_soft", lambda **kw: calls.append(kw))
    org = uuid4()
    p = _fake_payment()
    N.notify_payment_disputed(p, organizer_id=org)
    users = {c["user_id"] for c in calls}
    assert p.payer_id in users and org in users            # payer AND organizer
    org_note = next(c for c in calls if c["user_id"] == org)
    assert org_note["content"]["kind"] == "payment_disputed"
    assert "organizer" in org_note["dedup_key"]            # distinct key namespace


def test_notify_payment_disputed_skips_organizer_when_party(monkeypatch):
    # no duplicate notification when the organizer is themselves the payer/payee
    calls = []
    monkeypatch.setattr(N, "_emit_event_soft", lambda **kw: calls.append(kw))
    p = _fake_payment()
    N.notify_payment_disputed(p, organizer_id=p.payer_id)
    assert len(calls) == 1 and calls[0]["user_id"] == p.payer_id


# ── DB end-to-end (gated on a reachable TEST_DATABASE_URL) ─────────────────────


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB dispute-resolution flow DEFERRED",
)
def test_dispute_resolution_end_to_end_on_real_db():
    """Withdraw, waive, completion-via-waive, authz, and reputation on real PG."""
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.models.sol import (
        SolCircleTemplate, SolCycle, SolGroup, SolMembership,
        SolPayment, SolPaymentProfile, SolPaymentProof,
    )
    from app.services.sol_v1 import lifecycle as LC

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_dispute_e2e"
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

        group = LC.create_group(
            db, organizer_id=organizer, name="Dispute circle",
            contribution_amount=Decimal("50.00"), frequency="weekly", member_limit=3,
        )
        LC.join_group(db, user_id=alice, invite_code=group.invite_code)
        LC.join_group(db, user_id=bob, invite_code=group.invite_code)
        LC.lock_group(db, group_id=group.id, actor_id=organizer,
                      order_mode="random", start_date=date(2026, 1, 1), rng=Random(7))

        _, _, cycles = LC.get_group_for_member(db, group_id=group.id, user_id=organizer)
        assert len(cycles) == 3

        # Materialize every cycle's payments.
        payments_by_cycle = {}
        for cyc in cycles:
            _, pays = LG.activate_cycle(db, cycle_id=cyc.id, actor_id=organizer)
            payments_by_cycle[cyc.id] = pays

        def find_payment(pred):
            for cid, pays in payments_by_cycle.items():
                for p in pays:
                    if pred(cid, p):
                        return cid, p
            return None, None

        c0 = cycles[0].id

        # ── 1. WITHDRAW: payee retracts a mistaken dispute ────────────────────
        _, wp = find_payment(lambda cid, p: cid == c0)
        LG.mark_paid(db, payment_id=wp.id, actor_id=wp.payer_id, method="zelle")
        LG.dispute(db, payment_id=wp.id, actor_id=wp.payee_id)
        assert db.get(SolPayment, wp.id).status == "disputed"
        # authz: only the payee may withdraw
        with pytest.raises(SolError) as e:
            LG.withdraw_dispute(db, payment_id=wp.id, actor_id=wp.payer_id)
        assert e.value.status_code == 403
        with pytest.raises(SolError):
            LG.withdraw_dispute(db, payment_id=wp.id, actor_id=uuid4())
        marked_before = db.get(SolPayment, wp.id).payer_marked_at
        LG.withdraw_dispute(db, payment_id=wp.id, actor_id=wp.payee_id)
        wp_after = db.get(SolPayment, wp.id)
        assert wp_after.status == "marked"                           # back to the decision point
        # the sticky dispute signal is preserved (anti-gaming)
        assert wp_after.disputed_at is not None
        # Fix B: the mark timestamp is refreshed so a re-dispute's notification
        # dedup key can't collide with the first dispute's and get swallowed
        assert wp_after.payer_marked_at is not None and wp_after.payer_marked_at != marked_before

        # ── 2. WAIVE + completion: organizer writes off a third-party dispute ──
        # A payment where the organizer is NEITHER party (canonical, non-self-deal),
        # in a DIFFERENT cycle from wp so completing it isn't blocked by wp.
        cid, tp = find_payment(
            lambda cid, p: cid != c0 and organizer not in (p.payer_id, p.payee_id)
        )
        assert tp is not None, "expected a third-party payment in a non-c0 cycle"
        # settle every OTHER payment in that cycle so only tp is outstanding
        for p in payments_by_cycle[cid]:
            if p.id == tp.id:
                continue
            LG.mark_paid(db, payment_id=p.id, actor_id=p.payer_id, method="cash")
            LG.confirm_received(db, payment_id=p.id, actor_id=p.payee_id)
        # drive tp to disputed
        LG.mark_paid(db, payment_id=tp.id, actor_id=tp.payer_id, method="venmo")
        LG.dispute(db, payment_id=tp.id, actor_id=tp.payee_id)
        assert db.get(SolCycle, cid).status == "active"             # still frozen by the dispute
        # authz: a non-organizer (the payee) cannot waive
        with pytest.raises(SolError) as e:
            LG.waive_dispute(db, payment_id=tp.id, actor_id=tp.payee_id)
        assert e.value.status_code == 403
        with pytest.raises(SolError):
            LG.waive_dispute(db, payment_id=tp.id, actor_id=uuid4())
        # organizer waives → terminal + audit + the cycle finally completes
        waived = LG.waive_dispute(db, payment_id=tp.id, actor_id=organizer, note="  settled offline  ")
        assert waived.status == "waived"
        assert waived.resolved_by == organizer and waived.resolved_at is not None
        assert waived.resolution_note == "settled offline"          # trimmed
        assert db.get(SolCycle, cid).status == "complete"           # unfrozen!

        # ── 3. 409 guards on live rows ────────────────────────────────────────
        with pytest.raises(SolError) as e:                          # re-waive a waived row
            LG.waive_dispute(db, payment_id=tp.id, actor_id=organizer)
        assert e.value.status_code == 409
        _, confirmed_p = find_payment(lambda cid, p: db.get(SolPayment, p.id).status == "confirmed")
        with pytest.raises(SolError) as e:                          # waive a confirmed row
            LG.waive_dispute(db, payment_id=confirmed_p.id, actor_id=organizer)
        assert e.value.status_code == 409
        with pytest.raises(SolError) as e:                          # withdraw a non-disputed row
            LG.withdraw_dispute(db, payment_id=confirmed_p.id, actor_id=confirmed_p.payee_id)
        assert e.value.status_code == 409

        # ── 4. reputation: the waived payment is NEUTRAL for its payer ─────────
        rep = REP.compute_reputation(db, user_id=tp.payer_id, today=TODAY, group_id=group.id)
        assert rep["breakdown"]["waived"] >= 1
        # the waived obligation is excluded from the actionable denominator
        n_waived = db.scalar(
            select(func.count(SolPayment.id))
            .join(SolCycle, SolPayment.cycle_id == SolCycle.id)
            .where(SolCycle.group_id == group.id,
                   SolPayment.payer_id == tp.payer_id,
                   SolPayment.status == "waived")
        )
        assert n_waived >= 1

        # ── 5. organizer view is scoped to disputed-or-self-resolved (Fix A) ──
        # organizer can still view the payment they just waived (resolved_by==them)
        _, _, _, org_id = LG.get_payment_detail(db, payment_id=tp.id, user_id=organizer)
        assert org_id == organizer
        # ...but NOT a non-disputed third-party payment (settled/pending privacy)
        _, other_tp = find_payment(
            lambda ci, p: organizer not in (p.payer_id, p.payee_id) and p.id != tp.id
        )
        assert other_tp is not None and db.get(SolPayment, other_tp.id).status != "disputed"
        with pytest.raises(SolError) as e:
            LG.get_payment_detail(db, payment_id=other_tp.id, user_id=organizer)
        assert e.value.status_code == 403
        # the actual parties still can read it
        LG.get_payment_detail(db, payment_id=other_tp.id, user_id=other_tp.payer_id)

        db.close()
        conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
