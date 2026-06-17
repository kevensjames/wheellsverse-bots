# Nexora Phase 3 — Entity REST Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Back the Phase-2 shim's `entities.<E>.{filter,list,create,update,delete}` calls with a generic `/api/nx/e/<Entity>` REST layer over the existing `nx_` tables, driven by a declarative entity registry that maps frontend field names ↔ stored columns and enforces token-derived ownership/role policy.

**Architecture:** ONE registry (`core/nexora_entities.py`) describes each entity (`table`, `pk`, FE↔column field map with type coercion, filterable keys, writable fields, role/ownership policy). Generic functions (`entity_query/get/create/update/delete`) build SQL from the registry and translate rows ↔ FE objects (incl. `created_at` epoch → `created_date` ISO and JSON columns). FastAPI routes `/api/nx/e/{entity}` (GET/POST/PATCH/DELETE) dispatch to them behind `_nx_require_user`. Adding an entity later (Phase 4) = one registry entry.

**Tech Stack:** Python 3, SQLite, FastAPI, pytest 8.3.3, bcrypt (existing).

**Repo:** `/Users/jhonwheeler/wt-nexora-phase1` (isolated worktree), branch `nexora/phase3-entities` (stacked on `nexora/phase1`). Run all commands there. NEVER touch `/Users/jhonwheeler/wheellsverse_bots` (concurrent writer + live daemon).

**Spec:** the design spec §4.1 (conventions), §4.2 (additive columns), §7.1 (entity REST).

**Scope (Phase 3):** existing-table entities only — **CreatorProfile, Post, Subscription, Transaction, PayoutRequest, User**. (Follow/Notification/etc. = Phase 4 new tables; Message deferred for its semantic mismatch.)

---

## Field-model reference (FE shape ← existing `nx_` columns + additive)
- **CreatorProfile** ← `nx_creators` (+add: `user_email, display_name, category, cover_url, social_links(JSON), status, verification_status, total_earnings, available_balance, subscriber_count, follower_count, is_live`). FE id=int.
- **Post** ← `nx_posts` (+add: `creator_email, creator_profile_id, text, access_type, ppv_price, media_type, status, like_count, comment_count`; existing `media_urls` JSON, `body`).
- **Subscription** ← `nx_subscribers` (+add: `creator_email, creator_profile_id, amount, expires_at`).
- **Transaction** ← `nx_transactions` (+add: `from_email, to_email, creator_amount, platform_fee, description`).
- **PayoutRequest** ← `nx_payouts` (+add: `creator_email, payout_method, admin_notes`; FE status vocab `pending|paid|rejected`).
- **User** ← `nx_users` (Phase 1; email PK). FE: `id`(=email), `email, full_name, role, is_suspended, created_date`.

Conventions: `created_date` = ISO-8601 string from `created_at` REAL epoch; JSON columns stored as TEXT, exposed parsed; booleans as JS bools.

---

## File Structure
| File | Responsibility |
|------|----------------|
| `core/nexora_db.py` (modify) | Additive columns via `_ensure_columns` in `init_db()`. |
| `core/nexora_entities.py` (create) | Registry + `_to_fe`/`_from_fe` + `entity_query/get/create/update/delete`. |
| `core/api.py` (modify) | `/api/nx/e/{entity}` GET/POST/PATCH/DELETE routes behind `_nx_require_user`. |
| `tests/test_nexora_entities.py` (create) | Unit tests for registry mapping + CRUD. |
| `tests/test_nexora_entity_routes.py` (create) | TestClient route + auth tests. |

---

## Task 1: Additive columns migration

**Files:** Modify `core/nexora_db.py`; create `tests/test_nexora_entities.py`.

- [ ] **Step 1: Write the failing test** (`tests/test_nexora_entities.py`)

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

