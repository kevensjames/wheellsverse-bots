# Nexora Phase 5 — Aggregation Endpoint (`nexoraData`) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Replace the Base44 `nexoraData` multiplexer with `POST /api/nx/fn/nexoraData`, dispatching on `body.action`, **deriving identity from the bearer token** (not the body — closes the IDOR), reusing the Phase-3/4 entity ops.

**Repo:** `/Users/jhonwheeler/wt-nexora-phase1`, branch `nexora/phase5-aggregation` (stacked on Phase 4). NEVER touch `/Users/jhonwheeler/wheellsverse_bots`.

## Exact contract (from the frontend consumers)
| action | body (besides `action`) | returns (the app reads `res.data.X`) |
|---|---|---|
| `home_feed` | user_email* | `{ok, creators, posts, follows, subscriptions, purchases}` |
| `dashboard_data` | user_email* | `{ok, profile, posts, transactions, subscriptions, payouts, notifications}` (or `{ok, profile:null}`) |
| `fan_data` | user_email* | `{ok, creators, follows, subscriptions}` |
| `toggle_live` | creator_id*, is_live | `{ok, profile}` |
| `create_post` | title, text, access_type, ppv_price, media_urls, media_type | `{ok, post}` |
| `delete_post` | post_id | `{ok}` |
| `request_payout` | amount, payout_method, notes | `{ok, payout}` |

\* body emails/ids are IGNORED for authz — identity comes from the token (`_nx_require_user`).

---

## Task 1: Aggregation module

**Files:** Create `core/nexora_aggregations.py`; create `tests/test_nexora_aggregations.py`.

- [ ] **Step 1: failing test** (`tests/test_nexora_aggregations.py`)

```python
import pytest
from core import nexora_db, nexora_auth, nexora_entities as ent
from core import nexora_aggregations as agg

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def test_dashboard_data_no_profile(db):
    nexora_auth.register_creator("c@x.com", "hunter2", "Cee")
    out = agg.dashboard_data({"email": "c@x.com", "role": "creator"})
    # register_creator does NOT make a CreatorProfile (nx_creators row != CreatorProfile entity row keyed by user_email)
    assert out["ok"] is True

def test_fan_data_shapes(db):
    nexora_auth.register_fan("f@x.com", "hunter2")
    actor = {"email": "f@x.com", "role": "fan"}
    ent.entity_create("Follow", {"creator_email": "cr@x.com"}, actor)
    out = agg.fan_data(actor)
    assert out["ok"] is True
    assert isinstance(out["creators"], list) and isinstance(out["follows"], list)
    assert any(f["creator_email"] == "cr@x.com" for f in out["follows"])

def test_home_feed_shapes(db):
    nexora_auth.register_fan("h@x.com", "hunter2")
    out = agg.home_feed({"email": "h@x.com", "role": "fan"})
    assert out["ok"] is True
    for k in ("creators", "posts", "follows", "subscriptions", "purchases"):
        assert isinstance(out[k], list)

def test_toggle_live_sets_profile(db):
    # create a CreatorProfile entity row for the creator (entity layer keyed by user_email)
    nexora_auth.register_creator("live@x.com", "hunter2", "L")
    actor = {"email": "live@x.com", "role": "creator"}
    ent.entity_create("CreatorProfile", {"display_name": "L"}, actor)
    out = agg.toggle_live(actor, True)
    assert out["ok"] is True and out["profile"]["is_live"] is True
    out2 = agg.toggle_live(actor, False)
    assert out2["profile"]["is_live"] is False
```

- [ ] **Step 2: run → FAIL**

- [ ] **Step 3: create `core/nexora_aggregations.py`**

```python
#!/usr/bin/env python3
"""core/nexora_aggregations.py — token-derived multi-entity feeds (replaces Base44 nexoraData)."""
from typing import Dict

from core.nexora_db import get_conn
from core.nexora_entities import entity_query, entity_get


def home_feed(actor: Dict) -> Dict:
    email = actor["email"]
    return {
        "ok": True,
        "creators": entity_query("CreatorProfile", {"status": "approved"}, None, 500),
        "posts": entity_query("Post", {"status": "published"}, "-created_date", 200),
        "follows": entity_query("Follow", {"fan_email": email}, None, None),
        "subscriptions": entity_query("Subscription", {"fan_email": email, "status": "active"}, None, None),
        "purchases": entity_query("ContentPurchase", {"fan_email": email}, None, None),
    }


def fan_data(actor: Dict) -> Dict:
    email = actor["email"]
    return {
        "ok": True,
        "creators": entity_query("CreatorProfile", {"status": "approved"}, None, 500),
        "follows": entity_query("Follow", {"fan_email": email}, None, None),
        "subscriptions": entity_query("Subscription", {"fan_email": email, "status": "active"}, None, None),
    }


def dashboard_data(actor: Dict) -> Dict:
    email = actor["email"]
    profiles = entity_query("CreatorProfile", {"user_email": email}, None, 1)
    if not profiles:
        return {"ok": True, "profile": None}
    return {
        "ok": True,
        "profile": profiles[0],
        "posts": entity_query("Post", {"creator_email": email}, "-created_date", None),
        "transactions": entity_query("Transaction", {"to_email": email}, "-created_date", None),
        "subscriptions": entity_query("Subscription", {"creator_email": email, "status": "active"}, None, None),
        "payouts": entity_query("PayoutRequest", {"creator_email": email}, "-created_date", None),
        "notifications": entity_query("Notification", {"user_email": email, "is_read": False}, None, None),
    }


def toggle_live(actor: Dict, is_live: bool) -> Dict:
    """Set the actor's OWN CreatorProfile.is_live (ignores any body creator_id — token-derived)."""
    profiles = entity_query("CreatorProfile", {"user_email": actor["email"]}, None, 1)
    if not profiles:
        return {"ok": False, "error": "No creator profile"}
    pid = profiles[0]["id"]
    conn = get_conn()
    conn.execute("UPDATE nx_creators SET is_live=? WHERE id=?", (1 if is_live else 0, pid))
    conn.commit()
    conn.close()
    return {"ok": True, "profile": entity_get("CreatorProfile", pid)}
```

