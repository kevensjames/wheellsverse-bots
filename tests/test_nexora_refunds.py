"""Phase B Steps 4-6 — webhook dispatch seam + refund/dispute handling.

The lever: flip nx_transactions.status off 'succeeded' (full refund/dispute) or
reduce creator_amount/creator_cut in place (partial), then recalc_creator_stats
recomputes earnings/balance from source. recalc stays the single writer.
"""
import time
import pytest
from core import nexora_db, nexora_auth, nexora_entities as ent
from core import nexora_payments as pay

DAY = 86400


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db


def _onboarded_creator(email="cr@x.com"):
    nexora_auth.register_creator(email, "hunter2", "Cr")
    ent.entity_create("CreatorProfile", {"display_name": "Cr"}, {"email": email, "role": "creator"})


def _checkout(stripe_id, t, creator_email, fan_email="f@x.com", amount_total=1000,
              payment_intent="pi_1", **md):
    md.update({"type": t, "fan_email": fan_email, "creator_email": creator_email})
    return {"type": "checkout.session.completed",
            "data": {"object": {"id": stripe_id, "amount_total": amount_total,
                                "payment_intent": payment_intent, "metadata": md}}}


# ── Step 4: dispatch seam + correlation + ledger ─────────────────────────────────

def test_payment_intent_persisted_on_checkout(db):
    _onboarded_creator()
    pay.handle_stripe_event(_checkout("cs_1", "tip", "cr@x.com", payment_intent="pi_abc"))
    txns = ent.entity_query("Transaction", {"to_email": "cr@x.com"}, None, None)
    conn = nexora_db.get_conn()
    pi = conn.execute("SELECT payment_intent FROM nx_transactions WHERE stripe_id='cs_1'").fetchone()["payment_intent"]
    conn.close()
    assert pi == "pi_abc"


def test_non_refund_event_still_ignored(db):
    out = pay.handle_stripe_event({"type": "payment_intent.created", "data": {"object": {"id": "pi_1"}}})
    assert out.get("received") is True and out.get("ignored") == "payment_intent.created"


def test_event_seen_ledger_dedupes(db):
    conn = nexora_db.get_conn()
    assert pay._event_seen(conn, "evt_1") is False     # first time
    assert pay._event_seen(conn, "evt_1") is True       # already seen
    conn.close()


# ── Steps 5 & 6: refund + dispute ────────────────────────────────────────────────

def _cid(email):
    conn = nexora_db.get_conn()
    cid = conn.execute("SELECT id FROM nx_creators WHERE email=?", (email,)).fetchone()["id"]
    conn.close()
    return cid


def _refund_event(event_id, payment_intent, amount=1000, amount_refunded=1000, refunded=True):
    return {"id": event_id, "type": "charge.refunded",
            "data": {"object": {"id": "ch_x", "payment_intent": payment_intent,
                                "amount": amount, "amount_refunded": amount_refunded,
                                "refunded": refunded}}}


def _dispute_event(event_id, payment_intent, amount=1000):
    return {"id": event_id, "type": "charge.dispute.created",
            "data": {"object": {"id": "dp_x", "payment_intent": payment_intent, "amount": amount}}}


def _txn_status(stripe_id):
    conn = nexora_db.get_conn()
    row = conn.execute("SELECT status, creator_amount, refunded_amount FROM nx_transactions WHERE stripe_id=?",
                       (stripe_id,)).fetchone()
    conn.close()
    return row


def test_full_refund_flips_txn_and_drops_earnings(db):
    _onboarded_creator("fr@x.com")
    pay.handle_stripe_event(_checkout("cs_f", "subscription", "fr@x.com", payment_intent="pi_f"))
    pay.handle_stripe_event(_refund_event("evt_f", "pi_f"))
    prof = ent.entity_query("CreatorProfile", {"user_email": "fr@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"]) < 0.01 and abs(prof["available_balance"]) < 0.01
    assert _txn_status("cs_f")["status"] == "refunded"


