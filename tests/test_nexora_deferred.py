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
    u = ent.entity_update("PlatformSettings", "platform_fee_pct", {"value": "15"}, admin)
    assert u["value"] == "15"
    rows = ent.entity_query("PlatformSettings", {"key": "platform_fee_pct"}, None, None)
    assert len(rows) == 1

def test_platform_settings_admin_only_create(db):
    with pytest.raises(PermissionError):
        ent.entity_create("PlatformSettings", {"key": "k", "value": "v"}, {"email": "f@x.com", "role": "fan"})


import core.api as api
from fastapi.testclient import TestClient

def _h(t): return {"Authorization": f"Bearer {t}"}

def test_message_create_and_auto_scoped_read(db):
    a = nexora_auth.register_fan("a@x.com", "hunter2")["token"]
    b = nexora_auth.register_fan("b@x.com", "hunter2")["token"]
    c = TestClient(api.app)
    r = c.post("/api/nx/e/Message", headers=_h(a), json={"to_email": "b@x.com", "text": "hi", "conversation_id": "a|b"})
    assert r.status_code == 200 and r.json()["from_email"] == "a@x.com"
    la = c.get("/api/nx/e/Message", headers=_h(a))
    assert la.status_code == 200 and len(la.json()) == 1 and la.json()[0]["text"] == "hi"
    lb = c.get("/api/nx/e/Message", headers=_h(b))
    assert lb.status_code == 200 and len(lb.json()) == 1
    z = nexora_auth.register_fan("z@x.com", "hunter2")["token"]
    lz = c.get("/api/nx/e/Message", headers=_h(z))
    assert lz.status_code == 200 and len(lz.json()) == 0
