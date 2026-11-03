"""POST /api/stripe/webhook (core/api.py, core/board/stripe_webhook.py): every
delivery is verified with STRIPE_WEBHOOK_SECRET, each event id is claimed once,
so each side effect runs once per event, and the receiver writes no money (it
starts the Stripe sync). No network: Supabase is faked in tests/board_fakes.py
and every side effect is replaced by a recorder."""
import hashlib
import hmac
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from tests import board_fakes as bf

SECRET = "whsec_board_webhook_tests_0000000000"
PATH = "/api/stripe/webhook"


@pytest.fixture(autouse=True)
def _stripe_sdk(request):
    """The receiver checks signatures with the stripe package (requirements-server.txt)."""
    if "signing_secret" not in request.node.name:
        pytest.importorskip("stripe")


def sign(payload: bytes, secret: str = SECRET, at: int | None = None) -> str:
    """A Stripe-Signature header, computed the way Stripe documents it."""
    at = int(time.time()) if at is None else at
    mac = hmac.new(secret.encode(), f"{at}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={at},v1={mac}"


def checkout_event(event_id="evt_1", livemode=True, **meta):
    return {"id": event_id, "object": "event", "type": "checkout.session.completed", "livemode": livemode,
            "data": {"object": {
                "id": "cs_1", "object": "checkout.session", "amount_total": 2999, "currency": "usd",
                "customer_email": "buyer@example.com",
                "customer_details": {"email": "buyer@example.com", "name": "Bea Buyer"},
                "subscription": "sub_1", "customer": "cus_1", "payment_intent": "pi_1",
                "metadata": {"store_key": "blueprint_kit", "narai_plan": "pro", "partner": "coinbase",
                             "tg_pairing_token": "tg-token", "discord_pairing_token": "dc-token", **meta}}}}


def deleted_event(event_id="evt_del"):
    return {"id": event_id, "object": "event", "type": "customer.subscription.deleted", "livemode": True,
            "data": {"object": {"id": "sub_1", "object": "subscription"}}}


class Effects:
    """Records every side effect the receiver can run."""

    def __init__(self):
        self.calls = Counter()
        self.args = {}

    def record(self, name, result=None):
        def fn(*args, **kwargs):
            self.calls[name] += 1
            self.args[name] = (args, kwargs)
            return result
        return fn

    def record_async(self, name, result=True):
        async def fn(*args, **kwargs):
            self.calls[name] += 1
            self.args[name] = (args, kwargs)
            return result
        return fn


@pytest.fixture
def setup(monkeypatch, tmp_path):
    # the bridges create their SQLite files when first imported: keep them out of data/
    monkeypatch.setenv("TG_SUB_DB_PATH", str(tmp_path / "tg.db"))
    monkeypatch.setenv("DISCORD_SUB_DB_PATH", str(tmp_path / "discord.db"))
    import core.api as api
    import core.board.jobs as jobs
    from narai.integrations import discord_subscription as ds
    from narai.integrations import telegram_subscription as ts

    db = bf.install_board(monkeypatch)
    client = bf.client(monkeypatch)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("DISCORD_PAID_ROLE_ID", "role-1")
    monkeypatch.setattr(api, "_stripe_payments_file", tmp_path / "stripe_payments.json")
    fx = Effects()
    member = {"telegram_user_id": 42, "channel_id": "-100", "discord_guild_id": "g1", "discord_user_id": "u1"}
    monkeypatch.setattr(ts, "handle_checkout_completed", fx.record("tg_checkout", "tg-token"))
    monkeypatch.setattr(ts, "handle_subscription_updated", fx.record("tg_updated"))
    monkeypatch.setattr(ts, "revoke_for_subscription", fx.record("tg_revoke", member))
    monkeypatch.setattr(ts, "kick_telegram_user", fx.record_async("tg_kick"))
    monkeypatch.setattr(ds, "handle_checkout_completed", fx.record("dc_checkout", member))
    monkeypatch.setattr(ds, "handle_subscription_updated", fx.record("dc_updated"))
    monkeypatch.setattr(ds, "revoke_for_subscription", fx.record("dc_revoke", member))
    monkeypatch.setattr(ds, "grant_role", fx.record_async("dc_grant"))
    monkeypatch.setattr(ds, "revoke_role", fx.record_async("dc_revoke_role"))
    monkeypatch.setattr("core.click_tracker.record_conversion", fx.record("conversion", {"status": "recorded"}))
    monkeypatch.setattr("core.drip.enroll_in_drip", fx.record("drip", {"status": "skipped"}))
    monkeypatch.setattr("core.store_delivery.deliver", fx.record("delivery", {"status": "sent"}))

    class Profiles:            # core.narai_user.get_supabase().table("profiles").update(...).eq(...).execute()
        def table(self, name):
            fx.calls[f"table:{name}"] += 1
            return self

        def update(self, values):
            fx.args["tier"] = values
            return self

        def eq(self, column, value):
            fx.args["tier_where"] = (column, value)
            return self

        def execute(self):
            fx.calls["tier_upgrade"] += 1

    monkeypatch.setattr("core.narai_user.get_supabase", lambda: Profiles())
    monkeypatch.setattr(jobs, "sync_stripe", fx.record("stripe_sync"))
    return client, db, fx, api


def post(client, event, *, signature=None, secret=SECRET, raw=None):
    payload = raw if raw is not None else json.dumps(event).encode()
    headers = {"Content-Type": "application/json"}
    sig = sign(payload, secret) if signature is None else signature
    if sig:
        headers["Stripe-Signature"] = sig
    return client.post(PATH, content=payload, headers=headers)


ALL_CHECKOUT_EFFECTS = {"tg_checkout": 1, "dc_checkout": 1, "dc_grant": 1, "conversion": 1, "drip": 1,
                        "table:profiles": 1, "tier_upgrade": 1, "delivery": 1, "stripe_sync": 1}


def _payments(api):
    return json.loads(api._stripe_payments_file.read_text()) if api._stripe_payments_file.exists() else []


# ─── refused before anything runs ───────────────────────────────────────────

def test_without_the_signing_secret_every_post_is_refused_with_503(setup, monkeypatch, caplog):
    client, db, fx, api = setup
    from core.board import stripe_webhook
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    monkeypatch.setattr(stripe_webhook, "_no_secret_logged", None)
    caplog.set_level("ERROR", logger="board.stripe_webhook")
    for signature in (None, "", "t=1,v1=00"):
        r = post(client, checkout_event(), signature=signature)
        assert r.status_code == 503 and "signing secret" in r.json()["error"]
    unsigned = client.post(PATH, content=json.dumps(checkout_event()).encode())
    assert unsigned.status_code == 503
    assert db.calls == [] and not fx.calls and _payments(api) == []
    refusals = [r for r in caplog.records if r.name == "board.stripe_webhook" and "refused" in r.getMessage()]
    assert len(refusals) == 1 and refusals[0].levelname == "ERROR"      # said once, not once per event
    assert "STRIPE_WEBHOOK_SECRET is not set" in refusals[0].getMessage()


def test_a_missing_signing_secret_is_logged_at_startup(monkeypatch, caplog):
    import core.api as api
    from core.board import stripe_webhook
    assert stripe_webhook.check_secret in api._DEFERRED_STARTUP_HANDLERS
    caplog.set_level("ERROR", logger="board.stripe_webhook")

    def said():
        return [r for r in caplog.records if r.name == "board.stripe_webhook"]

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    stripe_webhook.check_secret()
    assert said() == []
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    stripe_webhook.check_secret()
    (record,) = said()
    assert record.levelname == "ERROR" and "STRIPE_WEBHOOK_SECRET is not set" in record.getMessage()


def test_a_bad_missing_or_stale_signature_is_refused_with_400(setup):
    client, db, fx, api = setup
    payload = json.dumps(checkout_event()).encode()
    for signature in ("", "garbage", sign(payload, "whsec_another_endpoint"),
                      sign(payload, at=int(time.time()) - 301),
                      sign(payload + b" ")):
        r = post(client, None, raw=payload, signature=signature)
        assert r.status_code == 400 and r.json()["error"] == "Invalid Stripe signature"
    assert SECRET not in r.text
    signed_junk = b"not json"
    assert post(client, None, raw=signed_junk).status_code == 400
    assert post(client, None, raw=b'{"object": "event"}').status_code == 400      # no id, no type
    assert db.calls == [] and not fx.calls and _payments(api) == []


# ─── once per event ─────────────────────────────────────────────────────────

def test_a_new_event_runs_every_side_effect_once_and_starts_the_sync(setup):
    client, db, fx, api = setup
    r = post(client, checkout_event())
    assert r.status_code == 200 and r.json() == {"received": True}
    assert dict(fx.calls) == ALL_CHECKOUT_EFFECTS
    assert fx.args["tier"] == {"tier": "pro"} and fx.args["tier_where"] == ("email", "buyer@example.com")
    assert fx.args["delivery"][1] == {"store_key": "blueprint_kit", "buyer_email": "buyer@example.com",
                                      "buyer_name": "Bea Buyer", "event_id": "evt_1", "amount_usd": 29.99}
    assert fx.args["conversion"][1]["external_id"] == "evt_1"
    assert fx.args["dc_grant"][0] == ("g1", "u1", "role-1")
    assert fx.args["stripe_sync"][1] == {"trigger": "webhook"}
    (payment,) = _payments(api)                                   # the payment log, kept for now
    assert payment["event_id"] == "evt_1" and payment["amount"] == 29.99
    row = db.webhook_events[("stripe", "evt_1")]
    assert (row["status"], row["attempts"], row["event_type"]) == ("processed", 1, "checkout.session.completed")
    assert row["processed_at"] is not None


def test_a_replayed_event_changes_nothing(setup):
    client, db, fx, api = setup
    assert post(client, checkout_event()).status_code == 200
    for _ in range(2):                                            # Stripe's retry, a replay from the dashboard
        r = post(client, checkout_event())
        assert r.status_code == 200 and r.json()["status"] == "done"
    assert dict(fx.calls) == ALL_CHECKOUT_EFFECTS                 # no second delivery, upgrade or bridge
    assert len(_payments(api)) == 1                               # no second payment row
    assert db.webhook_events[("stripe", "evt_1")]["attempts"] == 1


def test_the_same_event_arriving_mid_run_answers_409_and_runs_nothing(setup):
    client, db, fx, api = setup
    db._rpc_board_claim_webhook("stripe", "evt_1", "checkout.session.completed", True)   # running now
    r = post(client, checkout_event())
    assert r.status_code == 409
    assert not fx.calls and _payments(api) == []


def test_a_failed_or_abandoned_event_runs_again(setup):
    client, db, fx, api = setup
    db._rpc_board_claim_webhook("stripe", "evt_1", "checkout.session.completed", True)
    db.webhook_events[("stripe", "evt_1")].update(status="failed", error="side effects failed")
    assert post(client, checkout_event()).status_code == 200
    assert dict(fx.calls) == ALL_CHECKOUT_EFFECTS
    row = db.webhook_events[("stripe", "evt_1")]
    assert (row["status"], row["attempts"], row["error"]) == ("processed", 2, None)
    # one that died mid-run more than 10 minutes ago
    db._rpc_board_claim_webhook("stripe", "evt_2", "checkout.session.completed", True)
    db.clock = lambda: datetime.now(timezone.utc) + timedelta(minutes=11)
    assert post(client, checkout_event("evt_2")).status_code == 200
    assert fx.calls["delivery"] == 2 and db.webhook_events[("stripe", "evt_2")]["status"] == "processed"


def test_a_failing_receiver_answers_500_and_stripes_retry_runs_it_once(setup, monkeypatch):
    client, db, fx, api = setup

    def disk_full(record):
        raise OSError("No space left on device")

    real = api._save_stripe_payment
    monkeypatch.setattr(api, "_save_stripe_payment", disk_full)
    r = post(client, checkout_event())
    assert r.status_code == 500 and "No space" not in r.text
    row = db.webhook_events[("stripe", "evt_1")]
    assert row["status"] == "failed" and row["error"] == "side effects failed: OSError"
    assert fx.calls["delivery"] == 0
    monkeypatch.setattr(api, "_save_stripe_payment", real)
    assert post(client, checkout_event()).status_code == 200
    assert fx.calls["delivery"] == 1 and len(_payments(api)) == 1
    assert db.webhook_events[("stripe", "evt_1")]["status"] == "processed"


def test_one_failing_side_effect_does_not_stop_the_others(setup, monkeypatch):
    client, db, fx, api = setup

    def broken(**kwargs):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr("core.store_delivery.deliver", broken)
    assert post(client, checkout_event()).status_code == 200
    expected = {**ALL_CHECKOUT_EFFECTS}
    del expected["delivery"]
    assert dict(fx.calls) == expected
    assert db.webhook_events[("stripe", "evt_1")]["status"] == "processed"


def test_a_subscription_deletion_kicks_and_revokes_once(setup):
    client, db, fx, api = setup
    for _ in range(2):
        assert post(client, deleted_event()).status_code == 200
    assert fx.calls["tg_revoke"] == 1 and fx.calls["tg_kick"] == 1
    assert fx.calls["dc_revoke"] == 1 and fx.calls["dc_revoke_role"] == 1
    assert fx.args["tg_kick"][0] == ("-100", 42)
    assert fx.calls["delivery"] == 0 and fx.calls["conversion"] == 0


def test_a_test_mode_event_is_stored_as_ignored_and_runs_nothing(setup):
    client, db, fx, api = setup
    r = post(client, checkout_event(livemode=False))
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert not fx.calls and _payments(api) == []
    assert db.webhook_events[("stripe", "evt_1")]["status"] == "ignored"


def test_the_event_store_down_answers_503_and_runs_nothing(setup):
    client, db, fx, api = setup
    db.down = True
    assert post(client, checkout_event()).status_code == 503
    db.down = False
    db.fail["rpc/board_claim_webhook"] = 404                   # the migration was never applied
    assert post(client, checkout_event()).status_code == 503
    assert not fx.calls and _payments(api) == []


def test_the_receiver_writes_no_money(setup, monkeypatch):
    client, db, fx, api = setup
    stripe = bf.install_stripe(monkeypatch)
    stripe.add(*bf.fixture_day())
    assert post(client, checkout_event()).status_code == 200
    assert db.rpc_calls("board_ingest_ledger") == [] and db.ledger == {}
    assert stripe.calls == []                                  # the sync it started is a separate job
    assert fx.calls["stripe_sync"] == 1
    paths = {c.url.path for c in db.calls}
    assert paths == {"/rest/v1/rpc/board_claim_webhook", "/rest/v1/webhook_events"}


def test_the_webhook_needs_no_api_key(setup, monkeypatch):
    client, db, fx, api = setup
    import core.api as api_module
    monkeypatch.setattr(api_module, "_API_KEY", "a-key-the-webhook-never-sends")
    assert post(client, checkout_event("evt_key")).status_code == 200
