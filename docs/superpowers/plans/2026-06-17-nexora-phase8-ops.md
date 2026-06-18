# Nexora Phase 8 — Ops: recalcCreatorStats

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** An admin ops endpoint that recomputes a creator's persisted counters (`subscriber_count`, `follower_count`, `total_earnings`, `available_balance`) from source rows — reconciling drift, since the webhook bumps them incrementally.

**Repo:** `/Users/jhonwheeler/wt-nexora-phase1`, branch `nexora/phase8-ops` (stacked on Phase 7). NEVER touch `/Users/jhonwheeler/wheellsverse_bots`.

## Recompute rules (per creator, identified by email == nx_creators.email OR user_email)
- `subscriber_count` = COUNT(nx_subscribers WHERE creator_email=email AND status='active')
- `follower_count`  = COUNT(nx_follows WHERE creator_email=email)
- `total_earnings`  = SUM(nx_transactions.creator_amount WHERE to_email=email)
- `available_balance` = total_earnings − SUM(nx_payouts.amount WHERE creator_email=email AND status='paid')

---

## Task 1: Ops module + admin route

**Files:** Create `core/nexora_ops.py`; modify `core/api.py`; create `tests/test_nexora_ops.py`.

- [ ] **Step 1: failing test** (`tests/test_nexora_ops.py`)

```python
import pytest, time
from core import nexora_db, nexora_auth, nexora_users, nexora_entities as ent
from core import nexora_ops as ops

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _seed(db, email="cr@x.com"):
    nexora_auth.register_creator(email, "hunter2", "Cr")
    ent.entity_create("CreatorProfile", {"display_name": "Cr"}, {"email": email, "role": "creator"})
    conn = db.get_conn(); now = time.time()
    # 2 active subs, 3 follows
    for i in range(2):
        conn.execute("INSERT INTO nx_subscribers (creator_id,fan_email,status,started_at,creator_email) VALUES (?,?,?,?,?)",
                     (1, f"s{i}@x.com", "active", now, email))
    for i in range(3):
        conn.execute("INSERT INTO nx_follows (fan_email,creator_email,created_at) VALUES (?,?,?)", (f"f{i}@x.com", email, now))
    # earnings 20.0 (2 txns of 10 creator_amount), one paid payout of 5
    for i in range(2):
        conn.execute("INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,to_email,creator_amount,platform_fee) "
                     "VALUES (?,?,?,?,?,?,?,?)", (1, 11.11, 1.11, 10.0, now, email, 10.0, 1.11))
    conn.execute("INSERT INTO nx_payouts (creator_id,amount,requested_at,creator_email,status) VALUES (?,?,?,?,?)",
                 (1, 5.0, now, email, "paid"))
    # corrupt the persisted counters so recalc has something to fix
    conn.execute("UPDATE nx_creators SET subscriber_count=99, follower_count=99, total_earnings=999, available_balance=999 WHERE email=?", (email,))
    conn.commit(); conn.close()

def test_recalc_creator_stats(db):
    _seed(db)
    res = ops.recalc_creator_stats("cr@x.com")
    assert res["subscriber_count"] == 2 and res["follower_count"] == 3
    assert abs(res["total_earnings"] - 20.0) < 0.01 and abs(res["available_balance"] - 15.0) < 0.01  # 20 - 5
    prof = ent.entity_query("CreatorProfile", {"user_email": "cr@x.com"}, None, 1)[0]
    assert prof["subscriber_count"] == 2 and abs(prof["available_balance"] - 15.0) < 0.01

def test_recalc_all(db):
    _seed(db, "a@x.com"); _seed(db, "b@x.com")
    out = ops.recalc_all()
    assert len(out) >= 2
```

- [ ] **Step 2: run → FAIL.**

- [ ] **Step 3: create `core/nexora_ops.py`**

