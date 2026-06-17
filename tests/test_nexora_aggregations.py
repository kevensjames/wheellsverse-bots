import pytest
from core import nexora_db, nexora_auth, nexora_entities as ent

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def test_creatorprofile_create_upserts_existing_row(db):
    # a registered creator already has an nx_creators row (user_email='')
    nexora_auth.register_creator("c@x.com", "hunter2", "Cee")
    actor = {"email": "c@x.com", "role": "creator"}
    conn = db.get_conn()
    before = conn.execute("SELECT COUNT(*) n FROM nx_creators WHERE email='c@x.com'").fetchone()["n"]
    conn.close()
    fe = ent.entity_create("CreatorProfile", {"display_name": "Cee", "bio": "hi"}, actor)
    conn = db.get_conn()
    after = conn.execute("SELECT COUNT(*) n FROM nx_creators WHERE email='c@x.com'").fetchone()["n"]
    conn.close()
    assert before == 1 and after == 1            # UPDATED, not duplicated
    assert fe["user_email"] == "c@x.com" and fe["display_name"] == "Cee" and fe["bio"] == "hi"
    # now findable as a CreatorProfile by user_email (onboarded)
    found = ent.entity_query("CreatorProfile", {"user_email": "c@x.com"}, None, 1)
    assert len(found) == 1
