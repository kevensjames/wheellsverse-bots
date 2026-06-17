import pytest
import core.api as api
from core import nexora_db, nexora_auth, nexora_users
from fastapi.testclient import TestClient

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _h(tok):
    return {"Authorization": f"Bearer {tok}"}

def test_post_crud_and_ownership(db):
    tok = nexora_auth.register_creator("c@x.com", "hunter2", "Cee")["token"]
    client = TestClient(api.app)
    assert client.get("/api/nx/e/Post").status_code == 401            # unauth
    assert client.get("/api/nx/e/Nope", headers=_h(tok)).status_code == 404  # unknown
    r = client.post("/api/nx/e/Post", headers=_h(tok), json={"title": "Hi", "access_type": "free"})
    assert r.status_code == 200 and r.json()["creator_email"] == "c@x.com"
    pid = r.json()["id"]
    lst = client.get("/api/nx/e/Post?creator_email=c@x.com", headers=_h(tok))
    assert lst.status_code == 200 and any(p["id"] == pid for p in lst.json())
    up = client.patch(f"/api/nx/e/Post/{pid}", headers=_h(tok), json={"title": "Hi2"})
    assert up.status_code == 200 and up.json()["title"] == "Hi2"
    # non-owner update -> 403
    other = nexora_auth.register_creator("o@x.com", "hunter2", "Oh")["token"]
    assert client.patch(f"/api/nx/e/Post/{pid}", headers=_h(other), json={"title": "hax"}).status_code == 403
    assert client.delete(f"/api/nx/e/Post/{pid}", headers=_h(tok)).status_code == 200

def test_read_scoping_non_public(db):
    # Two fans with their own subscription rows (seed directly)
    a = nexora_auth.register_fan("a@x.com", "hunter2")["token"]
    nexora_auth.register_fan("b@x.com", "hunter2")
    # Create a real creator so the FK on creator_id is satisfied
    cr = nexora_auth.register_creator("cr@x.com", "hunter2", "Creator")
    creator_id = cr["creator_id"]
    conn = db.get_conn()
    import time as _t
    for fan in ("a@x.com", "b@x.com"):
        conn.execute("INSERT INTO nx_subscribers (creator_id,fan_email,started_at,status,creator_email) "
                     "VALUES (?,?,?,?,?)", (creator_id, fan, _t.time(), "active", "cr@x.com"))
    conn.commit(); conn.close()
    client = TestClient(api.app)
    # fan A scoping to self -> only A's row
    r = client.get("/api/nx/e/Subscription?fan_email=a@x.com", headers=_h(a))
    assert r.status_code == 200 and all(s["fan_email"] == "a@x.com" for s in r.json())
    # fan A trying to read B's rows -> 403 (self_col value != actor email)
    assert client.get("/api/nx/e/Subscription?fan_email=b@x.com", headers=_h(a)).status_code == 403
    # fan A with NO self scoping -> 403
    assert client.get("/api/nx/e/Subscription", headers=_h(a)).status_code == 403

def test_admin_reads_all_non_public(db):
    nexora_auth.register_creator("adm@x.com", "hunter2", "Adm")
    nexora_users.set_role("adm@x.com", "admin")
    tok = nexora_auth.login_creator("adm@x.com", "hunter2")["token"]
    conn = db.get_conn(); import time as _t
    conn.execute("INSERT INTO nx_subscribers (creator_id,fan_email,started_at,status) VALUES (?,?,?,?)",
                 (1, "z@x.com", _t.time(), "active"))
    conn.commit(); conn.close()
    client = TestClient(api.app)
    # admin needs no self scoping
    r = client.get("/api/nx/e/Subscription", headers=_h(tok))
    assert r.status_code == 200 and len(r.json()) >= 1