- [ ] **Step 4: run → PASS** (`cd /Users/jhonwheeler/wt-nexora-phase1 && python3 -m pytest tests/test_nexora_aggregations.py -v`).

- [ ] **Step 5: commit**

```bash
git add core/nexora_aggregations.py tests/test_nexora_aggregations.py
git commit -m "feat(nexora): token-derived aggregation feeds (home_feed/dashboard_data/fan_data/toggle_live)"
```

---

## Task 2: `/api/nx/fn/nexoraData` route

**Files:** Modify `core/api.py`; append tests to `tests/test_nexora_aggregations.py`.

- [ ] **Step 1: append failing test**

```python
import core.api as api
from fastapi.testclient import TestClient

def _h(t): return {"Authorization": f"Bearer {t}"}

def test_nexora_data_route(db):
    tok = nexora_auth.register_creator("d@x.com", "hunter2", "D")["token"]
    ent.entity_create("CreatorProfile", {"display_name": "D"}, {"email": "d@x.com", "role": "creator"})
    c = TestClient(api.app)
    # auth required
    assert c.post("/api/nx/fn/nexoraData", json={"action": "fan_data"}).status_code == 401
    # create_post via the multiplexer
    r = c.post("/api/nx/fn/nexoraData", headers=_h(tok),
               json={"action": "create_post", "title": "P", "access_type": "free"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["post"]["creator_email"] == "d@x.com"
    pid = r.json()["post"]["id"]
    # dashboard_data returns the profile + the post (token-derived, body email ignored)
    dash = c.post("/api/nx/fn/nexoraData", headers=_h(tok),
                  json={"action": "dashboard_data", "user_email": "someone-else@x.com"})
    assert dash.status_code == 200 and dash.json()["profile"]["user_email"] == "d@x.com"
    assert any(p["id"] == pid for p in dash.json()["posts"])
    # delete_post
    dele = c.post("/api/nx/fn/nexoraData", headers=_h(tok), json={"action": "delete_post", "post_id": pid})
    assert dele.status_code == 200 and dele.json()["ok"]
    # toggle_live
    tl = c.post("/api/nx/fn/nexoraData", headers=_h(tok), json={"action": "toggle_live", "is_live": True})
    assert tl.status_code == 200 and tl.json()["profile"]["is_live"] is True
    # unknown action
    assert c.post("/api/nx/fn/nexoraData", headers=_h(tok), json={"action": "nope"}).status_code == 400

def test_request_payout_via_route(db):
    tok = nexora_auth.register_creator("p@x.com", "hunter2", "P")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/fn/nexoraData", headers=_h(tok),
               json={"action": "request_payout", "amount": 25, "payout_method": "paypal", "notes": "x"})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["payout"]["amount"] == 25
```

- [ ] **Step 2: run → FAIL**

- [ ] **Step 3: add the route to `core/api.py`.** After the `delete` entity route (grep `grep -n "nx_entity_delete" core/api.py`), insert at module level:

```python
@app.post("/api/nx/fn/nexoraData")
async def nx_fn_nexora_data(request: Request):
    user = _nx_require_user(request)
    body = await request.json()
    action = body.get("action")
    from core.nexora_aggregations import home_feed, dashboard_data, fan_data, toggle_live
    from core.nexora_entities import entity_create, entity_delete
    if action == "home_feed":
        return home_feed(user)
    if action == "dashboard_data":
        return dashboard_data(user)
    if action == "fan_data":
        return fan_data(user)
    if action == "toggle_live":
        return toggle_live(user, bool(body.get("is_live")))
    if action == "create_post":
        try:
            return {"ok": True, "post": entity_create("Post", body, user)}
        except PermissionError:
            raise HTTPException(status_code=403, detail="Not allowed")
    if action == "delete_post":
        try:
            entity_delete("Post", body.get("post_id"), user)
            return {"ok": True}
        except PermissionError:
            raise HTTPException(status_code=403, detail="Not allowed")
    if action == "request_payout":
        try:
            return {"ok": True, "payout": entity_create("PayoutRequest", body, user)}
        except PermissionError:
            raise HTTPException(status_code=403, detail="Not allowed")
    raise HTTPException(status_code=400, detail="Unknown action")
```

- [ ] **Step 4: run → PASS** (`python3 -m pytest tests/test_nexora_aggregations.py -v`). Regression: `python3 -m pytest tests/test_nexora_phase4.py tests/test_nexora_entity_routes.py tests/test_nexora_entities.py tests/test_nexora_users.py -q`.

- [ ] **Step 5: commit**

```bash
git add core/api.py tests/test_nexora_aggregations.py
git commit -m "feat(nexora): POST /api/nx/fn/nexoraData multiplexer (token-derived) replacing Base44 nexoraData"
```

---

## Phase 5 Done — DoD
- [ ] Full suite green. All 7 `nexoraData` actions work token-derived; body emails/ids ignored for identity (verified: `dashboard_data` with a foreign `user_email` still returns the token user's data).
- [ ] No regression.

## Next Phase
Phase 6 — payments: `POST /api/nx/fn/createSubscriptionCheckout|createTipCheckout|createPPVCheckout` (real Stripe sessions → `{checkout_url}`) + harden `/api/nx/stripe-webhook` (signature verify, branch on metadata.type, create records + notifications + counter bumps).
