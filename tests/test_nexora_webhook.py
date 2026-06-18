import pytest, time
from core import nexora_db, nexora_auth, nexora_entities as ent
from core import nexora_payments as pay

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _onboarded_creator(email="cr@x.com"):
    nexora_auth.register_creator(email, "hunter2", "Cr")
    ent.entity_create("CreatorProfile", {"display_name": "Cr"}, {"email": email, "role": "creator"})

def _event(t, amount_total=1000, **md):
    md["type"] = t
    return {"type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "amount_total": amount_total, "metadata": md}}}

def test_subscription_event_creates_records(db):
    _onboarded_creator()
    pay.handle_stripe_event(_event("subscription", fan_email="f@x.com", creator_email="cr@x.com"))
    subs = ent.entity_query("Subscription", {"fan_email": "f@x.com"}, None, None)
    txns = ent.entity_query("Transaction", {"to_email": "cr@x.com"}, None, None)
    notes = ent.entity_query("Notification", {"user_email": "cr@x.com"}, None, None)
    assert len(subs) == 1 and subs[0]["status"] == "active"
    assert len(txns) == 1 and abs(txns[0]["creator_amount"] - 9.0) < 0.01 and abs(txns[0]["platform_fee"] - 1.0) < 0.01
    assert len(notes) >= 1
    prof = ent.entity_query("CreatorProfile", {"user_email": "cr@x.com"}, None, 1)[0]
    assert prof["subscriber_count"] == 1 and prof["total_earnings"] > 0

def test_ppv_event_creates_purchase(db):
    _onboarded_creator()
    pay.handle_stripe_event(_event("ppv", fan_email="f@x.com", creator_email="cr@x.com", post_id="5"))
    cps = ent.entity_query("ContentPurchase", {"fan_email": "f@x.com"}, None, None)
    assert len(cps) == 1 and cps[0]["post_id"] == 5

def test_tip_event_creates_tip(db):
    _onboarded_creator()
    pay.handle_stripe_event(_event("tip", fan_email="f@x.com", creator_email="cr@x.com", message="yo"))
    tips = ent.entity_query("Tip", {"to_email": "cr@x.com"}, None, None)
    assert len(tips) == 1 and tips[0]["from_email"] == "f@x.com"

def test_non_checkout_event_ignored(db):
    out = pay.handle_stripe_event({"type": "payment_intent.created", "data": {"object": {}}})
    assert out.get("received") is True

import core.api as api
from fastapi.testclient import TestClient
from unittest.mock import patch

def test_webhook_requires_valid_signature(db):
    c = TestClient(api.app)
    with patch("stripe.Webhook.construct_event", side_effect=Exception("bad sig")):
        r = c.post("/api/nx/stripe-webhook", data=b"{}", headers={"Stripe-Signature": "bad"})
    assert r.status_code == 400

def test_webhook_processes_verified_event(db):
    _onboarded_creator("w@x.com")
    c = TestClient(api.app)
    ev = _event("tip", fan_email="ff@x.com", creator_email="w@x.com", message="m")
    with patch("stripe.Webhook.construct_event", return_value=ev):
        r = c.post("/api/nx/stripe-webhook", data=b"{}", headers={"Stripe-Signature": "ok"})
    assert r.status_code == 200 and r.json().get("received")
    assert len(ent.entity_query("Tip", {"to_email": "w@x.com"}, None, None)) == 1
