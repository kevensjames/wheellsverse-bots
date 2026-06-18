# Nexora Phase 6 — Payments Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Money code — review carefully.

**Goal:** Back the shim's 3 `functions.invoke` checkout calls with real Stripe Checkout Sessions (`POST /api/nx/fn/create{Subscription,Tip,PPV}Checkout` → `{checkout_url}`), and **harden `/api/nx/stripe-webhook`** with Stripe-Signature verification + branch-on-`metadata.type` record creation (Subscription/ContentPurchase/Tip + Transaction + Notification + creator counter bumps) + renewal/cancellation.

**Repo:** `/Users/jhonwheeler/wt-nexora-phase1`, branch `nexora/phase6-payments` (stacked on Phase 5). NEVER touch `/Users/jhonwheeler/wheellsverse_bots`.

**Env/libs:** `stripe` 11.1.0 installed; `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` env vars. The webhook route is already whitelisted from the API-key gate (public, as Stripe requires).

## Contracts (what the shim/app sends → expects)
| function | body | returns |
|---|---|---|
| `createSubscriptionCheckout` | creator_email, creator_profile_id, creator_name, subscription_price, success_url, cancel_url | `{checkout_url}` |
| `createTipCheckout` | creator_email, creator_name, amount, message?, livestream_id?, success_url, cancel_url | `{checkout_url}` |
| `createPPVCheckout` | creator_email, post_id, title/amount, success_url, cancel_url | `{checkout_url}` |

The buyer (`fan_email`) is taken from the **token**, not the body. Money split: **10% platform / 90% creator**.

## Testing approach (no real Stripe)
Mock `stripe.checkout.Session.create` (returns an object with `.url`) and `stripe.Webhook.construct_event` (returns the event dict). All tests run in-process with a temp DB.

---

## Task 1: Checkout module + routes

**Files:** Create `core/nexora_payments.py`; modify `core/api.py`; create `tests/test_nexora_payments.py`.

- [ ] **Step 1: failing test** (`tests/test_nexora_payments.py`)

```python
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
    assert kwargs["line_items"][0]["price_data"]["unit_amount"] == 999  # cents

def test_tip_checkout_min_and_metadata(db):
    actor = {"email": "f@x.com", "role": "fan"}
    with pytest.raises(ValueError):
        pay.create_tip_checkout(actor, {"amount": 0.5})           # below $1
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
```

- [ ] **Step 2: run → FAIL.**

- [ ] **Step 3: create `core/nexora_payments.py`**

```python
#!/usr/bin/env python3
"""core/nexora_payments.py — Stripe Checkout session creation + webhook record handling."""
import os
from typing import Dict


def _stripe():
    import stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    return stripe


def _checkout(name: str, amount_cents: int, success_url: str, cancel_url: str, metadata: Dict) -> Dict:
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {"currency": "usd", "product_data": {"name": name}, "unit_amount": amount_cents},
            "quantity": 1,
        }],
        success_url=success_url or "",
        cancel_url=cancel_url or "",
        metadata=metadata,
    )
    return {"checkout_url": session.url}


def create_subscription_checkout(actor: Dict, body: Dict) -> Dict:
    price = float(body.get("subscription_price") or 0)
    if price <= 0:
        raise ValueError("invalid subscription price")
    return _checkout(
        f"Subscription to {body.get('creator_name', 'creator')}",
        int(round(price * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "subscription", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "creator_profile_id": str(body.get("creator_profile_id", ""))},
    )


def create_tip_checkout(actor: Dict, body: Dict) -> Dict:
    amount = float(body.get("amount") or 0)
    if amount < 1:
        raise ValueError("tip minimum is $1")
    return _checkout(
        f"Tip to {body.get('creator_name', 'creator')}",
        int(round(amount * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "tip", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "message": (body.get("message") or "")[:200],
         "livestream_id": str(body.get("livestream_id") or "")},
    )


def create_ppv_checkout(actor: Dict, body: Dict) -> Dict:
    amount = float(body.get("amount") or body.get("ppv_price") or 0)
    if amount <= 0:
        raise ValueError("invalid PPV price")
    return _checkout(
        body.get("title") or body.get("post_title") or "Exclusive content",
        int(round(amount * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "ppv", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "post_id": str(body.get("post_id", ""))},
    )
```

- [ ] **Step 4: add routes to `core/api.py`** — after the `nx_fn_nexora_data` route (grep `grep -n "nx_fn_nexora_data" core/api.py`), insert module-level:

