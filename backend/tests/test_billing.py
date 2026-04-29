"""Billing router tests. Stripe is mocked — we assert on how we call it
and how webhook events mutate our DB, not on Stripe's behavior."""
from __future__ import annotations

import hmac
import hashlib
import json
import time
from typing import Any

from app.config import settings
from app.models.subscription import Plan, Subscription
from app.models.user import User


# ---------- /subscription ----------

def test_subscription_free_by_default(client, free_user, auth_headers):
    r = client.get("/billing/subscription", headers=auth_headers(free_user))
    assert r.status_code == 200
    body = r.json()
    assert body["plan_code"] == "free"
    assert body["status"] == "free"
    assert body["predictions_per_day"] == 3


def test_subscription_active_sub(client, db_session, pro_user, auth_headers):
    r = client.get("/billing/subscription", headers=auth_headers(pro_user))
    assert r.status_code == 200
    body = r.json()
    assert body["plan_code"] == "pro"
    assert body["status"] == "active"


def test_subscription_requires_auth(client):
    assert client.get("/billing/subscription").status_code == 401


# ---------- /checkout ----------

def test_checkout_unauthenticated(client):
    r = client.post("/billing/checkout", json={"plan_code": "pro"})
    assert r.status_code == 401


def test_checkout_unknown_plan_returns_503(client, db_session, free_user, auth_headers, monkeypatch):
    # With STRIPE_PRICE_PRO empty we get 503 (plan not configured)
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO", "")
    r = client.post(
        "/billing/checkout",
        json={"plan_code": "pro"},
        headers=auth_headers(free_user),
    )
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


def test_checkout_happy_path(client, db_session, free_user, auth_headers, monkeypatch):
    """Full flow: no prior customer → we create one, persist customer_id,
    and return the checkout URL we received from Stripe."""
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO", "price_fake_pro")

    captured: dict[str, Any] = {}

    def fake_get_or_create(*, user_id, email, existing_customer_id):
        captured["customer_args"] = {
            "user_id": user_id,
            "email": email,
            "existing": existing_customer_id,
        }
        return "cus_fake_123"

    def fake_checkout(**kwargs):
        captured["checkout_args"] = kwargs
        return "https://checkout.stripe.com/c/pay/fake_session"

    from app.services import stripe_service as ss
    monkeypatch.setattr(ss, "get_or_create_customer", fake_get_or_create)
    monkeypatch.setattr(ss, "create_checkout_session", fake_checkout)

    r = client.post(
        "/billing/checkout",
        json={"plan_code": "pro"},
        headers=auth_headers(free_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_code"] == "pro"
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")

    # customer_id was persisted on the User row
    db_session.refresh(free_user)
    assert free_user.stripe_customer_id == "cus_fake_123"

    # And we passed the right price + metadata to Stripe
    assert captured["checkout_args"]["price_id"] == "price_fake_pro"
    assert captured["checkout_args"]["user_id"] == str(free_user.id)
    assert captured["checkout_args"]["plan_code"] == "pro"


# ---------- /webhook ----------

def _sign(payload: bytes, secret: str) -> str:
    """Forge a Stripe-Signature header. Mirrors stripe.WebhookSignature logic.
    Format: t=<unix_ts>,v1=<HMAC-SHA256(secret, "<ts>.<payload>")>
    """
    ts = int(time.time())
    signed_payload = f"{ts}.{payload.decode()}".encode()
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _webhook_payload(event_type: str, data_obj: dict) -> bytes:
    return json.dumps({
        "id": "evt_test",
        "type": event_type,
        "data": {"object": data_obj},
    }).encode()


def test_webhook_missing_signature_400(client):
    r = client.post("/billing/webhook", content=b"{}")
    assert r.status_code == 400


def test_webhook_invalid_signature_400(client, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    payload = _webhook_payload("ping", {})
    r = client.post(
        "/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": "t=123,v1=deadbeef"},
    )
    assert r.status_code == 400


def test_webhook_checkout_completed_activates_sub(
    client, db_session, free_user, monkeypatch
):
    secret = "whsec_test_abc"
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", secret)

    # Seed the plan Stripe will reference
    pro = db_session.query(Plan).filter(Plan.code == "pro").first()
    assert pro is not None

    data_obj = {
        "id": "cs_test_1",
        "customer": "cus_abc",
        "subscription": "sub_test_1",
        "metadata": {"user_id": str(free_user.id), "plan_code": "pro"},
    }
    payload = _webhook_payload("checkout.session.completed", data_obj)
    sig = _sign(payload, secret)

    r = client.post(
        "/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event_type"] == "checkout.session.completed"

    # Subscription row now exists and is active
    sub = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == free_user.id)
        .first()
    )
    assert sub is not None
    assert sub.status == "active"
    assert sub.stripe_subscription_id == "sub_test_1"
    assert sub.plan_id == pro.id

    # Customer ID was backfilled on the user
    db_session.refresh(free_user)
    assert free_user.stripe_customer_id == "cus_abc"


def test_webhook_subscription_deleted_cancels(
    client, db_session, pro_user, monkeypatch
):
    secret = "whsec_test_xyz"
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", secret)

    # Attach a stripe_subscription_id so the webhook can find it
    sub = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == pro_user.id)
        .first()
    )
    sub.stripe_subscription_id = "sub_delete_me"
    db_session.commit()

    payload = _webhook_payload(
        "customer.subscription.deleted",
        {"id": "sub_delete_me", "customer": "cus_any"},
    )
    sig = _sign(payload, secret)

    r = client.post(
        "/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200

    db_session.refresh(sub)
    assert sub.status == "canceled"


def test_webhook_unknown_event_returns_200(client, db_session, monkeypatch):
    """Stripe's retry loop punishes non-2xx. Unknown events must still 2xx."""
    secret = "whsec_test_unknown"
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", secret)

    payload = _webhook_payload("customer.created", {"id": "cus_new"})
    sig = _sign(payload, secret)
    r = client.post(
        "/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["received"] is True
