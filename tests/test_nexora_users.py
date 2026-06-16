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
