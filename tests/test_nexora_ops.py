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
    row = conn.execute("SELECT id FROM nx_creators WHERE email=?", (email,)).fetchone()
    cid = row["id"]
    for i in range(2):
        conn.execute("INSERT INTO nx_subscribers (creator_id,fan_email,status,started_at,creator_email) VALUES (?,?,?,?,?)",
                     (cid, f"s{i}_{cid}@x.com", "active", now, email))
    for i in range(3):
        conn.execute("INSERT INTO nx_follows (fan_email,creator_email,created_at) VALUES (?,?,?)", (f"f{i}_{cid}@x.com", email, now))
    for i in range(2):
        conn.execute("INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,to_email,creator_amount,platform_fee) "
                     "VALUES (?,?,?,?,?,?,?,?)", (cid, 11.11, 1.11, 10.0, now, email, 10.0, 1.11))
    conn.execute("INSERT INTO nx_payouts (creator_id,amount,requested_at,creator_email,status) VALUES (?,?,?,?,?)",
                 (cid, 5.0, now, email, "paid"))
    conn.execute("UPDATE nx_creators SET subscriber_count=99, follower_count=99, total_earnings=999, available_balance=999 WHERE email=?", (email,))
    conn.commit(); conn.close()

def test_recalc_creator_stats(db):
    _seed(db)
    res = ops.recalc_creator_stats("cr@x.com")
    assert res["subscriber_count"] == 2 and res["follower_count"] == 3
    assert abs(res["total_earnings"] - 20.0) < 0.01 and abs(res["available_balance"] - 15.0) < 0.01
    prof = ent.entity_query("CreatorProfile", {"user_email": "cr@x.com"}, None, 1)[0]
    assert prof["subscriber_count"] == 2 and abs(prof["available_balance"] - 15.0) < 0.01

def test_recalc_all(db):
    _seed(db, "a@x.com"); _seed(db, "b@x.com")
    out = ops.recalc_all()
    assert len(out) >= 2

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

def test_recalc_excludes_non_succeeded_transactions(db):
    nexora_auth.register_creator("e@x.com", "hunter2", "E")
    ent.entity_create("CreatorProfile", {"display_name": "E"}, {"email": "e@x.com", "role": "creator"})
    import time as _t
    conn = db.get_conn(); now = _t.time()
    conn.execute("INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,to_email,creator_amount,platform_fee,status) "
                 "VALUES (?,?,?,?,?,?,?,?,?)", (1, 11, 1, 10, now, "e@x.com", 10.0, 1.0, "succeeded"))
    conn.execute("INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,to_email,creator_amount,platform_fee,status) "
                 "VALUES (?,?,?,?,?,?,?,?,?)", (1, 11, 1, 10, now, "e@x.com", 10.0, 1.0, "refunded"))
    conn.commit(); conn.close()
    res = ops.recalc_creator_stats("e@x.com")
    assert abs(res["total_earnings"] - 10.0) < 0.01   # only the succeeded txn counts, not the refunded

def test_recalc_case_insensitive_email(db):
    nexora_auth.register_creator("mix@x.com", "hunter2", "M")
    ent.entity_create("CreatorProfile", {"display_name": "M"}, {"email": "mix@x.com", "role": "creator"})
    import time as _t
    conn = db.get_conn()
    conn.execute("INSERT INTO nx_follows (fan_email,creator_email,created_at) VALUES (?,?,?)", ("z@x.com", "MIX@x.com", _t.time()))
    conn.commit(); conn.close()
    res = ops.recalc_creator_stats("mix@x.com")
    assert res["follower_count"] == 1   # matched despite MIX vs mix
