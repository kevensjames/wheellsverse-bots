"""Regression tests for the 2026-06-30 production-audit fixes.

  - Unauthenticated /api/nx/subscribe forgery route removed.
  - User.is_suspended is admin-only (a banned user can't self-un-suspend).
  - stripe_id de-dup keeps the earliest row (so the UNIQUE-index migration is safe).
"""
import time
import pytest
from core import nexora_db, nexora_entities as ent
import core.api as api
from fastapi.testclient import TestClient


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db(force=True)
    return nexora_db


def test_legacy_subscribe_route_removed(db):
    # The forgery route is gone — no unauthenticated way to mint a subscription
    # or inject a fake earnings transaction.
    c = TestClient(api.app)
    r = c.post("/api/nx/subscribe", json={"creator_handle": "x", "fan_email": "f@x.com", "price_paid": 99})
    assert r.status_code in (404, 405)


def test_user_cannot_self_unsuspend(db):
    conn = nexora_db.get_conn()
    conn.execute("INSERT INTO nx_users (email,role,is_suspended,created_at) VALUES (?,?,?,?)",
                 ("banned@x.com", "fan", 1, time.time()))
    conn.commit(); conn.close()

    # The banned user owns their row, but is_suspended is NOT in their writable set.
    ent.entity_update("User", "banned@x.com", {"is_suspended": 0}, {"email": "banned@x.com", "role": "fan"})
    assert ent.entity_get("User", "banned@x.com")["is_suspended"] is True   # still suspended

    # full_name remains self-editable (legitimate).
    ent.entity_update("User", "banned@x.com", {"full_name": "Renamed"}, {"email": "banned@x.com", "role": "fan"})
    assert ent.entity_get("User", "banned@x.com")["full_name"] == "Renamed"

    # An admin CAN un-suspend.
    ent.entity_update("User", "banned@x.com", {"is_suspended": 0}, {"email": "adm@x.com", "role": "admin"})
    assert ent.entity_get("User", "banned@x.com")["is_suspended"] is False


def test_stripe_id_dedup_keeps_earliest(db):
    conn = nexora_db.get_conn()
    conn.execute("PRAGMA foreign_keys=OFF")                # dedup logic under test, not FKs
    conn.execute("DROP INDEX IF EXISTS ux_tx_stripe_id")   # allow inserting dups
    for i in range(3):
        conn.execute(
            "INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,stripe_id,status) "
            "VALUES (?,?,?,?,?,?,?)", (1, 10, 1, 9, 1000 + i, "cs_dup", "succeeded"))
    conn.execute("INSERT INTO nx_transactions (creator_id,amount,platform_cut,creator_cut,created_at,stripe_id,status) "
                 "VALUES (?,?,?,?,?,?,?)", (1, 5, 0, 5, 2000, "", "succeeded"))  # empty stripe_id untouched
    conn.commit()
    removed = nexora_db._dedupe_stripe_id(conn)
    conn.commit()
    dup_ids = [r["id"] for r in conn.execute("SELECT id FROM nx_transactions WHERE stripe_id='cs_dup' ORDER BY id")]
    empty_ct = conn.execute("SELECT COUNT(*) n FROM nx_transactions WHERE stripe_id=''").fetchone()["n"]
    conn.close()
    assert removed == 2 and len(dup_ids) == 1            # earliest survives, 2 dups removed
    assert empty_ct == 1                                  # empty stripe_id rows never touched
    # idempotent
    conn = nexora_db.get_conn(); again = nexora_db._dedupe_stripe_id(conn); conn.commit(); conn.close()
    assert again == 0