def test_additive_columns_present(db):
    assert {"user_email","display_name","category","cover_url","social_links","status",
            "verification_status","total_earnings","available_balance","subscriber_count",
            "follower_count","is_live"} <= _cols(db, "nx_creators")
    assert {"creator_email","creator_profile_id","text","access_type","ppv_price",
            "media_type","status","like_count","comment_count"} <= _cols(db, "nx_posts")
    assert {"creator_email","creator_profile_id","amount","expires_at"} <= _cols(db, "nx_subscribers")
    assert {"from_email","to_email","creator_amount","platform_fee","description"} <= _cols(db, "nx_transactions")
    assert {"creator_email","payout_method","admin_notes"} <= _cols(db, "nx_payouts")
```

- [ ] **Step 2: Run → FAIL** (`cd /Users/jhonwheeler/wt-nexora-phase1 && python3 -m pytest tests/test_nexora_entities.py -v`): columns missing.

- [ ] **Step 3: Implement.** In `core/nexora_db.py` `init_db()`, AFTER it executes `_SCHEMA` (so tables exist) and on the same `conn`, before commit/close, add the additive migrations:

```python
    _ensure_columns(conn, "nx_creators", {
        "user_email": "user_email TEXT DEFAULT ''",
        "display_name": "display_name TEXT DEFAULT ''",
        "category": "category TEXT DEFAULT ''",
        "cover_url": "cover_url TEXT DEFAULT ''",
        "social_links": "social_links TEXT DEFAULT '{}'",
        "status": "status TEXT DEFAULT 'pending'",
        "verification_status": "verification_status TEXT DEFAULT 'unverified'",
        "total_earnings": "total_earnings REAL DEFAULT 0",
        "available_balance": "available_balance REAL DEFAULT 0",
        "subscriber_count": "subscriber_count INTEGER DEFAULT 0",
        "follower_count": "follower_count INTEGER DEFAULT 0",
        "is_live": "is_live INTEGER DEFAULT 0",
    })
    _ensure_columns(conn, "nx_posts", {
        "creator_email": "creator_email TEXT DEFAULT ''",
        "creator_profile_id": "creator_profile_id INTEGER",
        "text": "text TEXT DEFAULT ''",
        "access_type": "access_type TEXT DEFAULT 'free'",
        "ppv_price": "ppv_price REAL DEFAULT 0",
        "media_type": "media_type TEXT DEFAULT 'image'",
        "status": "status TEXT DEFAULT 'published'",
        "like_count": "like_count INTEGER DEFAULT 0",
        "comment_count": "comment_count INTEGER DEFAULT 0",
    })
    _ensure_columns(conn, "nx_subscribers", {
        "creator_email": "creator_email TEXT DEFAULT ''",
        "creator_profile_id": "creator_profile_id INTEGER",
        "amount": "amount REAL DEFAULT 0",
        "expires_at": "expires_at REAL",
    })
    _ensure_columns(conn, "nx_transactions", {
        "from_email": "from_email TEXT DEFAULT ''",
        "to_email": "to_email TEXT DEFAULT ''",
        "creator_amount": "creator_amount REAL DEFAULT 0",
        "platform_fee": "platform_fee REAL DEFAULT 0",
        "description": "description TEXT DEFAULT ''",
    })
    _ensure_columns(conn, "nx_payouts", {
        "creator_email": "creator_email TEXT DEFAULT ''",
        "payout_method": "payout_method TEXT DEFAULT 'bank'",
        "admin_notes": "admin_notes TEXT DEFAULT ''",
    })
```

(If `init_db()` currently does `conn = get_conn(); conn.executescript(_SCHEMA); conn.commit(); conn.close()`, insert these `_ensure_columns(...)` calls between `executescript` and `commit`, reusing the same `conn`.)

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
cd /Users/jhonwheeler/wt-nexora-phase1
git add core/nexora_db.py tests/test_nexora_entities.py
git commit -m "feat(nexora): additive FE columns on existing nx_ tables"
```

---

## Task 2: Entity registry + field mapping

