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


from core import nexora_aggregations as agg

def test_fan_data_shapes(db):
    nexora_auth.register_fan("f@x.com", "hunter2")
    actor = {"email": "f@x.com", "role": "fan"}
    ent.entity_create("Follow", {"creator_email": "cr@x.com"}, actor)
    out = agg.fan_data(actor)
    assert out["ok"] is True and isinstance(out["creators"], list)
    assert any(f["creator_email"] == "cr@x.com" for f in out["follows"])

def test_home_feed_shapes(db):
    nexora_auth.register_fan("h@x.com", "hunter2")
    out = agg.home_feed({"email": "h@x.com", "role": "fan"})
    assert out["ok"] is True
    for k in ("creators", "posts", "follows", "subscriptions", "purchases"):
        assert isinstance(out[k], list)

def test_dashboard_data_no_profile(db):
    nexora_auth.register_creator("nd@x.com", "hunter2", "ND")  # registered but NOT onboarded
    out = agg.dashboard_data({"email": "nd@x.com", "role": "creator"})
    assert out["ok"] is True and out["profile"] is None   # user_email still '' -> not found

def test_toggle_live_sets_profile(db):
    nexora_auth.register_creator("live@x.com", "hunter2", "L")
    actor = {"email": "live@x.com", "role": "creator"}
    ent.entity_create("CreatorProfile", {"display_name": "L"}, actor)   # onboards (upsert sets user_email)
    out = agg.toggle_live(actor, True)
    assert out["ok"] is True and out["profile"]["is_live"] is True
    assert agg.toggle_live(actor, False)["profile"]["is_live"] is False
