import pytest
from core import nexora_db, nexora_users, nexora_admin

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db

def test_seed_admin(db):
    nexora_admin.seed_admin("boss@x.com", "s3cret-pass")
    u = nexora_users.get_user("boss@x.com")
    assert u["role"] == "admin"
    # the admin can authenticate through the standard creator login (password stored)
    from core import nexora_auth
    assert nexora_auth.login_creator("boss@x.com", "s3cret-pass").get("token")

def test_seed_admin_idempotent_promote(db):
    # seeding an existing email twice keeps role admin and updates the password
    nexora_admin.seed_admin("boss@x.com", "pass-one")
    nexora_admin.seed_admin("boss@x.com", "pass-two")
    u = nexora_users.get_user("boss@x.com")
    assert u["role"] == "admin"
    from core import nexora_auth
    assert nexora_auth.login_creator("boss@x.com", "pass-two").get("token")