**Files:** Create `core/nexora_entities.py`; append tests to `tests/test_nexora_entities.py`.

- [ ] **Step 1: Append the failing test**

```python
from core import nexora_entities as ent

def test_registry_and_mapping_roundtrip(db):
    # _from_fe keeps only writable fields, mapped to columns
    cols = ent._from_fe("CreatorProfile", {"display_name": "Ann", "bio": "hi", "id": 7, "status": "approved"})
    assert cols == {"display_name": "Ann", "bio": "hi"}  # id + status not writable
    # social_links json writable encodes to text
    cols2 = ent._from_fe("CreatorProfile", {"social_links": {"twitter": "@a"}})
    assert cols2["social_links"] == '{"twitter": "@a"}'

def test_to_fe_types(db):
    import json, time as _t
    conn = db.get_conn()
    conn.execute("INSERT INTO nx_creators (email,name,handle,created_at,user_email,display_name,"
                 "social_links,is_live,total_earnings) VALUES (?,?,?,?,?,?,?,?,?)",
                 ("c@x.com","C","cee",1700000000.0,"c@x.com","Cee",'{"x":1}',1,12.5))
    row = conn.execute("SELECT * FROM nx_creators WHERE email='c@x.com'").fetchone()
    conn.close()
    fe = ent._to_fe("CreatorProfile", row)
    assert fe["user_email"] == "c@x.com" and fe["display_name"] == "Cee"
    assert fe["social_links"] == {"x": 1}        # json parsed
    assert fe["is_live"] is True                  # bool
    assert isinstance(fe["created_date"], str) and fe["created_date"].endswith("Z")  # iso
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Create `core/nexora_entities.py`**

```python
#!/usr/bin/env python3
"""core/nexora_entities.py — declarative entity registry + FE<->row mapping + REST ops."""
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.nexora_db import get_conn, init_db

