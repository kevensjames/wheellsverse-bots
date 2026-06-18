import pytest
from core import nexora_db

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def _cols(db, t):
    conn = db.get_conn()
    c = {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}
    conn.close(); return c

def test_phase7_tables(db):
    assert {"id","reporter_email","reported_email","reason","details","status","admin_notes","created_at"} <= _cols(db, "nx_reports")
    assert {"id","admin_email","target_user_email","action_type","reason","notes","related_report_id","created_at"} <= _cols(db, "nx_moderation_actions")
    assert {"id","actor_email","action","entity_type","entity_id","details","created_at"} <= _cols(db, "nx_audit_logs")
    assert {"id","user_email","legal_full_name","date_of_birth","country","document_type","document_front_url",
            "document_back_url","selfie_url","consent_confirmed","status","reviewed_at",
            "reviewed_by_admin_email","review_notes","created_at"} <= _cols(db, "nx_creator_verifications")