def test_partial_refund_reduces_creator_amount(db):
    _onboarded_creator("pr@x.com")
    pay.handle_stripe_event(_checkout("cs_p", "tip", "pr@x.com", amount_total=1000, payment_intent="pi_p"))
    pay.handle_stripe_event(_refund_event("evt_p", "pi_p", amount=1000, amount_refunded=400, refunded=False))
    row = _txn_status("cs_p")
    assert row["status"] == "succeeded"                  # partial keeps it counting
    assert abs(row["creator_amount"] - 5.40) < 0.01      # net gross 6.0 * 90%
    assert abs(row["refunded_amount"] - 4.0) < 0.01
    prof = ent.entity_query("CreatorProfile", {"user_email": "pr@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"] - 5.40) < 0.01
    assert abs(nexora_db.get_available_balance(_cid("pr@x.com")) - 5.40) < 0.01   # payout gate agrees


def test_refund_revokes_subscription_access(db):
    _onboarded_creator("rs@x.com")
    pay.handle_stripe_event(_checkout("cs_s", "subscription", "rs@x.com", payment_intent="pi_s"))
    pay.handle_stripe_event(_refund_event("evt_s", "pi_s"))
    subs = ent.entity_query("Subscription", {"fan_email": "f@x.com"}, None, None)
    assert subs and subs[0]["status"] == "cancelled"


def test_refund_removes_ppv_purchase(db):
    _onboarded_creator("rp@x.com")
    pay.handle_stripe_event(_checkout("cs_v", "ppv", "rp@x.com", payment_intent="pi_v", post_id="5"))
    assert len(ent.entity_query("ContentPurchase", {"fan_email": "f@x.com"}, None, None)) == 1
    pay.handle_stripe_event(_refund_event("evt_v", "pi_v"))
    assert len(ent.entity_query("ContentPurchase", {"fan_email": "f@x.com"}, None, None)) == 0


def test_dispute_flips_to_disputed_and_revokes(db):
    _onboarded_creator("dp@x.com")
    pay.handle_stripe_event(_checkout("cs_d", "subscription", "dp@x.com", payment_intent="pi_d"))
    pay.handle_stripe_event(_dispute_event("evt_d", "pi_d"))
    assert _txn_status("cs_d")["status"] == "disputed"
    prof = ent.entity_query("CreatorProfile", {"user_email": "dp@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"]) < 0.01
    subs = ent.entity_query("Subscription", {"fan_email": "f@x.com"}, None, None)
    assert subs[0]["status"] == "cancelled"


def _dispute_closed_event(event_id, payment_intent, status):
    return {"id": event_id, "type": "charge.dispute.closed",
            "data": {"object": {"id": "dp_c", "payment_intent": payment_intent, "status": status}}}


def test_dispute_won_restores_earnings(db):
    _onboarded_creator("dw@x.com")
    pay.handle_stripe_event(_checkout("cs_dw", "subscription", "dw@x.com", payment_intent="pi_dw"))
    pay.handle_stripe_event(_dispute_event("evt_dw", "pi_dw"))            # disputed -> earnings 0
    assert _txn_status("cs_dw")["status"] == "disputed"
    pay.handle_stripe_event(_dispute_closed_event("evt_dw2", "pi_dw", "won"))
    assert _txn_status("cs_dw")["status"] == "succeeded"                  # restored
    prof = ent.entity_query("CreatorProfile", {"user_email": "dw@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"] - 9.0) < 0.01


def test_dispute_lost_keeps_earnings_debited(db):
    _onboarded_creator("dl@x.com")
    pay.handle_stripe_event(_checkout("cs_dl", "subscription", "dl@x.com", payment_intent="pi_dl"))
    pay.handle_stripe_event(_dispute_event("evt_dl", "pi_dl"))
    pay.handle_stripe_event(_dispute_closed_event("evt_dl2", "pi_dl", "lost"))
    assert _txn_status("cs_dl")["status"] == "disputed"                  # still debited
    prof = ent.entity_query("CreatorProfile", {"user_email": "dl@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"]) < 0.01


def test_dispute_won_restore_idempotent(db):
    _onboarded_creator("dwi@x.com")
    pay.handle_stripe_event(_checkout("cs_dwi", "tip", "dwi@x.com", payment_intent="pi_dwi"))
    pay.handle_stripe_event(_dispute_event("evt_dwi", "pi_dwi"))
    ev = _dispute_closed_event("evt_dwi2", "pi_dwi", "won")
    pay.handle_stripe_event(ev)
    out = pay.handle_stripe_event(ev)                                    # retry
    assert out.get("duplicate_event") == "evt_dwi2"
    prof = ent.entity_query("CreatorProfile", {"user_email": "dwi@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"] - 9.0) < 0.01                      # restored once, not 18