```python
@app.post("/api/nx/fn/createSubscriptionCheckout")
async def nx_fn_sub_checkout(request: Request):
    user = _nx_require_user(request)
    body = await request.json()
    from core.nexora_payments import create_subscription_checkout
    try:
        return create_subscription_checkout(user, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/nx/fn/createTipCheckout")
async def nx_fn_tip_checkout(request: Request):
    user = _nx_require_user(request)
    body = await request.json()
    from core.nexora_payments import create_tip_checkout
    try:
        return create_tip_checkout(user, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/nx/fn/createPPVCheckout")
async def nx_fn_ppv_checkout(request: Request):
    user = _nx_require_user(request)
    body = await request.json()
    from core.nexora_payments import create_ppv_checkout
    try:
        return create_ppv_checkout(user, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 5: append route test to `tests/test_nexora_payments.py`**

```python
import core.api as api
from fastapi.testclient import TestClient

def test_checkout_routes(db):
    tok = nexora_auth.register_fan("rf@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    assert c.post("/api/nx/fn/createTipCheckout", json={"amount": 5}).status_code == 401  # unauth
    with patch("stripe.checkout.Session.create", return_value=_mock_session()):
        r = c.post("/api/nx/fn/createTipCheckout",
                   headers={"Authorization": f"Bearer {tok}"},
                   json={"creator_email": "c@x.com", "amount": 5})
    assert r.status_code == 200 and r.json()["checkout_url"].startswith("https://stripe.test")
    # validation error -> 400
    with patch("stripe.checkout.Session.create", return_value=_mock_session()):
        bad = c.post("/api/nx/fn/createTipCheckout",
                     headers={"Authorization": f"Bearer {tok}"}, json={"amount": 0.1})
    assert bad.status_code == 400
```

- [ ] **Step 6: run → PASS** (`cd /Users/jhonwheeler/wt-nexora-phase1 && python3 -m pytest tests/test_nexora_payments.py -v`). Commit:

```bash
git add core/nexora_payments.py core/api.py tests/test_nexora_payments.py
git commit -m "feat(nexora): Stripe checkout sessions (subscription/tip/ppv) -> {checkout_url}"
```

---

## Task 2: Webhook record helpers

**Files:** Modify `core/nexora_payments.py`; create `tests/test_nexora_webhook.py`.

The webhook is server-authoritative: it inserts directly (the Subscription/ContentPurchase/Tip entities have `create_roles:[]`). Split: 10% platform / 90% creator.

- [ ] **Step 1: failing test** (`tests/test_nexora_webhook.py`)

```python
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

def _event(t, **md):
    md["type"] = t
    return {"type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "amount_total": 1000, "metadata": md}}}

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
```

- [ ] **Step 2: run → FAIL.**

- [ ] **Step 3: append to `core/nexora_payments.py`**

```python
import time as _time
from core.nexora_db import get_conn

PLATFORM_FEE_PCT = 10  # 10% platform / 90% creator


def _split(amount: float):
    platform = round(amount * PLATFORM_FEE_PCT / 100.0, 2)
    return platform, round(amount - platform, 2)


def _creator_row(conn, creator_email: str):
    return conn.execute("SELECT id FROM nx_creators WHERE email=? OR user_email=?",
                        (creator_email, creator_email)).fetchone()


def _notify(conn, user_email: str, ntype: str, title: str, message: str):
    conn.execute("INSERT INTO nx_notifications (user_email,type,title,message,is_read,created_at) "
                 "VALUES (?,?,?,?,0,?)", (user_email, ntype, title, message, _time.time()))


def handle_stripe_event(event: Dict) -> Dict:
    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    meta = obj.get("metadata", {}) or {}
    if etype != "checkout.session.completed":
        return {"received": True, "ignored": etype}
    t = meta.get("type")
    amount = (obj.get("amount_total", 0) or 0) / 100.0
    fan_email = meta.get("fan_email", "")
    creator_email = meta.get("creator_email", "")
    stripe_id = obj.get("id", "")
    platform, creator_amount = _split(amount)
    now = _time.time()
    conn = get_conn()
    crow = _creator_row(conn, creator_email)
    cid = crow["id"] if crow else None
    try:
        if t == "subscription":
            conn.execute(
                "INSERT INTO nx_subscribers (creator_id,fan_email,status,price_paid,started_at,"
                "creator_email,amount,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (cid or 0, fan_email, "active", amount, now, creator_email, amount, now + 30 * 86400))
            if cid:
                conn.execute("UPDATE nx_creators SET subscriber_count=subscriber_count+1, "
                             "total_earnings=total_earnings+?, available_balance=available_balance+? WHERE id=?",
                             (creator_amount, creator_amount, cid))
            _notify(conn, creator_email, "new_subscriber", "New subscriber!", f"{fan_email} subscribed")
        elif t == "ppv":
            conn.execute("INSERT INTO nx_content_purchases (fan_email,creator_email,creator_id,post_id,amount,created_at) "
                         "VALUES (?,?,?,?,?,?)",
                         (fan_email, creator_email, cid, int(meta.get("post_id") or 0), amount, now))
            if cid:
                conn.execute("UPDATE nx_creators SET total_earnings=total_earnings+?, available_balance=available_balance+? WHERE id=?",
                             (creator_amount, creator_amount, cid))
            _notify(conn, creator_email, "system", "Content unlocked", f"{fan_email} purchased your content")
        elif t == "tip":
            conn.execute("INSERT INTO nx_tips (from_email,to_email,creator_id,amount,message,livestream_id,created_at) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (fan_email, creator_email, cid, amount, meta.get("message", ""),
                          int(meta.get("livestream_id") or 0) or None, now))
            if cid:
                conn.execute("UPDATE nx_creators SET total_earnings=total_earnings+?, available_balance=available_balance+? WHERE id=?",
                             (creator_amount, creator_amount, cid))
            _notify(conn, creator_email, "system", "You got a tip!", f"{fan_email} tipped ${amount:.2f}")
        else:
            conn.close()
            return {"received": True, "ignored_type": t}
        conn.execute(
            "INSERT INTO nx_transactions (creator_id,fan_email,amount,platform_cut,creator_cut,type,stripe_id,"
            "status,created_at,from_email,to_email,creator_amount,platform_fee,description) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid or 0, fan_email, amount, platform, creator_amount, t, stripe_id, "succeeded", now,
             fan_email, creator_email, creator_amount, platform, f"{t} payment"))
        conn.commit()
    finally:
        conn.close()
    return {"received": True}
```

- [ ] **Step 4: run → PASS** (`python3 -m pytest tests/test_nexora_webhook.py -v`). Commit:

```bash
git add core/nexora_payments.py tests/test_nexora_webhook.py
git commit -m "feat(nexora): webhook record creation (subscription/ppv/tip + transaction + notification + counters, 10/90)"
```

---

## Task 3: Harden the webhook route (signature verification)

**Files:** Modify `core/api.py` (replace the body of `nx_stripe_webhook`); append to `tests/test_nexora_webhook.py`.

- [ ] **Step 1: append test**

```python
import core.api as api
from fastapi.testclient import TestClient
from unittest.mock import patch

def test_webhook_requires_valid_signature(db):
    c = TestClient(api.app)
    # construct_event raises on a bad signature -> 400
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
```

- [ ] **Step 2: run → FAIL** (current webhook ignores signature, uses old metadata).

- [ ] **Step 3: replace the body of `nx_stripe_webhook` in `core/api.py`** with:

```python
@app.post("/api/nx/stripe-webhook")
async def nx_stripe_webhook(request: Request):
    """Verify the Stripe signature, then create money records by metadata.type."""
    import stripe
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")
    from core.nexora_payments import handle_stripe_event
    return handle_stripe_event(event if isinstance(event, dict) else event.to_dict_recursive())
```

(Confirm `os` and `stripe` are importable at this scope — `os` is imported at module top; `stripe` is imported locally here. `construct_event` returns a `stripe.Event`; `.to_dict_recursive()` converts to a plain dict. In tests it's mocked to return a dict, so the `isinstance` guard handles both.)

- [ ] **Step 4: run → PASS.** Full regression: `python3 -m pytest tests/test_nexora_payments.py tests/test_nexora_webhook.py tests/test_nexora_aggregations.py tests/test_nexora_entities.py tests/test_nexora_users.py -q`. Commit:

```bash
git add core/api.py tests/test_nexora_webhook.py
git commit -m "feat(nexora): harden /api/nx/stripe-webhook with Stripe-Signature verification + typed dispatch"
```

---

## Phase 6 Done — DoD
- [ ] 3 checkout endpoints return `{checkout_url}` (mocked Stripe); fan_email from token; 10/90 split.
- [ ] Webhook verifies signature (bad sig → 400) and creates Subscription/ContentPurchase/Tip + Transaction + Notification + bumps counters per `metadata.type`.
- [ ] Full suite green.

## Tracked (post-Phase-6)
- Idempotency on the webhook (dedupe by `stripe_id`) to survive Stripe retries — add before production.
- `invoice.payment_succeeded` (renewal) + `customer.subscription.deleted` (cancel) — deferred (current checkouts are one-time `mode=payment`, not recurring Stripe subscriptions).

## Next Phase
Phase 7 — remaining 6 admin entities (Report, ModerationAction, AuditLog, CreatorVerification, PlatformSettings, Message) + admin-gated mutations.
