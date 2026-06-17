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

def test_additive_columns_present(db):
    assert {"user_email","display_name","category","cover_url","social_links","status",
            "verification_status","total_earnings","available_balance","subscriber_count",
            "follower_count","is_live"} <= _cols(db, "nx_creators")
    assert {"creator_email","creator_profile_id","text","access_type","ppv_price",
            "media_type","status","like_count","comment_count"} <= _cols(db, "nx_posts")
    assert {"creator_email","creator_profile_id","amount","expires_at"} <= _cols(db, "nx_subscribers")
    assert {"from_email","to_email","creator_amount","platform_fee","description"} <= _cols(db, "nx_transactions")
    assert {"creator_email","payout_method","admin_notes"} <= _cols(db, "nx_payouts")

from core import nexora_entities as ent

def _mk_creator(email, name="C"):
    from core import nexora_auth
    nexora_auth.register_creator(email, "hunter2", name)

def test_registry_and_mapping_roundtrip(db):
    cols = ent._from_fe("CreatorProfile", {"display_name": "Ann", "bio": "hi", "id": 7, "status": "approved"})
    assert cols == {"display_name": "Ann", "bio": "hi"}  # id + status not writable
    cols2 = ent._from_fe("CreatorProfile", {"social_links": {"twitter": "@a"}})
    assert cols2["social_links"] == '{"twitter": "@a"}'

def test_to_fe_types(db):
    conn = db.get_conn()
    conn.execute("INSERT INTO nx_creators (email,name,handle,created_at,user_email,display_name,"
                 "social_links,is_live,total_earnings) VALUES (?,?,?,?,?,?,?,?,?)",
                 ("c@x.com","C","cee",1700000000.0,"c@x.com","Cee",'{"x":1}',1,12.5))
    row = conn.execute("SELECT * FROM nx_creators WHERE email='c@x.com'").fetchone()
    conn.close()
    fe = ent._to_fe("CreatorProfile", row)
    assert fe["user_email"] == "c@x.com" and fe["display_name"] == "Cee"
    assert fe["social_links"] == {"x": 1}
    assert fe["is_live"] is True
    assert isinstance(fe["created_date"], str) and fe["created_date"].endswith("Z")

def test_entity_query_filter_sort_limit(db):
    conn = db.get_conn()
    for i, st in enumerate(["approved", "pending", "approved"]):
        conn.execute("INSERT INTO nx_creators (email,name,handle,created_at,user_email,status) "
                     "VALUES (?,?,?,?,?,?)", (f"c{i}@x.com", f"C{i}", f"c{i}", 1700000000.0+i, f"c{i}@x.com", st))
    conn.commit(); conn.close()
    out = ent.entity_query("CreatorProfile", {"status": "approved"}, "-created_date", 10)
    assert len(out) == 2 and all(c["status"] == "approved" for c in out)
    assert out[0]["created_date"] >= out[1]["created_date"]  # desc

def test_entity_get(db):
    conn = db.get_conn()
    conn.execute("INSERT INTO nx_creators (email,name,handle,created_at,user_email) VALUES (?,?,?,?,?)",
                 ("g@x.com","G","g",1700000000.0,"g@x.com"))
    cid = conn.execute("SELECT id FROM nx_creators WHERE email='g@x.com'").fetchone()["id"]
    conn.commit(); conn.close()
    fe = ent.entity_get("CreatorProfile", cid)
    assert fe["user_email"] == "g@x.com"
    assert ent.entity_get("CreatorProfile", 99999) is None


def test_entity_create_stamps_owner(db):
    _mk_creator("creator@x.com")
    actor = {"email": "creator@x.com", "role": "creator"}
    fe = ent.entity_create("Post", {"title": "Hi", "text": "yo", "access_type": "free"}, actor)
    assert fe["title"] == "Hi" and fe["creator_email"] == "creator@x.com"
    assert fe["id"] and fe["created_date"]
    assert isinstance(fe["creator_profile_id"], int) and fe["creator_profile_id"] > 0
    assert fe["creator_email"] == "creator@x.com"


def test_entity_update_owner_only(db):
    _mk_creator("o@x.com")
    owner = {"email": "o@x.com", "role": "creator"}
    other = {"email": "x@x.com", "role": "creator"}
    admin = {"email": "a@x.com", "role": "admin"}
    fe = ent.entity_create("Post", {"title": "P"}, owner)
    with pytest.raises(PermissionError):
        ent.entity_update("Post", fe["id"], {"title": "hax"}, other)
    upd = ent.entity_update("Post", fe["id"], {"title": "P2"}, owner)
    assert upd["title"] == "P2"
    upd2 = ent.entity_update("Post", fe["id"], {"status": "removed"}, admin)
    assert upd2["status"] == "removed"


def test_entity_delete_owner_only(db):
    _mk_creator("d@x.com")
    owner = {"email": "d@x.com", "role": "creator"}
    fe = ent.entity_create("Post", {"title": "D"}, owner)
    with pytest.raises(PermissionError):
        ent.entity_delete("Post", fe["id"], {"email": "z@x.com", "role": "fan"})
    ent.entity_delete("Post", fe["id"], owner)
    assert ent.entity_get("Post", fe["id"]) is None


def test_entity_create_role_enforced(db):
    # Post create_roles excludes 'fan'
    with pytest.raises(PermissionError):
        ent.entity_create("Post", {"title": "X"}, {"email": "f@x.com", "role": "fan"})
