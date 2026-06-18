# Nexora Deferred Entities — PlatformSettings + Message (→ 18/18)

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Back the last 2 entities, each needing a small machinery addition:
- **PlatformSettings** — key-value config, no owner, string `key` pk. Needs `no_owner` (skip owner stamp) + `pk_from_body` (new_pk from the body-provided key).
- **Message** (new table `nx_dms`) — the app fetches DMs unscoped (`Message.filter({})`), so reads must auto-restrict to rows where the user is a party. Needs `auto_scope_self` + an OR-scoped query.

**Repo:** `/Users/jhonwheeler/wt-nexora-phase1`, branch `nexora/phase9-deferred-entities` (stacked on Phase 8b). NEVER touch `/Users/jhonwheeler/wheellsverse_bots`.

## entity_create reference (insertion points)
- Owner stamp block: `if spec.get("owner_from_body"): ... else: cols[spec["owner_col"]] = actor["email"]`
- ts default: `ts_col = spec["fields"]["created_date"][0]; cols.setdefault(ts_col, time.time())`
- new_pk: `new_pk = actor["email"] if spec["pk"] == spec["owner_col"] else cur.lastrowid`

---

## Task 1: PlatformSettings (no_owner + pk_from_body)

**Files:** `core/nexora_db.py`, `core/nexora_entities.py`, `tests/test_nexora_deferred.py`.

- [ ] **Step 1: failing test** (`tests/test_nexora_deferred.py`)

```python
import pytest
from core import nexora_db, nexora_auth, nexora_users, nexora_entities as ent

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def test_platform_settings_keyed_create_update(db):
    admin = {"email": "a@x.com", "role": "admin"}
    s = ent.entity_create("PlatformSettings", {"key": "platform_fee_pct", "value": "10"}, admin)
    assert s["key"] == "platform_fee_pct" and s["value"] == "10" and s["id"] == "platform_fee_pct"
    # update by key
    u = ent.entity_update("PlatformSettings", "platform_fee_pct", {"value": "15"}, admin)
    assert u["value"] == "15"
    # exactly one row (keyed pk, no duplicate)
    rows = ent.entity_query("PlatformSettings", {"key": "platform_fee_pct"}, None, None)
    assert len(rows) == 1

def test_platform_settings_admin_only_create(db):
    with pytest.raises(PermissionError):
        ent.entity_create("PlatformSettings", {"key": "k", "value": "v"}, {"email": "f@x.com", "role": "fan"})
```

- [ ] **Step 2: run → FAIL.**

- [ ] **Step 3a: add table to `_SCHEMA` in `core/nexora_db.py`:**

```sql

CREATE TABLE IF NOT EXISTS nx_platform_settings (
    key         TEXT    PRIMARY KEY,
    value       TEXT    DEFAULT '',
    created_at  REAL    NOT NULL
);
```

- [ ] **Step 3b: add the PlatformSettings entry to `ENTITIES`:**

```python
    "PlatformSettings": {
        "table": "nx_platform_settings", "pk": "key", "no_owner": True, "pk_from_body": True,
        "fields": {
            "id": ("key", "str"), "key": ("key", "str"), "value": ("value", "str"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["key"],
        "writable": ["key", "value"],
        "create_roles": ["admin"], "read_public": False,
    },
```

- [ ] **Step 3c: machinery in `entity_create`** (`core/nexora_entities.py`):
(i) Replace the owner-stamp block's start so `no_owner` skips stamping:
```python
    if spec.get("no_owner"):
        pass
    elif spec.get("owner_from_body"):
        owner_fe = next(fe for fe, (c, _t) in spec["fields"].items() if c == spec["owner_col"])
        if owner_fe not in body:
            raise PermissionError("recipient required")
        cols[spec["owner_col"]] = body[owner_fe]
    else:
        cols[spec["owner_col"]] = actor["email"]
```
(ii) Change the `new_pk` line to honor `pk_from_body`:
```python
    if spec.get("pk_from_body"):
        new_pk = cols.get(spec["pk"])
    elif spec["pk"] == spec.get("owner_col"):
        new_pk = actor["email"]
    else:
        new_pk = cur.lastrowid
```
(Leave the upsert branch, ts default, and create_link_creator untouched. The ts default uses `spec["fields"]["created_date"]` — PlatformSettings has `created_date`, so it works.)

- [ ] **Step 4: run → PASS** (`cd /Users/jhonwheeler/wt-nexora-phase1 && python3 -m pytest tests/test_nexora_deferred.py -v`). Regression: `python3 -m pytest tests/test_nexora_entities.py tests/test_nexora_phase4.py tests/test_nexora_phase7.py -q` (no_owner/pk_from_body are opt-in; other entities unaffected).

- [ ] **Step 5: commit**

```bash
git add core/nexora_db.py core/nexora_entities.py tests/test_nexora_deferred.py
git commit -m "feat(nexora): PlatformSettings entity (no_owner + pk_from_body machinery)"
```

---

## Task 2: Message → nx_dms (auto_scope_self OR-query)

**Files:** `core/nexora_db.py`, `core/nexora_entities.py`, `core/api.py`, `tests/test_nexora_deferred.py`.

- [ ] **Step 1: append failing test**