def test_refund_idempotent_on_retry(db):
    _onboarded_creator("ri@x.com")
    pay.handle_stripe_event(_checkout("cs_i", "tip", "ri@x.com", payment_intent="pi_i"))
    ev = _refund_event("evt_i", "pi_i")
    pay.handle_stripe_event(ev)
    out = pay.handle_stripe_event(ev)                    # same Stripe event id
    assert out.get("duplicate_event") == "evt_i"
    prof = ent.entity_query("CreatorProfile", {"user_email": "ri@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"]) < 0.01            # not double-reversed


def test_refund_unknown_payment_intent_acked(db):
    _onboarded_creator("ru@x.com")
    out = pay.handle_stripe_event(_refund_event("evt_u", "pi_nope"))
    assert out.get("no_matching_txn") == "pi_nope"


def test_ppv_refund_removes_exact_post(db):
    # Refund must revoke the EXACT purchased post, not just the most-recent one.
    _onboarded_creator("ppv2@x.com")
    pay.handle_stripe_event(_checkout("cs_10", "ppv", "ppv2@x.com", payment_intent="pi_10", post_id="10"))
    pay.handle_stripe_event(_checkout("cs_20", "ppv", "ppv2@x.com", payment_intent="pi_20", post_id="20"))
    assert len(ent.entity_query("ContentPurchase", {"fan_email": "f@x.com"}, None, None)) == 2
    pay.handle_stripe_event(_refund_event("evt_10", "pi_10"))     # refund post 10 only
    remaining = ent.entity_query("ContentPurchase", {"fan_email": "f@x.com"}, None, None)
    assert len(remaining) == 1 and remaining[0]["post_id"] == 20   # post 20 survives, post 10 gone


def test_cumulative_partial_refunds(db):
    # Two incremental partials on one charge: amount_refunded is CUMULATIVE in Stripe,
    # so the net must recompute from original gross — not subtract each delta twice.
    _onboarded_creator("cum@x.com")
    pay.handle_stripe_event(_checkout("cs_c", "tip", "cum@x.com", amount_total=1000, payment_intent="pi_c"))
    pay.handle_stripe_event(_refund_event("evt_a", "pi_c", amount=1000, amount_refunded=300, refunded=False))
    pay.handle_stripe_event(_refund_event("evt_b", "pi_c", amount=1000, amount_refunded=500, refunded=False))
    row = _txn_status("cs_c")
    assert row["status"] == "succeeded"
    assert abs(row["creator_amount"] - 4.50) < 0.01     # net gross 5.0 * 90%, NOT double-counted
    assert abs(row["refunded_amount"] - 5.00) < 0.01    # cumulative 5.0, not 8.0


def test_dispute_correlates_with_charge_and_payment_intent(db):
    # A realistic charge.dispute.created carries both `charge` (ch_) and `payment_intent`.
    _onboarded_creator("dr@x.com")
    pay.handle_stripe_event(_checkout("cs_dr", "subscription", "dr@x.com", payment_intent="pi_dr"))
    ev = {"id": "evt_dr", "type": "charge.dispute.created",
          "data": {"object": {"id": "dp_1", "charge": "ch_dr", "payment_intent": "pi_dr", "amount": 1000}}}
    pay.handle_stripe_event(ev)
    assert _txn_status("cs_dr")["status"] == "disputed"
    prof = ent.entity_query("CreatorProfile", {"user_email": "dr@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"]) < 0.01


def test_refund_exceeding_paid_balance_goes_negative(db):
    _onboarded_creator("rn@x.com")
    pay.handle_stripe_event(_checkout("cs_n", "tip", "rn@x.com", payment_intent="pi_n"))   # earns 9.0
    creator = {"email": "rn@x.com", "role": "creator"}
    prq = ent.entity_create("PayoutRequest", {"amount": 9.0, "payout_method": "paypal"}, creator)
    ent.entity_update("PayoutRequest", prq["id"], {"status": "paid"}, {"email": "adm@x.com", "role": "admin"})
    pay.handle_stripe_event(_refund_event("evt_n", "pi_n"))    # full refund: earn 0, paid 9
    prof = ent.entity_query("CreatorProfile", {"user_email": "rn@x.com"}, None, 1)[0]
    assert abs(prof["total_earnings"]) < 0.01
    assert abs(prof["available_balance"] - (-9.0)) < 0.01      # negative debt, NOT clamped to 0
