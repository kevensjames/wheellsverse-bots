# Nexora Phase 4 — New-Table Entities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Back the remaining 6 frontend entities — **Follow, Notification, ContentPurchase, FanProfile, LiveStream, Tip** — by adding new `nx_` tables + registry entries, reusing the Phase-3 entity machinery (`entity_query/get/create/update/delete` + `/api/nx/e/{entity}` routes). No new route code needed — the generic routes already serve any registered entity.

**Architecture:** Add 6 `CREATE TABLE IF NOT EXISTS` to `_SCHEMA`; add 6 entries to `ENTITIES`; add ONE machinery feature — `owner_from_body` — for `Notification` (created *for* a recipient, not the actor). Everything else flows through the existing generic ops.

**Tech Stack:** Python 3, SQLite, FastAPI, pytest.

**Repo:** `/Users/jhonwheeler/wt-nexora-phase1` (worktree), branch `nexora/phase4-entities` (stacked on `nexora/phase3-entities`). NEVER touch `/Users/jhonwheeler/wheellsverse_bots`.

**Spec:** design spec §4.3.

## ⚠️ Security decision baked into this plan
`Notification.create` sets `user_email` (the recipient) **from the request body**, because the app creates notifications for *other* users (e.g. a fan follows → notify the creator). The generic "stamp owner from token" rule can't apply. This is handled by an `owner_from_body` flag. **This means any authenticated user can create a notification addressed to anyone — a spam/phishing vector.** It is allowed here ONLY to preserve the drop-in client contract; it is flagged in the PR and **tracked to move notification creation server-side** (triggered by follow/subscribe/tip events) in a later hardening pass. Reads are already owner-scoped (Notification is non-public, `self_cols=["user_email"]`).

---

## Task 1: New tables

**Files:** Modify `core/nexora_db.py` (`_SCHEMA`); create `tests/test_nexora_phase4.py`.

- [ ] **Step 1: Write the failing test** (`tests/test_nexora_phase4.py`)

```python
import pytest
from core import nexora_db

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _cols(db, table):
    conn = db.get_conn()
    c = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    conn.close(); return c

def test_new_tables_exist(db):
    assert {"id","fan_email","creator_email","creator_profile_id","created_at"} <= _cols(db, "nx_follows")
    assert {"id","user_email","type","title","message","link","is_read","created_at"} <= _cols(db, "nx_notifications")
    assert {"id","fan_email","creator_email","creator_id","post_id","amount","created_at"} <= _cols(db, "nx_content_purchases")
    assert {"id","user_email","bio","preferences","blocked_creators","is_age_verified","created_at"} <= _cols(db, "nx_fan_profiles")
    assert {"id","creator_email","creator_profile_id","title","description","access_type","price","status","viewer_count","created_at"} <= _cols(db, "nx_livestreams")
    assert {"id","from_email","to_email","creator_id","amount","message","livestream_id","created_at"} <= _cols(db, "nx_tips")
```

- [ ] **Step 2: Run → FAIL** (`cd /Users/jhonwheeler/wt-nexora-phase1 && python3 -m pytest tests/test_nexora_phase4.py -v`).

- [ ] **Step 3: Append these tables to the `_SCHEMA` string in `core/nexora_db.py`** (before its closing `"""`):

