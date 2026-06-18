import pytest
from unittest.mock import patch, MagicMock
from core import nexora_db, nexora_auth
from core import nexora_payments as pay

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _mock_session(url="https://stripe.test/checkout/abc"):
    m = MagicMock(); m.url = url; return m

def test_subscription_checkout_builds_session(db):
    actor = {"email": "fan@x.com", "role": "fan"}
    with patch("stripe.checkout.Session.create", return_value=_mock_session()) as mk:
        out = pay.create_subscription_checkout(actor, {
            "creator_email": "cr@x.com", "creator_name": "Cr", "subscription_price": 9.99,
            "success_url": "s", "cancel_url": "c"})
    assert out["checkout_url"] == "https://stripe.test/checkout/abc"
    kwargs = mk.call_args.kwargs
    assert kwargs["mode"] == "payment"
    md = kwargs["metadata"]
    assert md["type"] == "subscription" and md["fan_email"] == "fan@x.com" and md["creator_email"] == "cr@x.com"
    assert kwargs["line_items"][0]["price_data"]["unit_amount"] == 999

def test_tip_checkout_min_and_metadata(db):
    actor = {"email": "f@x.com", "role": "fan"}
    with pytest.raises(ValueError):
        pay.create_tip_checkout(actor, {"amount": 0.5})
    with patch("stripe.checkout.Session.create", return_value=_mock_session()) as mk:
        pay.create_tip_checkout(actor, {"creator_email": "c@x.com", "amount": 5, "message": "hi", "livestream_id": 7})
    md = mk.call_args.kwargs["metadata"]
    assert md["type"] == "tip" and md["message"] == "hi" and md["livestream_id"] == "7"

def test_ppv_checkout_metadata(db):
    actor = {"email": "f@x.com", "role": "fan"}
    with patch("stripe.checkout.Session.create", return_value=_mock_session()) as mk:
        pay.create_ppv_checkout(actor, {"creator_email": "c@x.com", "post_id": 12, "amount": 4.99})
    md = mk.call_args.kwargs["metadata"]
    assert md["type"] == "ppv" and md["post_id"] == "12"
    assert mk.call_args.kwargs["line_items"][0]["price_data"]["unit_amount"] == 499

import core.api as api
from fastapi.testclient import TestClient

def test_checkout_routes(db):
    tok = nexora_auth.register_fan("rf@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    assert c.post("/api/nx/fn/createTipCheckout", json={"amount": 5}).status_code == 401
    with patch("stripe.checkout.Session.create", return_value=_mock_session()):
        r = c.post("/api/nx/fn/createTipCheckout",
                   headers={"Authorization": f"Bearer {tok}"},
                   json={"creator_email": "c@x.com", "amount": 5})
    assert r.status_code == 200 and r.json()["checkout_url"].startswith("https://stripe.test")
    with patch("stripe.checkout.Session.create", return_value=_mock_session()):
        bad = c.post("/api/nx/fn/createTipCheckout",
                     headers={"Authorization": f"Bearer {tok}"}, json={"amount": 0.1})
    assert bad.status_code == 400
