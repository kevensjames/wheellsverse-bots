import pytest
from core import nexora_db

@pytest.fixture
def db(tmp_path, monkeypatch):
    """Redirect the SQLite file to a temp path and create the schema."""
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db


def test_init_db_creates_nx_users(db):
    conn = db.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(nx_users)")}
    conn.close()
    assert cols == {"email", "full_name", "role", "is_suspended",
                    "age_verified", "avatar_url", "created_at"}


def test_ensure_columns_is_idempotent(db):
    conn = db.get_conn()
    db._ensure_columns(conn, "nx_users", {"nickname": "nickname TEXT DEFAULT ''"})
    db._ensure_columns(conn, "nx_users", {"nickname": "nickname TEXT DEFAULT ''"})  # second call no-op
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(nx_users)")}
    conn.commit(); conn.close()
    assert "nickname" in cols


import hashlib, secrets
from core import nexora_auth


def test_bcrypt_roundtrip():
    h = nexora_auth.hash_password("hunter2")
    assert h.startswith("$2")                       # bcrypt prefix
    assert nexora_auth.verify_password("hunter2", h)
    assert not nexora_auth.verify_password("wrong", h)


def test_legacy_sha256_still_verifies():
    salt = secrets.token_hex(16)
    legacy = f"{salt}${hashlib.sha256((salt + 'hunter2').encode()).hexdigest()}"
    assert nexora_auth.verify_password("hunter2", legacy)
    assert nexora_auth.needs_rehash(legacy) is True
    assert nexora_auth.needs_rehash(nexora_auth.hash_password("x")) is False


from core import nexora_users

def test_upsert_creates_then_updates(db):
    u = nexora_users.upsert_user("A@X.com", full_name="Ann", role="creator")
    assert u == {"email": "a@x.com", "full_name": "Ann", "role": "creator",
                 "is_suspended": False, "age_verified": False, "avatar_url": ""}
    u2 = nexora_users.upsert_user("a@x.com", full_name="Annie")
    assert u2["full_name"] == "Annie" and u2["role"] == "creator"

def test_upsert_never_downgrades_admin(db):
    nexora_users.upsert_user("boss@x.com", role="admin")
    u = nexora_users.upsert_user("boss@x.com", role="creator")
    assert u["role"] == "admin"

def test_role_and_suspend_and_age(db):
    nexora_users.upsert_user("f@x.com")
    assert nexora_users.get_user("f@x.com")["role"] == "fan"
    nexora_users.set_role("f@x.com", "creator")
    nexora_users.set_suspended("f@x.com", True)
    nexora_users.set_age_verified("f@x.com")
    u = nexora_users.get_user("f@x.com")
    assert u["role"] == "creator" and u["is_suspended"] is True and u["age_verified"] is True

def test_check_access():
    admin = {"role": "admin"}; fan = {"role": "fan"}
    assert nexora_users.check_access(admin, "admin") is True
    assert nexora_users.check_access(fan, "admin") is False
    assert nexora_users.check_access(fan, "fan", "creator") is True

def test_resolve_creator_token(db):
    from core import nexora_auth
    reg = nexora_auth.register_creator("c@x.com", "hunter2", "Cee")
    u = nexora_users.resolve_user(reg["token"])
    assert u["email"] == "c@x.com" and u["role"] == "creator"

def test_resolve_fan_token(db):
    from core import nexora_auth
    reg = nexora_auth.register_fan("fan@x.com", "hunter2")
    u = nexora_users.resolve_user(reg["token"])
    assert u["email"] == "fan@x.com" and u["role"] == "fan"

def test_resolve_bad_token(db):
    assert nexora_users.resolve_user("nope") is None
    assert nexora_users.resolve_user("") is None


def test_register_creator_creates_user_row(db):
    from core import nexora_auth
    nexora_auth.register_creator("new@x.com", "hunter2", "New")
    u = nexora_users.get_user("new@x.com")
    assert u and u["role"] == "creator" and u["full_name"] == "New"

def test_login_rehashes_legacy_password(db):
    import hashlib, secrets, time as _t
    from core import nexora_auth
    # seed a creator with a LEGACY sha256 hash directly
    conn = db.get_conn()
    conn.execute("INSERT INTO nx_creators (email,name,handle,founding,created_at) "
                 "VALUES (?,?,?,1,?)", ("old@x.com", "Old", "old", _t.time()))
    cid = conn.execute("SELECT id FROM nx_creators WHERE email='old@x.com'").fetchone()["id"]
    salt = secrets.token_hex(16)
    legacy = f"{salt}${hashlib.sha256((salt + 'hunter2').encode()).hexdigest()}"
    conn.execute("INSERT INTO nx_passwords (creator_id,hash) VALUES (?,?)", (cid, legacy))
    conn.commit(); conn.close()

    res = nexora_auth.login_creator("old@x.com", "hunter2")
    assert "token" in res
    conn = db.get_conn()
    new_hash = conn.execute("SELECT hash FROM nx_passwords WHERE creator_id=?", (cid,)).fetchone()["hash"]
    conn.close()
    assert new_hash.startswith("$2")          # upgraded to bcrypt on login
