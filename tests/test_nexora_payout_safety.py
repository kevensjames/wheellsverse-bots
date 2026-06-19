"""Regression tests for the Phase-A money-safety fixes.

These guard two bugs that were live before the fix:
  1. The legacy POST /api/nx/payouts route authorized against LIFETIME earnings,
     never subtracting paid or in-flight payouts → double-payout.
  2. available_balance had two writers (webhook += vs recalc =) that could
     diverge; recalc is now the single writer.
"""
import time
import pytest
from core import nexora_db, nexora_auth, nexora_entities as ent
from core import nexora_payments as pay
from core import nexora_ops as ops
import core.api as api
from fastapi.testclient import TestClient


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db


def _creator(email="pay@x.com"):
    nexora_auth.register_creator(email, "hunter2", "Cr")
    ent.entity_create("CreatorProfile", {"display_name": "Cr"}, {"email": email, "role": "creator"})
    conn = nexora_db.get_conn()
    cid = conn.execute("SELECT id FROM nx_creators WHERE email=?", (email,)).fetchone()["id"]
    conn.close()
    return cid


def _earn(cid, email, creator_amount):
    """Record one succeeded transaction crediting `creator_amount` to the creator."""
    conn = nexora_db.get_conn()
    conn.execute(
        "INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,"
        "to_email,creator_amount,platform_fee,status) VALUES (?,?,?,?,?,?,?,?,?)",
        (cid, creator_amount * 1.11, creator_amount * 0.11, creator_amount, time.time(),
         email, creator_amount, creator_amount * 0.11, "succeeded"))
    conn.commit(); conn.close()


# ── get_available_balance: the core of the double-payout fix ────────────────────

def test_available_balance_subtracts_paid_and_inflight(db):
    cid = _creator()
    _earn(cid, "pay@x.com", 100.0)
    assert nexora_db.get_available_balance(cid) == 100.0          # nothing withdrawn yet
    conn = nexora_db.get_conn()
    conn.execute("INSERT INTO nx_payouts (creator_id,amount,requested_at,status) VALUES (?,?,?,?)",
                 (cid, 60.0, time.time(), "paid"))                 # already disbursed
    conn.execute("INSERT INTO nx_payouts (creator_id,amount,requested_at,status) VALUES (?,?,?,?)",
                 (cid, 20.0, time.time(), "requested"))            # in-flight
    conn.commit(); conn.close()
    assert nexora_db.get_available_balance(cid) == 20.0            # 100 - 60 - 20


# ── the actual hole: the legacy REST route ──────────────────────────────────────

def test_legacy_payout_route_blocks_double_request(db):
    cid = _creator("dbl@x.com")
    _earn(cid, "dbl@x.com", 100.0)
    tok = nexora_auth.login_creator("dbl@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    h = {"Authorization": f"Bearer {tok}"}
    # First request for $80 succeeds.
    assert c.post("/api/nx/payouts", headers=h, json={"amount": 80}).status_code == 200
    # Second request for $80 must be REJECTED: only $20 remains (100 earned − 80 in-flight).
    # Before the fix this was allowed because it gated on lifetime earnings ($100).
    r2 = c.post("/api/nx/payouts", headers=h, json={"amount": 80})
    assert r2.status_code == 400 and "available" in r2.json()["detail"].lower()


# ── single-writer invariant: available_balance == earnings − paid ───────────────

def test_balance_invariant_after_income_and_payout(db):
    _onb = "inv@x.com"
    nexora_auth.register_creator(_onb, "hunter2", "Inv")
    ent.entity_create("CreatorProfile", {"display_name": "Inv"}, {"email": _onb, "role": "creator"})
    # $100 tip → creator keeps 90 (10% platform fee). Webhook now defers to recalc.
    pay.handle_stripe_event({"type": "checkout.session.completed",
        "data": {"object": {"id": "cs_a", "amount_total": 10000,
                            "metadata": {"type": "tip", "fan_email": "f@x.com", "creator_email": _onb}}}})
    prof = ent.entity_query("CreatorProfile", {"user_email": _onb}, None, 1)[0]
    assert abs(prof["available_balance"] - 90.0) < 0.01     # recalc wrote it, not the webhook

    # Admin marks a $50 payout paid → recalc reconciles.
    creator = {"email": _onb, "role": "creator"}
    prq = ent.entity_create("PayoutRequest", {"amount": 50, "payout_method": "paypal"}, creator)
    ent.entity_update("PayoutRequest", prq["id"], {"status": "paid"}, {"email": "adm@x.com", "role": "admin"})

    # A second $100 tip arrives.
    pay.handle_stripe_event({"type": "checkout.session.completed",
        "data": {"object": {"id": "cs_b", "amount_total": 10000,
                            "metadata": {"type": "tip", "fan_email": "g@x.com", "creator_email": _onb}}}})

    prof = ent.entity_query("CreatorProfile", {"user_email": _onb}, None, 1)[0]
    # Invariant: stored available_balance == total_earnings − paid_payouts, never inflated.
    assert abs(prof["total_earnings"] - 180.0) < 0.01       # 90 + 90
    assert abs(prof["available_balance"] - 130.0) < 0.01    # 180 − 50, single writer
