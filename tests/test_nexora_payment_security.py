"""Money-safety regression tests for the Nexora payment fixes.

Covers the invariants behind the four confirmed-critical audit findings that were
fixed in `fix/nexora-payment-security`:

  * /api/nx/subscribe must only ever create a *pending* subscriber (no free paid
    access, no earnings), so an anonymous caller can't unlock paid content.
  * Payout "available" balance must subtract prior payouts so a creator can't
    withdraw the same earnings repeatedly.
  * The Stripe webhook must be idempotent per Stripe event id.

These exercise the pure `core.nexora_db` SQLite layer against a temp DB, so they
run without the full FastAPI app (whose server deps aren't installable locally).
The webhook's signature-verification + fail-closed behaviour is enforced in
`core/api.py:nx_stripe_webhook` and covered by code review; here we verify the
idempotency ledger it depends on.
"""
import importlib
import time

import pytest

nx = importlib.import_module("core.nexora_db")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nx, "DB_PATH", tmp_path / "nexora_test.db")
    nx.init_db()
    # a creator to hang subscribers/payouts off of
    conn = nx.get_conn()
    conn.execute(
        "INSERT INTO nx_creators (email,name,handle,created_at) VALUES (?,?,?,?)",
        ("c@x.io", "Creator", "creator", time.time()),
    )
    conn.commit()
    cid = conn.execute("SELECT id FROM nx_creators WHERE handle='creator'").fetchone()["id"]
    conn.close()
    return cid


# ── /subscribe → pending only ────────────────────────────────────────────────

def test_pending_subscriber_is_not_active(db):
    nx.add_pending_subscriber(db, "fan@x.io", "Fan")
    subs = nx.list_subscribers(db)
    assert len(subs) == 1
    assert subs[0]["status"] == "pending"
    # the paywall counts only 'active' subscribers → no free access
    assert nx.get_active_subscriber_count(db) == 0


def test_pending_does_not_downgrade_a_paid_active_subscriber(db):
    # webhook path activated a real paying fan
    nx.add_subscriber(db, "fan@x.io", "Fan", 9.99, "cus_1")
    assert nx.get_active_subscriber_count(db) == 1
    # a later anonymous /subscribe intent must NOT flip them back to pending
    nx.add_pending_subscriber(db, "fan@x.io", "Fan")
    assert nx.get_active_subscriber_count(db) == 1
    assert nx.list_subscribers(db)[0]["status"] == "active"


# ── payout balance can't be double-spent ─────────────────────────────────────

def test_reserved_payout_excludes_only_rejected(db):
    nx.get_conn().close()
    conn = nx.get_conn()
    now = time.time()
    for amt, status in [(50, "requested"), (30, "completed"), (20, "rejected"), (10, "failed")]:
        conn.execute(
            "INSERT INTO nx_payouts (creator_id,amount,status,requested_at) VALUES (?,?,?,?)",
            (db, amt, status, now),
        )
    conn.commit()
    conn.close()
    # 50 requested + 30 completed reserve balance; rejected/failed release it
    assert nx.get_reserved_payout_amount(db) == 80.0


def test_available_balance_prevents_repeat_withdrawal(db):
    # creator earned $100 (creator_cut is 90% of a $111.11 charge ≈ $100)
    nx.record_transaction(db, 111.12, "subscription", "fan@x.io", "cs_1")
    earned = nx.get_earnings(db)["total"]
    assert earned == pytest.approx(100.0, abs=0.02)

    # first payout of the full balance
    nx.request_payout(db, earned, "bank")
    reserved = nx.get_reserved_payout_amount(db)
    available = round(earned - reserved, 2)
    # the exploit was: available still == earned → withdraw again. It must now be 0.
    assert available == 0.0


# ── webhook idempotency ledger ───────────────────────────────────────────────

def test_event_processed_ledger_is_idempotent(db):
    assert nx.event_already_processed("evt_1") is False
    assert nx.mark_event_processed("evt_1") is True     # first delivery wins
    assert nx.event_already_processed("evt_1") is True
    assert nx.mark_event_processed("evt_1") is False    # replay loses the race


def test_process_paid_event_activates_and_credits_once(db):
    # first delivery: activates the subscriber AND records earnings atomically
    assert nx.process_paid_event("evt_pay_1", db, "fan@x.io", "Fan", 100.0, "cs_1") == "processed"
    assert nx.get_active_subscriber_count(db) == 1
    assert nx.get_earnings(db)["total"] == pytest.approx(90.0, abs=0.01)  # 90% creator cut

    # replay of the SAME event id is a no-op — no double credit
    assert nx.process_paid_event("evt_pay_1", db, "fan@x.io", "Fan", 100.0, "cs_1") == "duplicate"
    assert nx.get_earnings(db)["total"] == pytest.approx(90.0, abs=0.01)
    assert nx.get_active_subscriber_count(db) == 1


def test_process_paid_event_requires_event_id(db):
    with pytest.raises(ValueError):
        nx.process_paid_event("", db, "fan@x.io", "Fan", 100.0, "cs_1")
