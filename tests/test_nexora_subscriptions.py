"""Phase B Steps 2 & 3 — subscription renewal (UPSERT) + expiry sweep.

Step 2: the webhook subscription branch was a raw INSERT into nx_subscribers
(UNIQUE(creator_id,fan_email)); a repeat purchase with a new stripe_id 500s.
It is now an UPSERT that EXTENDS expires_at = MAX(existing, now) + 30d.

Step 3: nx_subscribers.expires_at was written but never read — subs were
perpetual. expire_subscriptions() sweeps active+expired rows to status='expired'
then recalc drops them from subscriber_count (recalc counts status='active').
"""
import time
import pytest
from core import nexora_db, nexora_auth, nexora_users, nexora_entities as ent
from core import nexora_payments as pay
from core import nexora_subscriptions as subs
import core.api as api
from fastapi.testclient import TestClient

DAY = 86400


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(nexora_db, "DB_PATH", tmp_path / "nexora.db")
    nexora_db.init_db()
    return nexora_db


def _creator(email="cr@x.com"):
    nexora_auth.register_creator(email, "hunter2", "Cr")
    ent.entity_create("CreatorProfile", {"display_name": "Cr"}, {"email": email, "role": "creator"})
    conn = nexora_db.get_conn()
    cid = conn.execute("SELECT id FROM nx_creators WHERE email=?", (email,)).fetchone()["id"]
    conn.close()
    return cid


def _sub_event(stripe_id, creator_email, fan_email="f@x.com", amount_total=1000):
    return {"type": "checkout.session.completed",
            "data": {"object": {"id": stripe_id, "amount_total": amount_total,
                                "metadata": {"type": "subscription", "fan_email": fan_email,
                                             "creator_email": creator_email}}}}


def _seed_sub(cid, email, fan_email, status, expires_at):
    conn = nexora_db.get_conn()
    conn.execute("INSERT INTO nx_subscribers (creator_id,fan_email,status,started_at,creator_email,expires_at) "
                 "VALUES (?,?,?,?,?,?)", (cid, fan_email, status, time.time(), email, expires_at))
    conn.commit(); conn.close()


# ── Step 2: renewal ─────────────────────────────────────────────────────────────

def test_renewal_extends_expires_at_not_duplicate(db):
    _creator("ren@x.com")
    pay.handle_stripe_event(_sub_event("cs_r1", "ren@x.com"))
    conn = nexora_db.get_conn()
    e1 = conn.execute("SELECT expires_at FROM nx_subscribers WHERE fan_email='f@x.com'").fetchone()["expires_at"]
    conn.close()
    pay.handle_stripe_event(_sub_event("cs_r2", "ren@x.com"))   # different stripe id -> real renewal
    conn = nexora_db.get_conn()
    rows = conn.execute("SELECT * FROM nx_subscribers WHERE fan_email='f@x.com'").fetchall()
    conn.close()
    assert len(rows) == 1                               # UNIQUE held, no duplicate, no 500
    assert rows[0]["status"] == "active"
    assert rows[0]["expires_at"] > e1 + 29 * DAY        # stacked ~30d onto the existing future expiry
    txns = ent.entity_query("Transaction", {"to_email": "ren@x.com"}, None, None)
    assert len(txns) == 2                               # one transaction per payment


def test_renewal_of_expired_sub_restarts_from_now(db):
    cid = _creator("exp@x.com")
    _seed_sub(cid, "exp@x.com", "f@x.com", "expired", time.time() - 5 * DAY)
    t0 = time.time()
    pay.handle_stripe_event(_sub_event("cs_x1", "exp@x.com"))
    conn = nexora_db.get_conn()
    rows = conn.execute("SELECT * FROM nx_subscribers WHERE fan_email='f@x.com'").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0]["status"] == "active"
    # restart from now (now+30d), NOT stale-stack (which would be now-5d+30d = now+25d)
    assert abs(rows[0]["expires_at"] - (t0 + 30 * DAY)) < 2 * DAY


# ── Step 3: expiry sweep ─────────────────────────────────────────────────────────