```python
#!/usr/bin/env python3
"""core/nexora_ops.py — recompute persisted creator counters from source rows."""
from typing import Dict, List

from core.nexora_db import get_conn


def recalc_creator_stats(email: str) -> Dict:
    email = (email or "").strip().lower()
    conn = get_conn()
    sub = conn.execute("SELECT COUNT(*) n FROM nx_subscribers WHERE creator_email=? AND status='active'",
                       (email,)).fetchone()["n"]
    fol = conn.execute("SELECT COUNT(*) n FROM nx_follows WHERE creator_email=?", (email,)).fetchone()["n"]
    earn = conn.execute("SELECT COALESCE(SUM(creator_amount),0) s FROM nx_transactions WHERE to_email=?",
                        (email,)).fetchone()["s"]
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM nx_payouts WHERE creator_email=? AND status='paid'",
                        (email,)).fetchone()["s"]
    earn = round(earn, 2)
    bal = round(earn - paid, 2)
    conn.execute("UPDATE nx_creators SET subscriber_count=?, follower_count=?, total_earnings=?, available_balance=? "
                 "WHERE email=? OR user_email=?", (sub, fol, earn, bal, email, email))
    conn.commit()
    conn.close()
    return {"email": email, "subscriber_count": sub, "follower_count": fol,
            "total_earnings": earn, "available_balance": bal}


def recalc_all() -> List[Dict]:
    conn = get_conn()
    emails = [r["email"] for r in conn.execute("SELECT email FROM nx_creators")]
    conn.close()
    return [recalc_creator_stats(e) for e in emails]
```

- [ ] **Step 4: add the admin route to `core/api.py`** — after the nexoraData route (grep `grep -n "nx_fn_nexora_data" core/api.py`), insert module-level:

```python
@app.post("/api/nx/admin/recalc-stats")
async def nx_admin_recalc_stats(request: Request):
    _nx_require_admin(request)
    body = await request.json()
    from core.nexora_ops import recalc_creator_stats, recalc_all
    email = body.get("creator_email")
    if email:
        return {"ok": True, "result": recalc_creator_stats(email)}
    results = recalc_all()
    return {"ok": True, "recalculated": len(results), "results": results}
```

- [ ] **Step 5: append route test to `tests/test_nexora_ops.py`**

```python
import core.api as api
from fastapi.testclient import TestClient

def test_recalc_route_admin_only(db):
    _seed(db)
    c = TestClient(api.app)
    fan = nexora_auth.register_fan("nonadmin@x.com", "hunter2")["token"]
    assert c.post("/api/nx/admin/recalc-stats", headers={"Authorization": f"Bearer {fan}"}, json={}).status_code == 403
    nexora_auth.register_creator("adm@x.com", "hunter2", "Adm"); nexora_users.set_role("adm@x.com", "admin")
    atok = nexora_auth.login_creator("adm@x.com", "hunter2")["token"]
    r = c.post("/api/nx/admin/recalc-stats", headers={"Authorization": f"Bearer {atok}"}, json={"creator_email": "cr@x.com"})
    assert r.status_code == 200 and r.json()["result"]["subscriber_count"] == 2
```

- [ ] **Step 6: run → PASS** (`cd /Users/jhonwheeler/wt-nexora-phase1 && python3 -m pytest tests/test_nexora_ops.py -v`). Regression: `python3 -m pytest tests/test_nexora_entities.py tests/test_nexora_webhook.py -q`. Commit:

```bash
git add core/nexora_ops.py core/api.py tests/test_nexora_ops.py
git commit -m "feat(nexora): recalcCreatorStats ops endpoint (reconcile counters from source rows)"
```

## Phase 8 Done — DoD
- [ ] `recalc_creator_stats` recomputes all 4 counters from source and persists them; admin route 403s non-admins; all nexora tests green.

## Next Phase
Phase 9 — exposure + deploy (`api.wheellsverse.com` tunnel ingress, CORS, live secrets, point SPA at backend). **Operator-gated** — needs Stripe + Cloudflare credentials.
