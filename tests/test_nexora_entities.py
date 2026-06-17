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