```sql

CREATE TABLE IF NOT EXISTS nx_follows (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fan_email           TEXT    NOT NULL,
    creator_email       TEXT    DEFAULT '',
    creator_profile_id  INTEGER,
    created_at          REAL    NOT NULL,
    UNIQUE (fan_email, creator_email)
);

CREATE TABLE IF NOT EXISTS nx_notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email  TEXT    NOT NULL,
    type        TEXT    DEFAULT 'system',
    title       TEXT    DEFAULT '',
    message     TEXT    DEFAULT '',
    link        TEXT    DEFAULT '',
    is_read     INTEGER DEFAULT 0,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_content_purchases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fan_email       TEXT    NOT NULL,
    creator_email   TEXT    DEFAULT '',
    creator_id      INTEGER,
    post_id         INTEGER,
    amount          REAL    DEFAULT 0,
    created_at      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_fan_profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email          TEXT    UNIQUE NOT NULL,
    bio                 TEXT    DEFAULT '',
    preferences         TEXT    DEFAULT '[]',
    blocked_creators    TEXT    DEFAULT '[]',
    is_age_verified     INTEGER DEFAULT 0,
    created_at          REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_livestreams (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_email       TEXT    DEFAULT '',
    creator_profile_id  INTEGER,
    title               TEXT    DEFAULT '',
    description         TEXT    DEFAULT '',
    access_type         TEXT    DEFAULT 'subscribers_only',
    price               REAL    DEFAULT 0,
    status              TEXT    DEFAULT 'ended',
    viewer_count        INTEGER DEFAULT 0,
    created_at          REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_tips (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_email      TEXT    DEFAULT '',
    to_email        TEXT    DEFAULT '',
    creator_id      INTEGER,
    amount          REAL    DEFAULT 0,
    message         TEXT    DEFAULT '',
    livestream_id   INTEGER,
    created_at      REAL    NOT NULL
);
```

(These are plain `CREATE TABLE IF NOT EXISTS` appended to `_SCHEMA` — `init_db()` already runs `_SCHEMA`. No `_ensure_columns` needed for brand-new tables.)

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add core/nexora_db.py tests/test_nexora_phase4.py
git commit -m "feat(nexora): new tables — follows, notifications, content_purchases, fan_profiles, livestreams, tips"
```

---

## Task 2: Registry entries + `owner_from_body`

**Files:** Modify `core/nexora_entities.py`; append tests to `tests/test_nexora_phase4.py`.

- [ ] **Step 1: Append the failing test**

```python
from core import nexora_entities as ent
from core import nexora_auth

def _mk_creator(email, name="C"):
    nexora_auth.register_creator(email, "hunter2", name)

def test_follow_create_stamps_fan_owner(db):
    actor = {"email": "fan@x.com", "role": "fan"}
    fe = ent.entity_create("Follow", {"creator_email": "cr@x.com"}, actor)
    assert fe["fan_email"] == "fan@x.com" and fe["creator_email"] == "cr@x.com"

def test_notification_create_uses_body_recipient(db):
    actor = {"email": "actor@x.com", "role": "fan"}
    fe = ent.entity_create("Notification", {"user_email": "recipient@x.com", "type": "new_follower",
                                            "title": "New follower", "message": "hi"}, actor)
    assert fe["user_email"] == "recipient@x.com"   # owner from BODY, not actor
    assert fe["is_read"] is False

def test_notification_update_is_read(db):
    actor = {"email": "r@x.com", "role": "fan"}
    fe = ent.entity_create("Notification", {"user_email": "r@x.com", "title": "t"}, actor)
    upd = ent.entity_update("Notification", fe["id"], {"is_read": True}, actor)
    assert upd["is_read"] is True

def test_webhook_entities_reject_create(db):
    admin = {"email": "a@x.com", "role": "admin"}
    for ename in ("ContentPurchase", "Tip"):
        with pytest.raises(PermissionError):
            ent.entity_create(ename, {"amount": 5}, admin)

def test_livestream_resolves_creator_profile(db):
    _mk_creator("live@x.com")
    actor = {"email": "live@x.com", "role": "creator"}
    fe = ent.entity_create("LiveStream", {"title": "Stream", "access_type": "subscribers_only"}, actor)
    assert fe["creator_email"] == "live@x.com" and isinstance(fe["creator_profile_id"], int) and fe["creator_profile_id"] > 0
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3a: Add the 6 entity specs to `ENTITIES` in `core/nexora_entities.py`** (inside the `ENTITIES = {...}` dict):

