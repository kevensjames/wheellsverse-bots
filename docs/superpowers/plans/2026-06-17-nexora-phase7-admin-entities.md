# Nexora Phase 7 — Admin/Governance Entities Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Back the admin console's 4 governance entities — **Report, ModerationAction, AuditLog, CreatorVerification** — as new `nx_` tables + registry entries, reusing the Phase-3/4 machinery (no machinery changes). This makes the admin moderation/approvals/audit/KYC flows work end-to-end.

**Repo:** `/Users/jhonwheeler/wt-nexora-phase1`, branch `nexora/phase7-admin` (stacked on Phase 6). NEVER touch `/Users/jhonwheeler/wheellsverse_bots`.

## Scope & deferral
- **In:** Report, ModerationAction, AuditLog, CreatorVerification (all fit existing machinery: owner stamp, `writable_admin` for admin-only fields, `self_cols` read-scope).
- **Deferred (tracked, design friction):** **PlatformSettings** (string `key` pk + no owner — needs new `no_owner`/`pk_from_body` flags; it's just fee/min-payout config, seed directly for now) and **Message** (the app's `Message.filter({})` queries ALL dms unscoped, which conflicts with read-scoping — needs a frontend scoping change). After Phase 7: **16/18 entities backed**.

## App usage (drives the registry)
- Report: admin `list` + `update({status, admin_notes})`; created by reporters.
- ModerationAction: admin `create`.
- AuditLog: admin `create`.
- CreatorVerification: creator `create` + `filter({user_email})`; admin `list` + `update({status, reviewed_at, reviewed_by_admin_email, review_notes})`.

---

## Task 1: New tables

**Files:** Modify `core/nexora_db.py` (`_SCHEMA`); create `tests/test_nexora_phase7.py`.

- [ ] **Step 1: failing test** (`tests/test_nexora_phase7.py`)

```python
import pytest
from core import nexora_db

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _cols(db, t):
    conn = db.get_conn()
    c = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
    conn.close(); return c

def test_phase7_tables(db):
    assert {"id","reporter_email","reported_email","reason","details","status","admin_notes","created_at"} <= _cols(db, "nx_reports")
    assert {"id","admin_email","target_user_email","action_type","reason","notes","related_report_id","created_at"} <= _cols(db, "nx_moderation_actions")
    assert {"id","actor_email","action","entity_type","entity_id","details","created_at"} <= _cols(db, "nx_audit_logs")
    assert {"id","user_email","legal_full_name","date_of_birth","country","document_type","document_front_url",
            "document_back_url","selfie_url","consent_confirmed","status","reviewed_at",
            "reviewed_by_admin_email","review_notes","created_at"} <= _cols(db, "nx_creator_verifications")
```

- [ ] **Step 2: run → FAIL.**

- [ ] **Step 3: append to `_SCHEMA` in `core/nexora_db.py`** (before its closing `"""`):

```sql

CREATE TABLE IF NOT EXISTS nx_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_email  TEXT    NOT NULL,
    reported_email  TEXT    DEFAULT '',
    reason          TEXT    DEFAULT '',
    details         TEXT    DEFAULT '',
    status          TEXT    DEFAULT 'open',
    admin_notes     TEXT    DEFAULT '',
    created_at      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_moderation_actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_email         TEXT    NOT NULL,
    target_user_email   TEXT    DEFAULT '',
    action_type         TEXT    DEFAULT '',
    reason              TEXT    DEFAULT '',
    notes               TEXT    DEFAULT '',
    related_report_id   INTEGER,
    created_at          REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_email TEXT    NOT NULL,
    action      TEXT    DEFAULT '',
    entity_type TEXT    DEFAULT '',
    entity_id   TEXT    DEFAULT '',
    details     TEXT    DEFAULT '',
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_creator_verifications (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email              TEXT    NOT NULL,
    legal_full_name         TEXT    DEFAULT '',
    date_of_birth           TEXT    DEFAULT '',
    country                 TEXT    DEFAULT '',
    document_type           TEXT    DEFAULT '',
    document_front_url      TEXT    DEFAULT '',
    document_back_url       TEXT    DEFAULT '',
    selfie_url              TEXT    DEFAULT '',
    consent_confirmed       INTEGER DEFAULT 0,
    status                  TEXT    DEFAULT 'submitted',
    reviewed_at             TEXT    DEFAULT '',
    reviewed_by_admin_email TEXT    DEFAULT '',
    review_notes            TEXT    DEFAULT '',
    created_at              REAL    NOT NULL
);
```

- [ ] **Step 4: run → PASS.** Commit:

```bash
git add core/nexora_db.py tests/test_nexora_phase7.py
git commit -m "feat(nexora): admin tables — reports, moderation_actions, audit_logs, creator_verifications"
```

---

## Task 2: Registry entries

**Files:** Modify `core/nexora_entities.py`; append tests to `tests/test_nexora_phase7.py`.

- [ ] **Step 1: append failing test**

```python
from core import nexora_entities as ent
from core import nexora_auth

def test_report_create_and_admin_resolve(db):
    reporter = {"email": "r@x.com", "role": "fan"}
    admin = {"email": "a@x.com", "role": "admin"}
    rep = ent.entity_create("Report", {"reported_email": "bad@x.com", "reason": "spam", "details": "d"}, reporter)
    assert rep["reporter_email"] == "r@x.com" and rep["status"] == "open"
    # reporter cannot set status; admin can
    assert ent.entity_update("Report", rep["id"], {"status": "resolved"}, reporter)["status"] == "open"
    assert ent.entity_update("Report", rep["id"], {"status": "resolved", "admin_notes": "ok"}, admin)["status"] == "resolved"

def test_creator_verification_flow(db):
    nexora_auth.register_creator("v@x.com", "hunter2", "V")
    creator = {"email": "v@x.com", "role": "creator"}
    admin = {"email": "ad@x.com", "role": "admin"}
    cv = ent.entity_create("CreatorVerification",
        {"legal_full_name": "Vee Person", "country": "US", "consent_confirmed": True,
         "document_front_url": "u1", "status": "approved"}, creator)  # creator can't self-approve
    assert cv["user_email"] == "v@x.com" and cv["status"] == "submitted" and cv["consent_confirmed"] is True
    # admin reviews
    rev = ent.entity_update("CreatorVerification", cv["id"],
        {"status": "approved", "review_notes": "ok", "reviewed_by_admin_email": "ad@x.com"}, admin)
    assert rev["status"] == "approved" and rev["reviewed_by_admin_email"] == "ad@x.com"

def test_admin_only_creates(db):
    fan = {"email": "f@x.com", "role": "fan"}
    for e in ("ModerationAction", "AuditLog"):
        with pytest.raises(PermissionError):
            ent.entity_create(e, {"action": "x"}, fan)
    admin = {"email": "a@x.com", "role": "admin"}
    al = ent.entity_create("AuditLog", {"action": "approve", "entity_type": "CreatorProfile", "entity_id": "5"}, admin)
    assert al["actor_email"] == "a@x.com" and al["action"] == "approve"
```

- [ ] **Step 2: run → FAIL.**

- [ ] **Step 3: add 4 entries to the `ENTITIES` dict in `core/nexora_entities.py`:**

```python
    "Report": {
        "table": "nx_reports", "pk": "id", "owner_col": "reporter_email",
        "fields": {
            "id": ("id", "int"), "reporter_email": ("reporter_email", "str"),
            "reported_email": ("reported_email", "str"), "reason": ("reason", "str"),
            "details": ("details", "str"), "status": ("status", "str"),
            "admin_notes": ("admin_notes", "str"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "reporter_email", "reported_email", "status"],
        "writable": ["reported_email", "reason", "details"],
        "writable_admin": ["status", "admin_notes"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["reporter_email"],
    },
    "ModerationAction": {
        "table": "nx_moderation_actions", "pk": "id", "owner_col": "admin_email",
        "fields": {
            "id": ("id", "int"), "admin_email": ("admin_email", "str"),
            "target_user_email": ("target_user_email", "str"), "action_type": ("action_type", "str"),
            "reason": ("reason", "str"), "notes": ("notes", "str"),
            "related_report_id": ("related_report_id", "int"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "admin_email", "target_user_email"],
        "writable": ["target_user_email", "action_type", "reason", "notes", "related_report_id"],
        "create_roles": ["admin"],
        "read_public": False, "self_cols": ["admin_email"],
    },
    "AuditLog": {
        "table": "nx_audit_logs", "pk": "id", "owner_col": "actor_email",
        "fields": {
            "id": ("id", "int"), "actor_email": ("actor_email", "str"),
            "action": ("action", "str"), "entity_type": ("entity_type", "str"),
            "entity_id": ("entity_id", "str"), "details": ("details", "str"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "actor_email", "action", "entity_type"],
        "writable": ["action", "entity_type", "entity_id", "details"],
        "create_roles": ["admin"],
        "read_public": False, "self_cols": ["actor_email"],
    },
    "CreatorVerification": {
        "table": "nx_creator_verifications", "pk": "id", "owner_col": "user_email",
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "legal_full_name": ("legal_full_name", "str"), "date_of_birth": ("date_of_birth", "str"),
            "country": ("country", "str"), "document_type": ("document_type", "str"),
            "document_front_url": ("document_front_url", "str"),
            "document_back_url": ("document_back_url", "str"), "selfie_url": ("selfie_url", "str"),
            "consent_confirmed": ("consent_confirmed", "bool"), "status": ("status", "str"),
            "reviewed_at": ("reviewed_at", "str"),
            "reviewed_by_admin_email": ("reviewed_by_admin_email", "str"),
            "review_notes": ("review_notes", "str"),
            "submitted_at": ("created_at", "ts"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email", "status"],
        "writable": ["legal_full_name", "date_of_birth", "country", "document_type",
                     "document_front_url", "document_back_url", "selfie_url", "consent_confirmed"],
        "writable_admin": ["status", "reviewed_at", "reviewed_by_admin_email", "review_notes"],
        "create_roles": ["creator", "admin"],
        "read_public": False, "self_cols": ["user_email"],
    },
```

