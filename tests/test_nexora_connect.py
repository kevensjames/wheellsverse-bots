"""Phase B Step 7 — Stripe Connect scaffolding (INERT until enabled).

Verifies the scaffolding is safe to ship before a live platform account exists:
columns present, stub endpoints 503 when disabled, disburse refuses without KYC,
and the payout.paid/failed webhooks reconcile via the single balance writer.
No live Stripe calls — the SDK is patched.
"""
import time
import pytest
from unittest.mock import patch
from core import nexora_db, nexora_auth, nexora_users, nexora_entities as ent
from core import nexora_payments as pay
from core import nexora_connect as connect
import core.api as api
from fastapi.testclient import TestClient


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db


def _creator(email="cr@x.com"):
    nexora_auth.register_creator(email, "hunter2", "Cr")
    ent.entity_create("CreatorProfile", {"display_name": "Cr"}, {"email": email, "role": "creator"})
    conn = nexora_db.get_conn()
    cid = conn.execute("SELECT id FROM nx_creators WHERE email=?", (email,)).fetchone()["id"]
    conn.close()
    return cid


def _earn(cid, email, creator_amount):
    conn = nexora_db.get_conn()
    conn.execute("INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,"
                 "to_email,creator_amount,platform_fee,status) VALUES (?,?,?,?,?,?,?,?,?)",
                 (cid, creator_amount * 1.11, creator_amount * 0.11, creator_amount, time.time(),
                  email, creator_amount, creator_amount * 0.11, "succeeded"))
    conn.commit(); conn.close()


def _seed_payout(cid, email, amount, status, transfer_id="tr_1"):
    conn = nexora_db.get_conn()
    conn.execute("INSERT INTO nx_payouts (creator_id,amount,requested_at,creator_email,status,stripe_transfer_id) "
                 "VALUES (?,?,?,?,?,?)", (cid, amount, time.time(), email, status, transfer_id))
    conn.commit(); conn.close()


def _balance(email):
    return ent.entity_query("CreatorProfile", {"user_email": email}, None, 1)[0]["available_balance"]


# ── schema + inert safety ────────────────────────────────────────────────────────

def test_connect_columns_exist_after_init(db):
    conn = nexora_db.get_conn()
    cre = {r["name"] for r in conn.execute("PRAGMA table_info(nx_creators)")}
    pay_cols = {r["name"] for r in conn.execute("PRAGMA table_info(nx_payouts)")}
    conn.close()
    assert {"stripe_account_id", "stripe_payouts_enabled", "stripe_onboarding_status"} <= cre
    assert {"stripe_transfer_id", "stripe_payout_id", "failure_reason"} <= pay_cols


def test_onboarding_link_returns_503_when_connect_disabled(db, monkeypatch):
    monkeypatch.delenv("STRIPE_CONNECT_ENABLED", raising=False)
    _creator("d@x.com")
    tok = nexora_auth.login_creator("d@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/connect/onboarding-link", headers={"Authorization": f"Bearer {tok}"}, json={})
    assert r.status_code == 503 and "not configured" in r.json()["detail"].lower()


def test_create_connected_account_persists_acct_id_idempotent(db, monkeypatch):
    monkeypatch.setenv("STRIPE_CONNECT_ENABLED", "1")
    _creator("a@x.com")
    with patch("stripe.Account.create", return_value={"id": "acct_X"}) as mk:
        assert connect.create_or_get_connected_account("a@x.com") == "acct_X"
        assert connect.create_or_get_connected_account("a@x.com") == "acct_X"   # idempotent
    assert mk.call_count == 1                                                     # not created twice


def test_disburse_refuses_when_kyc_incomplete(db, monkeypatch):
    monkeypatch.setenv("STRIPE_CONNECT_ENABLED", "1")
    cid = _creator("k@x.com")
    _seed_payout(cid, "k@x.com", 50.0, "requested")
    pid = nexora_db.list_payouts(cid)[0]["id"]
    with patch("stripe.Transfer.create") as mk:
        with pytest.raises(connect.ConnectNotConfigured):
            connect.disburse_payout(pid)
    mk.assert_not_called()                                                        # never transfer to un-KYC'd acct


# ── webhook reconciliation (single balance writer) ───────────────────────────────