# field spec: FE name -> (column, type)  type in {str,int,float,bool,json,ts}
ENTITIES = {
    "CreatorProfile": {
        "table": "nx_creators", "pk": "id", "owner_col": "user_email",
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "display_name": ("display_name", "str"), "bio": ("bio", "str"),
            "category": ("category", "str"), "avatar_url": ("avatar", "str"),
            "cover_url": ("cover_url", "str"), "social_links": ("social_links", "json"),
            "subscription_price": ("price", "float"), "status": ("status", "str"),
            "verification_status": ("verification_status", "str"),
            "total_earnings": ("total_earnings", "float"),
            "available_balance": ("available_balance", "float"),
            "subscriber_count": ("subscriber_count", "int"),
            "follower_count": ("follower_count", "int"),
            "is_live": ("is_live", "bool"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email", "status"],
        "writable": ["display_name", "bio", "category", "avatar_url", "cover_url",
                     "social_links", "subscription_price"],
        "create_roles": ["fan", "creator", "admin"], "read_public": True,
    },
    "Post": {
        "table": "nx_posts", "pk": "id", "owner_col": "creator_email",
        "fields": {
            "id": ("id", "int"), "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "title": ("title", "str"), "text": ("text", "str"),
            "media_urls": ("media_urls", "json"), "media_type": ("media_type", "str"),
            "access_type": ("access_type", "str"), "ppv_price": ("ppv_price", "float"),
            "status": ("status", "str"), "like_count": ("like_count", "int"),
            "comment_count": ("comment_count", "int"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "creator_email", "creator_profile_id", "status", "access_type"],
        "writable": ["title", "text", "media_urls", "media_type", "access_type",
                     "ppv_price", "status"],
        "create_roles": ["creator", "admin"], "read_public": True,
    },
    "Subscription": {
        "table": "nx_subscribers", "pk": "id", "owner_col": "fan_email",
        "fields": {
            "id": ("id", "int"), "fan_email": ("fan_email", "str"),
            "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "amount": ("amount", "float"), "status": ("status", "str"),
            "created_date": ("started_at", "ts"),
        },
        "filterable": ["id", "fan_email", "creator_email", "status"],
        "writable": ["status"],
        "create_roles": ["admin"], "read_public": False,
    },
    "Transaction": {
        "table": "nx_transactions", "pk": "id", "owner_col": "to_email",
        "fields": {
            "id": ("id", "int"), "from_email": ("from_email", "str"),
            "to_email": ("to_email", "str"), "amount": ("amount", "float"),
            "creator_amount": ("creator_amount", "float"),
            "platform_fee": ("platform_fee", "float"), "type": ("type", "str"),
            "status": ("status", "str"), "description": ("description", "str"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "from_email", "to_email", "type", "status"],
        "writable": [], "create_roles": ["admin"], "read_public": False,
    },
    "PayoutRequest": {
        "table": "nx_payouts", "pk": "id", "owner_col": "creator_email",
        "fields": {
            "id": ("id", "int"), "creator_email": ("creator_email", "str"),
            "amount": ("amount", "float"), "payout_method": ("payout_method", "str"),
            "status": ("status", "str"), "admin_notes": ("admin_notes", "str"),
            "created_date": ("requested_at", "ts"),
        },
        "filterable": ["id", "creator_email", "status"],
        "writable": ["status", "admin_notes"],
        "create_roles": ["creator", "admin"], "read_public": False,
    },
    "User": {
        "table": "nx_users", "pk": "email", "owner_col": "email",
        "fields": {
            "id": ("email", "str"), "email": ("email", "str"),
            "full_name": ("full_name", "str"), "role": ("role", "str"),
            "is_suspended": ("is_suspended", "bool"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["email", "role", "is_suspended"],
        "writable": ["is_suspended", "full_name"],
        "create_roles": ["admin"], "read_public": False,
    },
}


def _iso(epoch) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _to_fe(entity: str, row) -> Dict:
    spec = ENTITIES[entity]
    keys = row.keys() if hasattr(row, "keys") else []
    out = {}
    for fe, (col, typ) in spec["fields"].items():
        if col not in keys:
            continue
        v = row[col]
        if v is None:
            out[fe] = None
        elif typ == "bool":
            out[fe] = bool(v)
        elif typ == "int":
            out[fe] = int(v)
        elif typ == "float":
            out[fe] = float(v)
        elif typ == "json":
            try:
                out[fe] = json.loads(v) if isinstance(v, str) else v
            except Exception:
                out[fe] = v
        elif typ == "ts":
            out[fe] = _iso(v)
        else:
            out[fe] = v
    return out


def _from_fe(entity: str, body: Dict) -> Dict:
    spec = ENTITIES[entity]
    cols = {}
    for fe in spec["writable"]:
        if fe in body:
            col, typ = spec["fields"][fe]
            v = body[fe]
            if typ == "json" and not isinstance(v, str):
                v = json.dumps(v)
            elif typ == "bool":
                v = 1 if v else 0
            cols[col] = v
    return cols
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add core/nexora_entities.py tests/test_nexora_entities.py
git commit -m "feat(nexora): entity registry + FE<->row field mapping"
```

---

## Task 3: Entity read ops (query/get)

**Files:** Modify `core/nexora_entities.py`; append tests.

- [ ] **Step 1: Append the failing test**

```python
def test_entity_query_filter_sort_limit(db):
    conn = db.get_conn()
    for i, st in enumerate(["approved", "pending", "approved"]):
        conn.execute("INSERT INTO nx_creators (email,name,handle,created_at,user_email,status) "
                     "VALUES (?,?,?,?,?,?)", (f"c{i}@x.com", f"C{i}", f"c{i}", 1700000000.0+i, f"c{i}@x.com", st))
    conn.commit(); conn.close()
    out = ent.entity_query("CreatorProfile", {"status": "approved"}, "-created_date", 10)
    assert len(out) == 2 and all(c["status"] == "approved" for c in out)
    assert out[0]["created_date"] >= out[1]["created_date"]  # desc

def test_entity_get(db):
    conn = db.get_conn()
    conn.execute("INSERT INTO nx_creators (email,name,handle,created_at,user_email) VALUES (?,?,?,?,?)",
                 ("g@x.com","G","g",1700000000.0,"g@x.com"))
    cid = conn.execute("SELECT id FROM nx_creators WHERE email='g@x.com'").fetchone()["id"]
    conn.commit(); conn.close()
    fe = ent.entity_get("CreatorProfile", cid)
    assert fe["user_email"] == "g@x.com"
    assert ent.entity_get("CreatorProfile", 99999) is None
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Append to `core/nexora_entities.py`**

```python
def entity_query(entity: str, criteria: Optional[Dict], sort: Optional[str],
                 limit: Optional[int]) -> List[Dict]:
    spec = ENTITIES[entity]
    init_db()
    where, params = [], []
    for fe, val in (criteria or {}).items():
        if fe in spec["filterable"]:
            col, typ = spec["fields"][fe]
            if typ == "bool":
                val = 1 if str(val).lower() in ("1", "true") else 0
            where.append(f"{col}=?"); params.append(val)
    sql = f"SELECT * FROM {spec['table']}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if sort:
        desc = sort.startswith("-")
        fe = sort[1:] if desc else sort
        col = spec["fields"].get(fe, (None,))[0]
        if col:
            sql += f" ORDER BY {col} {'DESC' if desc else 'ASC'}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_to_fe(entity, r) for r in rows]


def entity_get(entity: str, pk_value) -> Optional[Dict]:
    spec = ENTITIES[entity]
    init_db()
    conn = get_conn()
    row = conn.execute(f"SELECT * FROM {spec['table']} WHERE {spec['pk']}=?", (pk_value,)).fetchone()
    conn.close()
    return _to_fe(entity, row) if row else None
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add core/nexora_entities.py tests/test_nexora_entities.py
git commit -m "feat(nexora): entity_query (filter/sort/limit) + entity_get"
```

---

## Task 4: Entity write ops (create/update/delete) with ownership

**Files:** Modify `core/nexora_entities.py`; append tests.

- [ ] **Step 1: Append the failing test**

```python
def test_entity_create_stamps_owner(db):
    actor = {"email": "creator@x.com", "role": "creator"}
    fe = ent.entity_create("Post", {"title": "Hi", "text": "yo", "access_type": "free"}, actor)
    assert fe["title"] == "Hi" and fe["creator_email"] == "creator@x.com"
    assert fe["id"] and fe["created_date"]

def test_entity_update_owner_only(db):
    owner = {"email": "o@x.com", "role": "creator"}
    other = {"email": "x@x.com", "role": "creator"}
    admin = {"email": "a@x.com", "role": "admin"}
    fe = ent.entity_create("Post", {"title": "P"}, owner)
    # non-owner non-admin blocked
    with pytest.raises(PermissionError):
        ent.entity_update("Post", fe["id"], {"title": "hax"}, other)
    # owner allowed
    upd = ent.entity_update("Post", fe["id"], {"title": "P2"}, owner)
    assert upd["title"] == "P2"
    # admin allowed
    upd2 = ent.entity_update("Post", fe["id"], {"status": "removed"}, admin)
    assert upd2["status"] == "removed"

def test_entity_delete_owner_only(db):
    owner = {"email": "d@x.com", "role": "creator"}
    fe = ent.entity_create("Post", {"title": "D"}, owner)
    with pytest.raises(PermissionError):
        ent.entity_delete("Post", fe["id"], {"email": "z@x.com", "role": "fan"})
    ent.entity_delete("Post", fe["id"], owner)
    assert ent.entity_get("Post", fe["id"]) is None
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Append to `core/nexora_entities.py`**

```python
def _owner_email(entity: str, pk_value) -> Optional[str]:
    spec = ENTITIES[entity]
    conn = get_conn()
    row = conn.execute(f"SELECT {spec['owner_col']} AS o FROM {spec['table']} WHERE {spec['pk']}=?",
                       (pk_value,)).fetchone()
    conn.close()
    return row["o"] if row else None


def _require_owner_or_admin(entity: str, pk_value, actor: Dict) -> None:
    if actor.get("role") == "admin":
        return
    owner = _owner_email(entity, pk_value)
    if owner is None or owner != actor.get("email"):
        raise PermissionError("not allowed")


def entity_create(entity: str, body: Dict, actor: Dict) -> Dict:
    spec = ENTITIES[entity]
    if actor.get("role") not in spec.get("create_roles", []):
        raise PermissionError("not allowed")
    init_db()
    cols = _from_fe(entity, body)
    cols[spec["owner_col"]] = actor["email"]            # stamp ownership from token
    # created timestamp column (the FE created_date source)
    ts_col = spec["fields"]["created_date"][0]
    cols.setdefault(ts_col, time.time())
    keys = list(cols.keys())
    placeholders = ",".join("?" for _ in keys)
    conn = get_conn()
    cur = conn.execute(f"INSERT INTO {spec['table']} ({','.join(keys)}) VALUES ({placeholders})",
                       [cols[k] for k in keys])
    new_pk = actor["email"] if spec["pk"] == spec["owner_col"] else cur.lastrowid
    conn.commit(); conn.close()
    return entity_get(entity, new_pk)


def entity_update(entity: str, pk_value, body: Dict, actor: Dict) -> Optional[Dict]:
    _require_owner_or_admin(entity, pk_value, actor)
    spec = ENTITIES[entity]
    cols = _from_fe(entity, body)
    if cols:
        sets = ",".join(f"{k}=?" for k in cols)
        conn = get_conn()
        conn.execute(f"UPDATE {spec['table']} SET {sets} WHERE {spec['pk']}=?",
                     [*cols.values(), pk_value])
        conn.commit(); conn.close()
    return entity_get(entity, pk_value)


def entity_delete(entity: str, pk_value, actor: Dict) -> None:
    _require_owner_or_admin(entity, pk_value, actor)
    spec = ENTITIES[entity]
    conn = get_conn()
    conn.execute(f"DELETE FROM {spec['table']} WHERE {spec['pk']}=?", (pk_value,))
    conn.commit(); conn.close()
```

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add core/nexora_entities.py tests/test_nexora_entities.py
git commit -m "feat(nexora): entity create/update/delete with token-derived ownership"
```

---

## Task 5: FastAPI `/api/nx/e/{entity}` routes

**Files:** Modify `core/api.py`; create `tests/test_nexora_entity_routes.py`.

> Verified in-process via TestClient (monkeypatched temp DB); the live daemon is never touched.

- [ ] **Step 1: Add routes to `core/api.py`** — after the `/api/nx/auth/logout` route block (grep `grep -n "/api/nx/auth/logout" core/api.py`), insert:

```python
@app.get("/api/nx/e/{entity}")
def nx_entity_list(entity: str, request: Request):
    _nx_require_user(request)
    from core.nexora_entities import ENTITIES, entity_query
    if entity not in ENTITIES:
        raise HTTPException(status_code=404, detail="Unknown entity")
    qp = dict(request.query_params)
    sort = qp.pop("_sort", None)
    limit = qp.pop("_limit", None)
    return entity_query(entity, qp, sort, int(limit) if limit else None)


@app.post("/api/nx/e/{entity}")
async def nx_entity_create(entity: str, request: Request):
    user = _nx_require_user(request)
    from core.nexora_entities import ENTITIES, entity_create
    if entity not in ENTITIES:
        raise HTTPException(status_code=404, detail="Unknown entity")
    body = await request.json()
    try:
        return entity_create(entity, body, user)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Not allowed")


@app.patch("/api/nx/e/{entity}/{pk}")
async def nx_entity_update(entity: str, pk: str, request: Request):
    user = _nx_require_user(request)
    from core.nexora_entities import ENTITIES, entity_update
    if entity not in ENTITIES:
        raise HTTPException(status_code=404, detail="Unknown entity")
    body = await request.json()
    try:
        return entity_update(entity, pk, body, user)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Not allowed")


@app.delete("/api/nx/e/{entity}/{pk}")
def nx_entity_delete(entity: str, pk: str, request: Request):
    user = _nx_require_user(request)
    from core.nexora_entities import ENTITIES, entity_delete
    if entity not in ENTITIES:
        raise HTTPException(status_code=404, detail="Unknown entity")
    try:
        entity_delete(entity, pk, user)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Not allowed")
    return {"ok": True}
```

- [ ] **Step 2: Create `tests/test_nexora_entity_routes.py`**

```python
import pytest
import core.api as api
from core import nexora_db, nexora_auth
from fastapi.testclient import TestClient

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _creator(db):
    return nexora_auth.register_creator("c@x.com", "hunter2", "Cee")["token"]

def test_entity_routes_crud_and_auth(db):
    tok = _creator(db)
    client = TestClient(api.app)
    h = {"Authorization": f"Bearer {tok}"}
    # unauthenticated → 401
    assert client.get("/api/nx/e/Post").status_code == 401
    # unknown entity → 404
    assert client.get("/api/nx/e/Nope", headers=h).status_code == 404
    # create
    r = client.post("/api/nx/e/Post", headers=h, json={"title": "Hi", "access_type": "free"})
    assert r.status_code == 200 and r.json()["creator_email"] == "c@x.com"
    pid = r.json()["id"]
    # list with filter
    lst = client.get("/api/nx/e/Post?creator_email=c@x.com", headers=h)
    assert lst.status_code == 200 and any(p["id"] == pid for p in lst.json())
    # update by owner
    up = client.patch(f"/api/nx/e/Post/{pid}", headers=h, json={"title": "Hi2"})
    assert up.status_code == 200 and up.json()["title"] == "Hi2"
    # delete by owner
    assert client.delete(f"/api/nx/e/Post/{pid}", headers=h).status_code == 200

def test_entity_update_blocked_for_non_owner(db):
    tok = _creator(db)
    client = TestClient(api.app)
    pid = client.post("/api/nx/e/Post", headers={"Authorization": f"Bearer {tok}"},
                      json={"title": "P"}).json()["id"]
    other = nexora_auth.register_creator("o@x.com", "hunter2", "Oh")["token"]
    r = client.patch(f"/api/nx/e/Post/{pid}", headers={"Authorization": f"Bearer {other}"},
                     json={"title": "hax"})
    assert r.status_code == 403
```

- [ ] **Step 3: Run → PASS** (`python3 -m pytest tests/test_nexora_entity_routes.py -v`). Also run `tests/test_nexora_entities.py` + Phase-1 suites to confirm no regression.

- [ ] **Step 4: Commit**

```bash
git add core/api.py tests/test_nexora_entity_routes.py
git commit -m "feat(nexora): /api/nx/e/{entity} REST routes (list/create/update/delete)"
```

---

## Phase 3 Done — Definition of Done
- [ ] `python3 -m pytest tests/test_nexora_entities.py tests/test_nexora_entity_routes.py tests/test_nexora_users.py tests/test_nexora_api.py tests/test_nexora_admin.py -q` → all green.
- [ ] CreatorProfile, Post, Subscription, Transaction, PayoutRequest, User each list/round-trip via `/api/nx/e/<E>`; ownership enforced (non-owner update/delete → 403; admin override works).
- [ ] No regression in Phase-1 auth.

## Next Phase
Phase 4 — new-table entities (Follow, Notification, ContentPurchase, FanProfile, LiveStream, Tip) added as registry entries + `CREATE TABLE`s, reusing this exact machinery.
