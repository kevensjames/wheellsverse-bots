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
