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


import core.api as api
from fastapi.testclient import TestClient

def _h(tok): return {"Authorization": f"Bearer {tok}"}

def test_follow_create_delete_via_route(db):
    tok = nexora_auth.register_fan("f@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/e/Follow", headers=_h(tok), json={"creator_email": "cr@x.com"})
    assert r.status_code == 200 and r.json()["fan_email"] == "f@x.com"
    fid = r.json()["id"]
    lst = c.get("/api/nx/e/Follow?fan_email=f@x.com", headers=_h(tok))
    assert lst.status_code == 200 and any(x["id"] == fid for x in lst.json())
    assert c.delete(f"/api/nx/e/Follow/{fid}", headers=_h(tok)).status_code == 200

def test_notification_route_and_read_scope(db):
    fan = nexora_auth.register_fan("n@x.com", "hunter2")["token"]
    other = nexora_auth.register_fan("o@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/e/Notification", headers=_h(fan),
               json={"user_email": "n@x.com", "type": "system", "title": "hi"})
    assert r.status_code == 200
    nid = r.json()["id"]
    assert c.get("/api/nx/e/Notification?user_email=n@x.com", headers=_h(fan)).status_code == 200
    # other user CANNOT read n's notifications
    assert c.get("/api/nx/e/Notification?user_email=n@x.com", headers=_h(other)).status_code == 403
    up = c.patch(f"/api/nx/e/Notification/{nid}", headers=_h(fan), json={"is_read": True})
    assert up.status_code == 200 and up.json()["is_read"] is True

def test_livestream_create_via_route(db):
    tok = nexora_auth.register_creator("ls@x.com", "hunter2", "LS")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/e/LiveStream", headers=_h(tok), json={"title": "Live", "access_type": "subscribers_only"})
    assert r.status_code == 200 and r.json()["creator_email"] == "ls@x.com"
    assert c.get("/api/nx/e/LiveStream?status=ended", headers=_h(tok)).status_code == 200

def test_content_purchase_create_blocked_via_route(db):
    tok = nexora_auth.register_fan("cp@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    assert c.post("/api/nx/e/ContentPurchase", headers=_h(tok), json={"amount": 5}).status_code == 403
