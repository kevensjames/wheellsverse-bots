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


from core import nexora_entities as ent
from core import nexora_auth

def test_report_create_and_admin_resolve(db):
    reporter = {"email": "r@x.com", "role": "fan"}
    admin = {"email": "a@x.com", "role": "admin"}
    rep = ent.entity_create("Report", {"reported_email": "bad@x.com", "reason": "spam", "details": "d"}, reporter)
    assert rep["reporter_email"] == "r@x.com" and rep["status"] == "open"
    assert ent.entity_update("Report", rep["id"], {"status": "resolved"}, reporter)["status"] == "open"
    assert ent.entity_update("Report", rep["id"], {"status": "resolved", "admin_notes": "ok"}, admin)["status"] == "resolved"

def test_creator_verification_flow(db):
    nexora_auth.register_creator("v@x.com", "hunter2", "V")
    creator = {"email": "v@x.com", "role": "creator"}
    admin = {"email": "ad@x.com", "role": "admin"}
    cv = ent.entity_create("CreatorVerification",
        {"legal_full_name": "Vee Person", "country": "US", "consent_confirmed": True,
         "document_front_url": "u1", "status": "approved"}, creator)
    assert cv["user_email"] == "v@x.com" and cv["status"] == "submitted" and cv["consent_confirmed"] is True
    rev = ent.entity_update("CreatorVerification", cv["id"],
        {"status": "approved", "review_notes": "ok", "reviewed_by_admin_email": "ad@x.com"}, admin)
    assert rev["status"] == "approved" and rev["reviewed_by_admin_email"] == "ad@x.com"

def test_admin_only_creates(db):
    fan = {"email": "f@x.com", "role": "fan"}
    for e in ("ModerationAction", "AuditLog"):
        with pytest.raises(PermissionError):
            ent.entity_create(e, {"action": "x"}, fan)
    admin = {"email": "a@x.com", "role": "admin"}
    al = ent.entity_create("AuditLog", {"action": "approve", "entity_type": "CreatorProfile", "entity_id": "5"}, admin)
    assert al["actor_email"] == "a@x.com" and al["action"] == "approve"
