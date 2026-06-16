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
