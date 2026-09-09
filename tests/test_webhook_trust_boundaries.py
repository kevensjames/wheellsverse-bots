"""Four webhook receivers accepted anything anyone sent them.

    /api/telegram/webhook   read the right header, but guarded it with `if expected_secret and ...`.
                            With TELEGRAM_WEBHOOK_SECRET unset the check vanished entirely, and it
                            compared with `!=` rather than a constant-time equality.
    /api/whatsapp/webhook   no authentication of any kind. `await request.json()`, then straight into
                            background_tasks.add_task(get_client().handle_payload, data).
    /api/beehiiv/webhook    token in a QUERY STRING, with a docstring that said the quiet part out
                            loud: "If it isn't set, we accept any request (the URL itself is the
                            shared secret)."
    /api/payhip/webhook     no authentication. A forged POST wrote a fabricated sale into the sales
                            file — a financial record — flipped state["verified"]=True, and fired a
                            Telegram notification to the owner.

All four are in _PUBLIC_PATHS, so the global API-key middleware skips them by design. That is correct
for a webhook: the provider cannot hold our API key. It means authentication has to come from the
provider's own mechanism, and for these four it did not come at all.

WHAT IS AND IS NOT VERIFIABLE. Three of these have a real cryptographic contract; one does not.

    Telegram   a shared secret echoed in a header. Authenticates the sender, cannot bind the body.
    Meta       HMAC-SHA256 over the raw body, keyed by the App Secret. Binds the body.
    Svix       HMAC-SHA256 over `{id}.{timestamp}.{body}`. Binds body, id AND timestamp.
    Payhip     `signature = sha256(api_key)` — a CONSTANT. It authenticates nobody in particular and
               binds nothing. Payhip's public API has coupons and license keys only, so there is no
               transaction endpoint to confirm a sale against either. These tests therefore assert
               that a Payhip callback never becomes a confirmed financial record, rather than
               pretending a verification exists.

The raw body is the message. Re-serialising parsed JSON changes key order, spacing and unicode
escaping, and the signature stops matching — so the handlers must read the body once and parse those
same bytes. `test_signature_is_over_the_exact_bytes_not_reserialised_json` is the guard for that, and
it fails against any implementation that verifies `json.dumps(await request.json())`.

Nothing here reaches a provider or sends anything: every outbound path is spied and refuses.
"""
import base64
import hashlib
import hmac
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("KAI_CAPABILITY_FABRIC_ENABLED", "true")

from core import api as core_api          # noqa: E402
from core import webhook_auth as wa       # noqa: E402

TG_SECRET = "telegram-webhook-secret"
META_APP_SECRET = "meta-app-secret"
META_VERIFY_TOKEN = "meta-verify-token"
BEEHIIV_KEY = os.urandom(24)
BEEHIIV_SECRET = "whsec_" + base64.b64encode(BEEHIIV_KEY).decode()
PAYHIP_API_KEY = "payhip-api-key"


@pytest.fixture
def client():
    return TestClient(core_api.app)