```python
    "Follow": {
        "table": "nx_follows", "pk": "id", "owner_col": "fan_email",
        "fields": {
            "id": ("id", "int"), "fan_email": ("fan_email", "str"),
            "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "fan_email", "creator_email", "creator_profile_id"],
        "writable": ["creator_email", "creator_profile_id"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["fan_email", "creator_email"],
    },
    "Notification": {
        "table": "nx_notifications", "pk": "id", "owner_col": "user_email",
        "owner_from_body": True,
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "type": ("type", "str"), "title": ("title", "str"),
            "message": ("message", "str"), "link": ("link", "str"),
            "is_read": ("is_read", "bool"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email", "is_read", "type"],
        "writable": ["type", "title", "message", "link", "is_read"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["user_email"],
    },
    "ContentPurchase": {
        "table": "nx_content_purchases", "pk": "id", "owner_col": "fan_email",
        "fields": {
            "id": ("id", "int"), "fan_email": ("fan_email", "str"),
            "creator_email": ("creator_email", "str"), "creator_id": ("creator_id", "int"),
            "post_id": ("post_id", "int"), "amount": ("amount", "float"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "fan_email", "creator_email", "post_id"],
        "writable": [], "create_roles": [],
        "read_public": False, "self_cols": ["fan_email", "creator_email"],
    },
    "FanProfile": {
        "table": "nx_fan_profiles", "pk": "id", "owner_col": "user_email",
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "bio": ("bio", "str"), "preferences": ("preferences", "json"),
            "blocked_creators": ("blocked_creators", "json"),
            "is_age_verified": ("is_age_verified", "bool"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email"],
        "writable": ["bio", "preferences", "blocked_creators", "is_age_verified"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["user_email"],
    },
    "LiveStream": {
        "table": "nx_livestreams", "pk": "id", "owner_col": "creator_email",
        "create_link_creator": ["creator_profile_id"],
        "fields": {
            "id": ("id", "int"), "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "title": ("title", "str"), "description": ("description", "str"),
            "access_type": ("access_type", "str"), "price": ("price", "float"),
            "status": ("status", "str"), "viewer_count": ("viewer_count", "int"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "creator_email", "creator_profile_id", "status"],
        "writable": ["title", "description", "access_type", "price", "status"],
        "create_roles": ["creator", "admin"], "read_public": True,
    },
    "Tip": {
        "table": "nx_tips", "pk": "id", "owner_col": "to_email",
        "fields": {
            "id": ("id", "int"), "from_email": ("from_email", "str"),
            "to_email": ("to_email", "str"), "creator_id": ("creator_id", "int"),
            "amount": ("amount", "float"), "message": ("message", "str"),
            "livestream_id": ("livestream_id", "int"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "from_email", "to_email"],
        "writable": [], "create_roles": [],
        "read_public": False, "self_cols": ["from_email", "to_email"],
    },
```