```python
import core.api as api
from fastapi.testclient import TestClient

def _h(t): return {"Authorization": f"Bearer {t}"}

def test_message_create_and_auto_scoped_read(db):
    a = nexora_auth.register_fan("a@x.com", "hunter2")["token"]
    b = nexora_auth.register_fan("b@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    # A messages B
    r = c.post("/api/nx/e/Message", headers=_h(a), json={"to_email": "b@x.com", "text": "hi", "conversation_id": "a|b"})
    assert r.status_code == 200 and r.json()["from_email"] == "a@x.com"
    # A fetches messages WITH NO filter -> auto-scoped to A's (no 403)
    la = c.get("/api/nx/e/Message", headers=_h(a))
    assert la.status_code == 200 and len(la.json()) == 1 and la.json()[0]["text"] == "hi"
    # B also sees it (B is the to_email party)
    lb = c.get("/api/nx/e/Message", headers=_h(b))
    assert lb.status_code == 200 and len(lb.json()) == 1
    # an unrelated user sees none
    z = nexora_auth.register_fan("z@x.com", "hunter2")["token"]
    lz = c.get("/api/nx/e/Message", headers=_h(z))
    assert lz.status_code == 200 and len(lz.json()) == 0
```

- [ ] **Step 2: run → FAIL.**

- [ ] **Step 3a: add table to `_SCHEMA`:**

```sql

CREATE TABLE IF NOT EXISTS nx_dms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_email      TEXT    NOT NULL,
    to_email        TEXT    DEFAULT '',
    conversation_id TEXT    DEFAULT '',
    text            TEXT    DEFAULT '',
    created_at      REAL    NOT NULL
);
```

- [ ] **Step 3b: add the Message entry to `ENTITIES`:**

```python
    "Message": {
        "table": "nx_dms", "pk": "id", "owner_col": "from_email", "auto_scope_self": True,
        "fields": {
            "id": ("id", "int"), "from_email": ("from_email", "str"),
            "to_email": ("to_email", "str"), "conversation_id": ("conversation_id", "str"),
            "text": ("text", "str"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "from_email", "to_email", "conversation_id"],
        "writable": ["to_email", "conversation_id", "text"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["from_email", "to_email"],
    },
```

- [ ] **Step 3c: add `entity_query_scoped` to `core/nexora_entities.py`** (OR-scope across self_cols, AND other filterable criteria):

```python
def entity_query_scoped(entity: str, criteria: Optional[Dict], sort: Optional[str],
                        limit: Optional[int], scope_cols: List[str], email: str) -> List[Dict]:
    """Like entity_query but restricts to rows where `email` matches ANY scope_col
    (OR), AND any additional filterable criteria. For auto_scope_self entities."""
    spec = ENTITIES[entity]
    init_db()
    where, params = [], []
    ors = []
    for c in scope_cols:
        col = spec["fields"][c][0]
        ors.append(f"{col}=? COLLATE NOCASE"); params.append(email)
    if ors:
        where.append("(" + " OR ".join(ors) + ")")
    for fe, val in (criteria or {}).items():
        if fe in spec["filterable"] and fe not in scope_cols:
            col, typ = spec["fields"][fe]
            where.append(f"{col}=?"); params.append(val)
    sql = f"SELECT * FROM {spec['table']}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if sort:
        desc = sort.startswith("-"); fe = sort[1:] if desc else sort
        col = spec["fields"].get(fe, (None,))[0]
        if col:
            sql += f" ORDER BY {col} {'DESC' if desc else 'ASC'}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_to_fe(entity, r) for r in rows]
```

- [ ] **Step 3d: hook it into the GET route `nx_entity_list` in `core/api.py`** — in the read-authz block, before the `if not any(...)` 403 check, add the auto-scope branch:

```python
    if not spec.get("read_public") and user["role"] != "admin":
        if spec.get("auto_scope_self"):
            from core.nexora_entities import entity_query_scoped
            return entity_query_scoped(entity, qp, sort, int(limit) if limit else None,
                                       self_cols, user["email"])
        if not any(qp.get(c) == user["email"] for c in self_cols):
            raise HTTPException(status_code=403, detail="Not allowed")
```
(Admins still fall through to the normal `entity_query` and see all.)

- [ ] **Step 4: run → PASS** (`python3 -m pytest tests/test_nexora_deferred.py -v`). Full regression: `python3 -m pytest tests/test_nexora_*.py -q`.

- [ ] **Step 5: commit**

```bash
git add core/nexora_db.py core/nexora_entities.py core/api.py tests/test_nexora_deferred.py
git commit -m "feat(nexora): Message DMs (nx_dms) with auto_scope_self OR-query read — 18/18 entities backed"
```

## Done — DoD
- [ ] PlatformSettings: keyed create/update (no duplicate), admin-only. Message: create + auto-scoped read (party sees own, unrelated sees none, no 403 on unscoped fetch). **18/18 entities backed.** Full suite green.

## Note
PlatformSettings read is admin-only (no `self_cols`). If creator-facing settings (e.g. public fee %) are needed later, add a public read path. The webhook still uses a hardcoded 10% fee — wiring it to read PlatformSettings is a separate follow-up.