def test_expire_sweep_flips_expired_active_to_expired(db):
    cid = _creator("sw@x.com")
    _seed_sub(cid, "sw@x.com", "past@x.com", "active", time.time() - 1)
    _seed_sub(cid, "sw@x.com", "future@x.com", "active", time.time() + 10 * DAY)
    out = subs.expire_subscriptions()
    assert out["expired_count"] == 1
    conn = nexora_db.get_conn()
    statuses = {r["fan_email"]: r["status"] for r in
                conn.execute("SELECT fan_email,status FROM nx_subscribers WHERE creator_id=?", (cid,))}
    conn.close()
    assert statuses["past@x.com"] == "expired" and statuses["future@x.com"] == "active"


def test_expire_sweep_is_idempotent(db):
    cid = _creator("id@x.com")
    _seed_sub(cid, "id@x.com", "p@x.com", "active", time.time() - 1)
    assert subs.expire_subscriptions()["expired_count"] == 1
    assert subs.expire_subscriptions()["expired_count"] == 0     # nothing left active+expired


def test_null_expires_at_never_expires(db):
    cid = _creator("nl@x.com")
    _seed_sub(cid, "nl@x.com", "legacy@x.com", "active", None)
    assert subs.expire_subscriptions()["expired_count"] == 0     # NULL = never-expire (no mass-expiry)
    conn = nexora_db.get_conn()
    s = conn.execute("SELECT status FROM nx_subscribers WHERE fan_email='legacy@x.com'").fetchone()["status"]
    conn.close()
    assert s == "active"


def test_grace_period_keeps_recently_expired_active(db):
    cid = _creator("gr@x.com")
    _seed_sub(cid, "gr@x.com", "r@x.com", "active", time.time() - 1 * DAY)
    assert subs.expire_subscriptions(grace_secs=3 * DAY)["expired_count"] == 0   # within grace
    assert subs.expire_subscriptions(grace_secs=0)["expired_count"] == 1          # no grace


def test_expire_sweep_recalcs_subscriber_count(db):
    cid = _creator("rc@x.com")
    _seed_sub(cid, "rc@x.com", "a@x.com", "active", time.time() + 10 * DAY)
    _seed_sub(cid, "rc@x.com", "b@x.com", "active", time.time() - 1)
    subs.sweep_and_recalc()
    prof = ent.entity_query("CreatorProfile", {"user_email": "rc@x.com"}, None, 1)[0]
    assert prof["subscriber_count"] == 1     # only the still-active sub counts


def test_renewal_resurrects_cancelled_sub(db):
    # Refund cancels a sub (status='cancelled'); a later re-subscribe must reactivate
    # the SAME row (UPSERT sets active, clears cancelled_at, restarts expiry) — no duplicate.
    cid = _creator("res@x.com")
    conn = nexora_db.get_conn()
    conn.execute("INSERT INTO nx_subscribers (creator_id,fan_email,status,started_at,creator_email,"
                 "expires_at,cancelled_at) VALUES (?,?,?,?,?,?,?)",
                 (cid, "f@x.com", "cancelled", time.time() - 10 * DAY, "res@x.com",
                  time.time() - 5 * DAY, time.time() - 5 * DAY))
    conn.commit(); conn.close()
    t0 = time.time()
    pay.handle_stripe_event(_sub_event("cs_res", "res@x.com"))
    conn = nexora_db.get_conn()
    rows = conn.execute("SELECT * FROM nx_subscribers WHERE fan_email='f@x.com'").fetchall()
    conn.close()
    assert len(rows) == 1                              # reactivated, not duplicated
    assert rows[0]["status"] == "active" and rows[0]["cancelled_at"] is None
    assert abs(rows[0]["expires_at"] - (t0 + 30 * DAY)) < 2 * DAY
    subs.sweep_and_recalc()
    prof = ent.entity_query("CreatorProfile", {"user_email": "res@x.com"}, None, 1)[0]
    assert prof["subscriber_count"] == 1


def test_expire_endpoint_admin_only(db):
    _creator("ep@x.com")
    c = TestClient(api.app)
    fan = nexora_auth.register_fan("nonadmin@x.com", "hunter2")["token"]
    assert c.post("/api/nx/admin/expire-subscriptions",
                  headers={"Authorization": f"Bearer {fan}"}, json={}).status_code == 403
    nexora_auth.register_creator("adm@x.com", "hunter2", "Adm"); nexora_users.set_role("adm@x.com", "admin")
    atok = nexora_auth.login_creator("adm@x.com", "hunter2")["token"]
    r = c.post("/api/nx/admin/expire-subscriptions",
               headers={"Authorization": f"Bearer {atok}"}, json={})
    assert r.status_code == 200 and r.json()["ok"] is True and "expired" in r.json()