def test_account_updated_event_sets_payouts_enabled(db):
    cid = _creator("au@x.com")
    conn = nexora_db.get_conn()
    conn.execute("UPDATE nx_creators SET stripe_account_id='acct_Y' WHERE id=?", (cid,))
    conn.commit(); conn.close()
    pay.handle_stripe_event({"type": "account.updated",
                             "data": {"object": {"id": "acct_Y", "payouts_enabled": True,
                                                 "details_submitted": True}}})
    conn = nexora_db.get_conn()
    row = conn.execute("SELECT stripe_payouts_enabled, stripe_onboarding_status FROM nx_creators WHERE id=?",
                       (cid,)).fetchone()
    conn.close()
    assert row["stripe_payouts_enabled"] == 1 and row["stripe_onboarding_status"] == "complete"


def test_payout_paid_event_marks_paid_and_recalcs_balance(db):
    cid = _creator("pp@x.com")
    _earn(cid, "pp@x.com", 100.0)
    _seed_payout(cid, "pp@x.com", 60.0, "processing", transfer_id="tr_1")
    nexora_db.get_conn().close()
    from core.nexora_ops import recalc_creator_stats
    recalc_creator_stats("pp@x.com")                       # baseline: 100 earned, 0 paid -> 100
    pay.handle_stripe_event({"type": "payout.paid", "data": {"object": {"id": "tr_1"}}})
    assert abs(_balance("pp@x.com") - 40.0) < 0.01         # 100 - 60 paid, via single writer


def test_payout_failed_event_reverts_status_and_restores_balance(db):
    cid = _creator("pf@x.com")
    _earn(cid, "pf@x.com", 100.0)
    _seed_payout(cid, "pf@x.com", 60.0, "paid", transfer_id="tr_2")
    from core.nexora_ops import recalc_creator_stats
    recalc_creator_stats("pf@x.com")                       # 100 - 60 paid -> 40
    assert abs(_balance("pf@x.com") - 40.0) < 0.01
    pay.handle_stripe_event({"type": "payout.failed",
                             "data": {"object": {"id": "tr_2", "failure_message": "bank rejected"}}})
    assert abs(_balance("pf@x.com") - 100.0) < 0.01        # failed payout frees the balance


def test_connect_event_idempotent_on_retry(db):
    cid = _creator("ci@x.com")
    _earn(cid, "ci@x.com", 100.0)
    _seed_payout(cid, "ci@x.com", 60.0, "processing", transfer_id="tr_3")
    ev = {"type": "payout.paid", "data": {"object": {"id": "tr_3"}}}
    pay.handle_stripe_event(ev)
    pay.handle_stripe_event(ev)                            # retry
    assert abs(_balance("ci@x.com") - 40.0) < 0.01         # paid once, not 2x
    payouts = nexora_db.list_payouts(cid)
    assert sum(1 for p in payouts if p["status"] == "paid") == 1


def test_payout_failed_on_inflight_frees_balance(db):
    # payout.failed on a still-in-flight ('requested') payout must free the balance,
    # not leave it locked. recalc subtracts only 'paid'; the gate counts requested as
    # in-flight, so flipping to 'failed' removes it from both.
    cid = _creator("fi@x.com")
    _earn(cid, "fi@x.com", 100.0)
    _seed_payout(cid, "fi@x.com", 60.0, "requested", transfer_id="tr_fi")
    pay.handle_stripe_event({"type": "payout.failed",
                             "data": {"object": {"id": "tr_fi", "failure_message": "bank rejected"}}})
    payouts = nexora_db.list_payouts(cid)
    assert payouts[0]["status"] == "failed" and payouts[0]["failure_reason"] == "bank rejected"
    assert nexora_db.get_available_balance(cid) == 100.0   # in-flight freed


def test_connect_status_403_for_suspended_creator(db):
    import time as _t
    _creator("susp@x.com")
    conn = nexora_db.get_conn()
    conn.execute("INSERT INTO nx_users (email,role,is_suspended,created_at) VALUES (?,?,?,?) "
                 "ON CONFLICT(email) DO UPDATE SET is_suspended=1",
                 ("susp@x.com", "creator", 1, _t.time()))
    conn.commit(); conn.close()
    tok = nexora_auth.login_creator("susp@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    r = c.get("/api/nx/connect/status", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_payout_request_gate_unchanged_with_connect(db):
    # Phase A available-balance gate must still compose with Connect columns present.
    cid = _creator("g@x.com")
    _earn(cid, "g@x.com", 100.0)
    tok = nexora_auth.login_creator("g@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    h = {"Authorization": f"Bearer {tok}"}
    assert c.post("/api/nx/payouts", headers=h, json={"amount": 80}).status_code == 200
    assert c.post("/api/nx/payouts", headers=h, json={"amount": 80}).status_code == 400   # only $20 left