- [ ] **Step 4: run → PASS** (`cd /Users/jhonwheeler/wt-nexora-phase1 && python3 -m pytest tests/test_nexora_phase7.py -v`). Regression: `python3 -m pytest tests/test_nexora_entities.py -q`. Commit:

```bash
git add core/nexora_entities.py tests/test_nexora_phase7.py
git commit -m "feat(nexora): register Report/ModerationAction/AuditLog/CreatorVerification entities"
```

---

## Task 3: Route integration tests

**Files:** Append to `tests/test_nexora_phase7.py`.

- [ ] **Step 1: append**

```python
import core.api as api
from core import nexora_users
from fastapi.testclient import TestClient

def _admin_token(db):
    nexora_auth.register_creator("admin@x.com", "hunter2", "Admin")
    nexora_users.set_role("admin@x.com", "admin")
    return nexora_auth.login_creator("admin@x.com", "hunter2")["token"]

def _h(t): return {"Authorization": f"Bearer {t}"}

def test_report_routes_admin_only_read(db):
    rep_tok = nexora_auth.register_fan("rep@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    # a fan can create a report
    r = c.post("/api/nx/e/Report", headers=_h(rep_tok), json={"reported_email": "b@x.com", "reason": "spam"})
    assert r.status_code == 200
    # a non-admin cannot list all reports (no self-scope) -> 403
    assert c.get("/api/nx/e/Report", headers=_h(rep_tok)).status_code == 403
    # admin can list
    atok = _admin_token(db)
    assert c.get("/api/nx/e/Report", headers=_h(atok)).status_code == 200

def test_creator_verification_routes(db):
    tok = nexora_auth.register_creator("cv@x.com", "hunter2", "CV")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/e/CreatorVerification", headers=_h(tok),
               json={"legal_full_name": "C V", "country": "US", "consent_confirmed": True})
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    vid = r.json()["id"]
    # creator reads own (self-scoped)
    assert c.get("/api/nx/e/CreatorVerification?user_email=cv@x.com", headers=_h(tok)).status_code == 200
    # admin approves
    atok = _admin_token(db)
    up = c.patch(f"/api/nx/e/CreatorVerification/{vid}", headers=_h(atok), json={"status": "approved"})
    assert up.status_code == 200 and up.json()["status"] == "approved"
```

- [ ] **Step 2: run → PASS.** Full regression:
`python3 -m pytest tests/test_nexora_phase7.py tests/test_nexora_entities.py tests/test_nexora_entity_routes.py tests/test_nexora_phase4.py tests/test_nexora_aggregations.py tests/test_nexora_users.py -q`.

- [ ] **Step 3: commit**

```bash
git add tests/test_nexora_phase7.py
git commit -m "test(nexora): admin entity route integration (report read-gating, verification flow)"
```

---

## Phase 7 Done — DoD
- [ ] 4 admin entities backed; reporter can't self-resolve a report (admin-only `status`); creator can't self-approve verification (admin-only `status`); ModerationAction/AuditLog admin-only create; admin-only read of reports.
- [ ] Full suite green. **16/18 entities backed.**

## Tracked
- **PlatformSettings** + **Message** deferred (design friction — see Scope). PlatformSettings: seed `platform_fee_pct`/`min_payout` directly; the webhook already uses a 10% constant.

## Next Phase
Phase 8 — ops (`recalcCreatorStats` to keep persisted counters truthful), then Phase 9 (exposure: `api.wheellsverse.com` tunnel ingress + CORS + deploy) — **the go-live, needs operator credentials.**
