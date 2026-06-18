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
