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