- [ ] **Step 3b: Add `owner_from_body` handling to `entity_create`** in `core/nexora_entities.py`. Replace the single owner-stamp line:
```python
    cols[spec["owner_col"]] = actor["email"]            # stamp ownership from token
```
with:
```python
    if spec.get("owner_from_body"):
        # entity is created FOR a recipient (e.g. Notification) — owner comes from the body
        owner_fe = next(fe for fe, (c, _t) in spec["fields"].items() if c == spec["owner_col"])
        if owner_fe not in body:
            raise PermissionError("recipient required")
        cols[spec["owner_col"]] = body[owner_fe]
    else:
        cols[spec["owner_col"]] = actor["email"]        # stamp ownership from token
```
(Everything else in `entity_create` — role check, `create_link_creator`, ts default, INSERT — stays. `LiveStream`'s `create_link_creator: ["creator_profile_id"]` reuses the existing resolution; `nx_livestreams.creator_profile_id` is nullable so no FK issue.)

- [ ] **Step 4: Run → PASS** (`python3 -m pytest tests/test_nexora_phase4.py -v`). Also regression: `python3 -m pytest tests/test_nexora_entities.py -q`.

- [ ] **Step 5: Commit**

```bash
git add core/nexora_entities.py tests/test_nexora_phase4.py
git commit -m "feat(nexora): register Follow/Notification/ContentPurchase/FanProfile/LiveStream/Tip + owner_from_body"
```

---

## Task 3: Route integration tests

**Files:** Append to `tests/test_nexora_phase4.py` (uses `core.api` + TestClient).

- [ ] **Step 1: Append**

```python
import core.api as api
from fastapi.testclient import TestClient

def _h(tok): return {"Authorization": f"Bearer {tok}"}

def test_follow_create_delete_via_route(db):
    tok = nexora_auth.register_fan("f@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/e/Follow", headers=_h(tok), json={"creator_email": "cr@x.com"})
    assert r.status_code == 200 and r.json()["fan_email"] == "f@x.com"
    fid = r.json()["id"]
    # fan reads own follows (self-scoped)
    lst = c.get("/api/nx/e/Follow?fan_email=f@x.com", headers=_h(tok))
    assert lst.status_code == 200 and any(x["id"] == fid for x in lst.json())
    # delete own follow
    assert c.delete(f"/api/nx/e/Follow/{fid}", headers=_h(tok)).status_code == 200

def test_notification_route_and_read_scope(db):
    fan = nexora_auth.register_fan("n@x.com", "hunter2")["token"]
    other = nexora_auth.register_fan("o@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    # actor n creates a notification for recipient n (self)
    r = c.post("/api/nx/e/Notification", headers=_h(fan),
               json={"user_email": "n@x.com", "type": "system", "title": "hi"})
    assert r.status_code == 200
    nid = r.json()["id"]
    # recipient reads own (scoped)
    assert c.get("/api/nx/e/Notification?user_email=n@x.com", headers=_h(fan)).status_code == 200
    # other user CANNOT read n's notifications
    assert c.get("/api/nx/e/Notification?user_email=n@x.com", headers=_h(other)).status_code == 403
    # mark read
    up = c.patch(f"/api/nx/e/Notification/{nid}", headers=_h(fan), json={"is_read": True})
    assert up.status_code == 200 and up.json()["is_read"] is True

def test_livestream_create_via_route(db):
    tok = nexora_auth.register_creator("ls@x.com", "hunter2", "LS")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/e/LiveStream", headers=_h(tok), json={"title": "Live", "access_type": "subscribers_only"})
    assert r.status_code == 200 and r.json()["creator_email"] == "ls@x.com"
    # public read (any authed user can browse live streams)
    assert c.get("/api/nx/e/LiveStream?status=ended", headers=_h(tok)).status_code == 200

def test_content_purchase_create_blocked_via_route(db):
    tok = nexora_auth.register_fan("cp@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    # create_roles=[] -> 403
    assert c.post("/api/nx/e/ContentPurchase", headers=_h(tok), json={"amount": 5}).status_code == 403
```

- [ ] **Step 2: Run → PASS** (`python3 -m pytest tests/test_nexora_phase4.py -v`). Full regression:
`python3 -m pytest tests/test_nexora_phase4.py tests/test_nexora_entities.py tests/test_nexora_entity_routes.py tests/test_nexora_users.py tests/test_nexora_api.py tests/test_nexora_admin.py -q`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_nexora_phase4.py
git commit -m "test(nexora): route integration for Phase-4 entities (follow/notification/livestream/contentpurchase)"
```

---

## Phase 4 Done — Definition of Done
- [ ] Full suite green (Phase 1 + 3 + 4).
- [ ] All 6 new entities registered; Follow/FanProfile/LiveStream user-creatable (owner-stamped), Notification create-for-recipient works + read-scoped, ContentPurchase/Tip reject create (webhook-only).
- [ ] No regression.

## Tracked hardening (post-Phase-4)
- **Move Notification creation server-side** (triggered by follow/subscribe/tip events) to remove the client-side spam/phishing vector; then set `Notification.create_roles=[]`.

## Next Phase
Phase 5 — aggregation endpoints (`/api/nx/home-feed`, `/dashboard-data`, `/creators`, `/fan-data`, `/toggle-live`) replacing the old `nexoraData` multiplexer, all token-derived.