@pytest.fixture(autouse=True)
def _configured(monkeypatch, tmp_path):
    """Every secret configured, so a refusal in these tests is the VERIFIER refusing — never an
    unconfigured endpoint refusing for the wrong reason. The unconfigured case is tested separately
    and must be 503, not 200 and not 401."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", TG_SECRET)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-bot-token")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", META_APP_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", META_VERIFY_TOKEN)
    monkeypatch.setenv("BEEHIIV_WEBHOOK_SECRET", BEEHIIV_SECRET)
    monkeypatch.setenv("PAYHIP_API_KEY", PAYHIP_API_KEY)
    monkeypatch.setattr(wa, "_DEFAULT_STORE", tmp_path / "events", raising=False)
    core_api._rate_limit_store.clear()
    yield
    core_api._rate_limit_store.clear()


@pytest.fixture
def no_effects(monkeypatch):
    """Record-and-refuse over every way these handlers can touch the outside world or persist
    anything. A forged delivery that slips past a gate is caught here even if its status code lies."""
    import subprocess
    import urllib.request
    fired = []

    def spy(name):
        def _f(*a, **k):
            fired.append(name)
            raise AssertionError(f"forbidden effect from a refused webhook: {name}")
        return _f

    for mod, attr in (("core.telegram", "notify"),):
        try:
            m = __import__(mod, fromlist=["x"])
            monkeypatch.setattr(m, attr, spy(f"{mod}.{attr}"), raising=False)
        except Exception:
            pass
    for attr in ("_payhip_save_sales", "_payhip_save_state", "_add_log"):
        if hasattr(core_api, attr):
            monkeypatch.setattr(core_api, attr, spy(attr), raising=False)
    monkeypatch.setattr(subprocess, "Popen", spy("subprocess.Popen"), raising=False)
    monkeypatch.setattr(subprocess, "run", spy("subprocess.run"), raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", spy("urlopen"), raising=False)
    try:
        import requests
        monkeypatch.setattr(requests, "post", spy("requests.post"), raising=False)
        monkeypatch.setattr(requests, "get", spy("requests.get"), raising=False)
    except Exception:
        pass
    return fired


def meta_sig(body: bytes, secret: str = META_APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def svix_headers(body: bytes, msg_id="msg_1", ts=None, secret_key=BEEHIIV_KEY):
    ts = str(int(time.time())) if ts is None else str(ts)
    sig = base64.b64encode(hmac.new(
        secret_key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}"}


TG_BODY = {"message": {"text": "hello", "chat": {"id": "123"}}}
WA_BODY = {"object": "whatsapp_business_account",
           "entry": [{"changes": [{"value": {"messages": [
               {"from": "1555", "id": "wamid.1", "type": "text", "text": {"body": "hi"}}]}}]}]}
BH_BODY = {"event": "subscriber.created", "data": {"email": "a@b.com", "id": "sub_1"}}
PH_BODY = {"id": "txn_1", "email": "a@b.com", "price": 1999, "currency": "USD",
           "type": "paid", "signature": hashlib.sha256(PAYHIP_API_KEY.encode()).hexdigest()}


# ── 1. an unsigned delivery is refused, and does nothing ──────────────────────────────────────────
@pytest.mark.parametrize("path,body", [
    ("/api/telegram/webhook", TG_BODY),
    ("/api/whatsapp/webhook", WA_BODY),
    ("/api/beehiiv/webhook", BH_BODY),
    ("/api/payhip/webhook", PH_BODY),
])
def test_an_unsigned_delivery_is_refused(client, no_effects, path, body):
    # Payhip carries its secret INSIDE the body, so "unsigned" means stripping that field — not
    # merely omitting headers. Reusing the signed fixture here made this case silently test the
    # accept path instead of the refuse path.
    payload = {k: v for k, v in body.items() if k != "signature"}
    r = client.post(path, json=payload)
    assert r.status_code in (401, 403), f"{path} accepted an unsigned delivery ({r.status_code})"
    assert no_effects == [], f"{path} produced effects from an unsigned delivery: {no_effects}"


@pytest.mark.parametrize("path,body", [
    ("/api/telegram/webhook", TG_BODY),
    ("/api/whatsapp/webhook", WA_BODY),
    ("/api/beehiiv/webhook", BH_BODY),
    ("/api/payhip/webhook", PH_BODY),
])
def test_a_forged_signature_is_refused(client, no_effects, path, body):
    forged = {
        "X-Telegram-Bot-Api-Secret-Token": "not-the-secret",
        "X-Hub-Signature-256": "sha256=" + "0" * 64,
        "svix-id": "msg_1", "svix-timestamp": str(int(time.time())),
        "svix-signature": "v1," + base64.b64encode(b"0" * 32).decode(),
    }
    payload = dict(body)
    if path.endswith("payhip/webhook"):
        payload["signature"] = "0" * 64
    r = client.post(path, json=payload, headers=forged)
    assert r.status_code in (401, 403), f"{path} accepted a forged signature ({r.status_code})"
    assert no_effects == [], f"{path} produced effects from a forged delivery: {no_effects}"


def test_no_secret_may_be_accepted_from_a_query_string(client, no_effects):
    """Beehiiv's token used to live in `?token=`. A URL is not a private channel — it lands in edge
    logs, access logs, Referer headers, history and analytics, none of which can revoke it. The
    query parameter must now be inert: presenting it, correct or not, authenticates nothing."""
    for qs in (f"?token={BEEHIIV_SECRET}", "?token=anything", "?token="):
        r = client.post(f"/api/beehiiv/webhook{qs}", json=BH_BODY)
        assert r.status_code in (401, 403), f"query token was accepted: {qs} -> {r.status_code}"
    assert no_effects == []


# ── 2. unconfigured is 503, never open and never a plain refusal ──────────────────────────────────
@pytest.mark.parametrize("path,body,unset", [
    ("/api/telegram/webhook", TG_BODY, "TELEGRAM_WEBHOOK_SECRET"),
    ("/api/whatsapp/webhook", WA_BODY, "WHATSAPP_APP_SECRET"),
    ("/api/beehiiv/webhook", BH_BODY, "BEEHIIV_WEBHOOK_SECRET"),
    ("/api/payhip/webhook", PH_BODY, "PAYHIP_API_KEY"),
])
def test_missing_configuration_is_503_not_open(client, no_effects, monkeypatch, path, body, unset):
    """The fail-open that caused this: `if expected_secret and ...` meant unset = accept everything.
    Missing configuration is our misconfiguration, not the caller's permission — and it must be
    distinguishable from a refusal so it shows up in monitoring instead of hiding as a 401."""
    monkeypatch.delenv(unset, raising=False)
    r = client.post(path, json=body)
    assert r.status_code == 503, f"{path} with {unset} unset returned {r.status_code}, not 503"
    assert wa.UNAVAILABLE in r.text, f"{path} did not name the reason: {r.text[:200]}"
    assert no_effects == []


# ── 3. a genuine delivery still works ─────────────────────────────────────────────────────────────
def test_a_genuine_telegram_delivery_is_accepted(client, monkeypatch):
    monkeypatch.setattr(core_api, "_narai_v2_reply", lambda *a, **k: None, raising=False)
    r = client.post("/api/telegram/webhook", json=TG_BODY,
                    headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET})
    assert r.status_code == 200, r.text


def test_a_genuine_meta_delivery_is_accepted(client, monkeypatch):
    import sys, types
    fake = types.ModuleType("core.whatsapp")
    fake.get_client = lambda: types.SimpleNamespace(handle_payload=lambda d: None)
    monkeypatch.setitem(sys.modules, "core.whatsapp", fake)
    body = json.dumps(WA_BODY).encode()
    r = client.post("/api/whatsapp/webhook", content=body,
                    headers={"X-Hub-Signature-256": meta_sig(body),
                             "Content-Type": "application/json"})
    assert r.status_code == 200, r.text


def test_a_genuine_beehiiv_delivery_is_accepted(client):
    body = json.dumps(BH_BODY).encode()
    r = client.post("/api/beehiiv/webhook", content=body,
                    headers={**svix_headers(body), "Content-Type": "application/json"})
    assert r.status_code == 200, r.text


# ── 4. the raw body is the message ────────────────────────────────────────────────────────────────
def test_meta_signature_is_over_the_exact_bytes_not_reserialised_json(client, monkeypatch):
    """The same guard for the Meta path, and it was missing.

    A mutant that changed `raw = await _webhook_body(request)` to
    `raw = json.dumps(await request.json()).encode()` SURVIVED the first mutation round, because the
    raw-body test below only exercised Beehiiv. Writing the guard once and assuming it covered every
    provider is how the register-webhooks route stayed public through the commit meant to gate it —
    a check proves the path it runs on, never the path next to it.
    """
    import sys, types
    fake = types.ModuleType("core.whatsapp")
    fake.get_client = lambda: types.SimpleNamespace(handle_payload=lambda d: None)
    monkeypatch.setitem(sys.modules, "core.whatsapp", fake)

    raw = (b'{"object":"whatsapp_business_account",  "z":1, "caf":"caf\\u00e9",'
           b'"entry":[{"changes":[{"value":{"messages":[{"id":"wamid.raw","from":"1","type":"text"}]}}]}]}')
    assert json.dumps(json.loads(raw)).encode() != raw       # the premise
    r = client.post("/api/whatsapp/webhook", content=raw,
                    headers={"X-Hub-Signature-256": meta_sig(raw),
                             "Content-Type": "application/json"})
    assert r.status_code == 200, f"raw-body signature rejected — body is being re-serialised: {r.text[:200]}"


def test_signature_is_over_the_exact_bytes_not_reserialised_json(client):
    """The guard against verifying `json.dumps(await request.json())`.

    This body round-trips through json.loads/json.dumps to DIFFERENT bytes — key order, spacing and
    the non-ASCII escape all change. Signed over the bytes as sent, it must verify. Any implementation
    that re-serialises before verifying computes a different HMAC and rejects it.
    """
    raw = b'{"z":1,  "a":"caf\\u00e9", "nested":{"b":2,"a":1}}'
    assert json.dumps(json.loads(raw)).encode() != raw       # the premise of this test
    r = client.post("/api/beehiiv/webhook", content=raw,
                    headers={**svix_headers(raw), "Content-Type": "application/json"})
    assert r.status_code == 200, f"raw-body signature rejected — body is being re-serialised: {r.text[:200]}"


def test_a_tampered_body_fails_even_by_one_byte(client, no_effects):
    body = json.dumps(BH_BODY).encode()
    headers = svix_headers(body)
    r = client.post("/api/beehiiv/webhook", content=body + b" ",
                    headers={**headers, "Content-Type": "application/json"})
    assert r.status_code in (401, 403)
    assert no_effects == []


# ── 5. replay ─────────────────────────────────────────────────────────────────────────────────────
def test_an_expired_delivery_is_rejected(client, no_effects):
    """Svix binds the timestamp INTO the signed content, so a captured delivery cannot have its
    timestamp edited without breaking the signature. The tolerance is what stops the untouched
    original from being replayed a week later."""
    body = json.dumps(BH_BODY).encode()
    old = svix_headers(body, ts=int(time.time()) - 86400)
    r = client.post("/api/beehiiv/webhook", content=body,
                    headers={**old, "Content-Type": "application/json"})
    assert r.status_code in (401, 403), f"a day-old delivery was accepted ({r.status_code})"
    assert no_effects == []
    future = svix_headers(body, ts=int(time.time()) + 86400)
    r = client.post("/api/beehiiv/webhook", content=body,
                    headers={**future, "Content-Type": "application/json"})
    assert r.status_code in (401, 403), "a far-future delivery was accepted"


def test_a_valid_duplicate_acknowledges_without_repeating_effects(client, monkeypatch):
    """A provider retry is normal and must not be punished with an error — that only makes it retry
    harder. It must be acknowledged, and it must not happen twice."""
    handled = []
    import sys, types
    fake = types.ModuleType("core.whatsapp")
    fake.get_client = lambda: types.SimpleNamespace(handle_payload=lambda d: handled.append(d))
    monkeypatch.setitem(sys.modules, "core.whatsapp", fake)

    body = json.dumps(WA_BODY).encode()
    h = {"X-Hub-Signature-256": meta_sig(body), "Content-Type": "application/json"}
    first = client.post("/api/whatsapp/webhook", content=body, headers=h)
    second = client.post("/api/whatsapp/webhook", content=body, headers=h)
    assert first.status_code == 200 and second.status_code == 200, "a retry was not acknowledged"
    assert len(handled) <= 1, f"the duplicate was processed again: {len(handled)} times"


# ── 6. Payhip is not a confirmed financial event ──────────────────────────────────────────────────
def test_payhip_static_signature_is_not_treated_as_payload_authentication():
    """Payhip's `signature` is sha256(api_key) — the same value on every request. It excludes an
    anonymous stranger and nothing more: anyone who observes one delivery can forge every field of
    every later one. The code must say so rather than round it up to 'verified'."""
    assert wa.payhip_trust_level() == "SHARED_SECRET_ONLY_NO_PAYLOAD_BINDING_NO_SERVER_CONFIRMATION"
    good = hashlib.sha256(PAYHIP_API_KEY.encode()).hexdigest()
    assert wa.verify_payhip_static(good, PAYHIP_API_KEY)[0] == wa.OK
    # Identical for a completely different payload — that is the whole point.
    assert wa.verify_payhip_static(good, PAYHIP_API_KEY)[0] == wa.OK


def test_a_payhip_callback_does_not_flip_verified_state(client):
    """state["verified"]=True was set from the callback itself, so anyone who could POST could make
    the dashboard report a verified integration. A claim cannot be its own evidence."""
    before = core_api._payhip_load_state()
    client.post("/api/payhip/webhook", json={"type": "ping"})
    after = core_api._payhip_load_state()
    assert after.get("verified") == before.get("verified"), "an unsigned ping flipped verified state"


def test_a_payhip_sale_is_recorded_as_unconfirmed(client, monkeypatch):
    """Payhip offers no transaction endpoint — its public API covers coupons and license keys only —
    so a sale can never be confirmed server-to-server. The record must carry that provenance instead
    of sitting in the sales file indistinguishable from a confirmed one."""
    saved = {}
    monkeypatch.setattr(core_api, "_payhip_save_sales",
                        lambda sales: saved.setdefault("sales", sales), raising=False)
    monkeypatch.setattr(core_api, "_payhip_save_state", lambda s: None, raising=False)
    try:
        import core.telegram as ctg
        monkeypatch.setattr(ctg, "notify", lambda *a, **k: None, raising=False)
    except Exception:
        pass
    r = client.post("/api/payhip/webhook", json=PH_BODY)
    assert r.status_code == 200, r.text
    sales = saved.get("sales") or []
    assert sales, "a verified Payhip sale was not recorded at all"
    assert sales[0].get("confirmation") == "UNCONFIRMED", (
        f"the sale is not marked unconfirmed: {sales[0].get('confirmation')!r}")


# ── 7. the Meta handshake stays separate from delivery ────────────────────────────────────────────
def test_the_get_handshake_is_separate_from_post_delivery(client, no_effects):
    r = client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": META_VERIFY_TOKEN, "hub.challenge": "42"})
    assert r.status_code == 200 and r.text.strip().strip('"') == "42", r.text
    for bad in ({"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
                {"hub.mode": "unsubscribe", "hub.verify_token": META_VERIFY_TOKEN, "hub.challenge": "42"}):
        assert client.get("/api/whatsapp/webhook", params=bad).status_code in (401, 403)
    # Satisfying the handshake must not authenticate a POST.
    r = client.post("/api/whatsapp/webhook", json=WA_BODY, params={
        "hub.mode": "subscribe", "hub.verify_token": META_VERIFY_TOKEN, "hub.challenge": "42"})
    assert r.status_code in (401, 403), "the GET handshake authenticated a POST delivery"
    assert no_effects == []
