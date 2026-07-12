#!/usr/bin/env python3
"""
core/nexora_db.py
─────────────────────────────────────────────────────────────────────────────
NEXORA platform — SQLite database layer.
Tables: creators, sessions, passwords, posts, subscribers,
        transactions, payouts, messages
─────────────────────────────────────────────────────────────────────────────
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).parent.parent

# Use /var/data/nexora.db when running on Railway (mounted persistent volume).
# Fall back to local data/ directory for development.
_RAILWAY_VOL = Path("/var/data")
if _RAILWAY_VOL.exists() or os.environ.get("RAILWAY_ENVIRONMENT"):
    DB_PATH = _RAILWAY_VOL / "nexora.db"
else:
    DB_PATH = ROOT / "data" / "nexora.db"

# ── Connection ─────────────────────────────────────────────────────────────────


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_columns(conn, table: str, cols: dict) -> None:
    """Idempotently ADD COLUMN for any name in `cols` missing from `table`.
    `cols` maps column-name -> full column DDL fragment."""
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in cols.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

# ── Schema ─────────────────────────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS nx_creators (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    UNIQUE NOT NULL,
    name            TEXT    NOT NULL,
    handle          TEXT    UNIQUE NOT NULL,
    bio             TEXT    DEFAULT '',
    avatar          TEXT    DEFAULT '',
    price           REAL    DEFAULT 9.99,
    payout_method   TEXT    DEFAULT 'bank',
    stripe_link     TEXT    DEFAULT '',
    founding        INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1,
    created_at      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_passwords (
    creator_id  INTEGER PRIMARY KEY,
    hash        TEXT    NOT NULL,
    FOREIGN KEY (creator_id) REFERENCES nx_creators(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nx_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL,
    token       TEXT    UNIQUE NOT NULL,
    expires_at  REAL    NOT NULL,
    created_at  REAL    NOT NULL,
    FOREIGN KEY (creator_id) REFERENCES nx_creators(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nx_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL,
    title       TEXT    DEFAULT '',
    body        TEXT    DEFAULT '',
    access      TEXT    DEFAULT 'subscribers',
    media_urls  TEXT    DEFAULT '[]',
    created_at  REAL    NOT NULL,
    FOREIGN KEY (creator_id) REFERENCES nx_creators(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nx_subscribers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id      INTEGER NOT NULL,
    fan_email       TEXT    NOT NULL,
    fan_name        TEXT    DEFAULT '',
    status          TEXT    DEFAULT 'active',
    stripe_cust     TEXT    DEFAULT '',
    price_paid      REAL    DEFAULT 0,
    started_at      REAL    NOT NULL,
    cancelled_at    REAL,
    FOREIGN KEY (creator_id) REFERENCES nx_creators(id) ON DELETE CASCADE,
    UNIQUE (creator_id, fan_email)
);

CREATE TABLE IF NOT EXISTS nx_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id      INTEGER NOT NULL,
    fan_email       TEXT    DEFAULT '',
    amount          REAL    NOT NULL,
    platform_cut    REAL    NOT NULL,
    creator_cut     REAL    NOT NULL,
    type            TEXT    DEFAULT 'subscription',
    stripe_id       TEXT    DEFAULT '',
    status          TEXT    DEFAULT 'succeeded',
    created_at      REAL    NOT NULL,
    FOREIGN KEY (creator_id) REFERENCES nx_creators(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nx_payouts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id      INTEGER NOT NULL,
    amount          REAL    NOT NULL,
    method          TEXT    DEFAULT 'bank',
    status          TEXT    DEFAULT 'requested',
    requested_at    REAL    NOT NULL,
    completed_at    REAL,
    notes           TEXT    DEFAULT '',
    FOREIGN KEY (creator_id) REFERENCES nx_creators(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nx_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL,
    fan_email   TEXT    NOT NULL,
    sender      TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    read        INTEGER DEFAULT 0,
    created_at  REAL    NOT NULL,
    FOREIGN KEY (creator_id) REFERENCES nx_creators(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nx_fan_passwords (
    fan_email   TEXT    PRIMARY KEY,
    hash        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_fan_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fan_email   TEXT    NOT NULL,
    token       TEXT    UNIQUE NOT NULL,
    expires_at  REAL    NOT NULL,
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS nx_users (
    email         TEXT    PRIMARY KEY,
    full_name     TEXT    DEFAULT '',
    role          TEXT    DEFAULT 'fan',
    is_suspended  INTEGER DEFAULT 0,
    age_verified  INTEGER DEFAULT 0,
    avatar_url    TEXT    DEFAULT '',
    created_at    REAL    NOT NULL
);

-- Idempotency ledger for Stripe webhook events. A verified event is recorded
-- here BEFORE its side-effects run; a replay of the same event id is a no-op.
CREATE TABLE IF NOT EXISTS nx_processed_events (
    event_id      TEXT    PRIMARY KEY,
    processed_at  REAL    NOT NULL
);
"""


def init_db() -> None:
    conn = get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()

# ── Creators ───────────────────────────────────────────────────────────────────


def get_creator_by_id(creator_id: int) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT id,email,name,handle,bio,avatar,price,payout_method,stripe_link,founding,active,created_at "
        "FROM nx_creators WHERE id=?", (creator_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_creator_by_handle(handle: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT id,email,name,handle,bio,avatar,price,payout_method,stripe_link,founding,active,created_at "
        "FROM nx_creators WHERE handle=? AND active=1", (handle,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_creator_by_email(email: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT id,email,name,handle,bio,avatar,price,payout_method,stripe_link,founding,active,created_at "
        "FROM nx_creators WHERE email=?", (email,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_creator_profile(creator_id: int, fields: Dict) -> bool:
    allowed = {"name", "bio", "avatar", "price", "payout_method", "stripe_link"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return False
    sets = ", ".join(f"{k}=?" for k in safe)
    vals = list(safe.values()) + [creator_id]
    conn = get_conn()
    conn.execute(f"UPDATE nx_creators SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()
    return True

# ── Posts ──────────────────────────────────────────────────────────────────────


def create_post(creator_id: int, title: str, body: str,
                access: str = "subscribers", media_urls: List[str] = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO nx_posts (creator_id,title,body,access,media_urls,created_at) VALUES (?,?,?,?,?,?)",
        (creator_id, title, body, access, json.dumps(media_urls or []), time.time())
    )
    post_id = cur.lastrowid
    conn.commit()
    conn.close()
    return post_id


def list_posts(creator_id: int, limit: int = 50) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM nx_posts WHERE creator_id=? ORDER BY created_at DESC LIMIT ?",
        (creator_id, limit)
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["media_urls"] = json.loads(d.get("media_urls") or "[]")
        except Exception:
            d["media_urls"] = []
        out.append(d)
    return out


def delete_post(post_id: int, creator_id: int) -> bool:
    conn = get_conn()
    conn.execute("DELETE FROM nx_posts WHERE id=? AND creator_id=?", (post_id, creator_id))
    conn.commit()
    conn.close()
    return True

# ── Subscribers ────────────────────────────────────────────────────────────────


def add_subscriber(creator_id: int, fan_email: str, fan_name: str = "",
                   price_paid: float = 0, stripe_cust: str = "") -> Dict:
    conn = get_conn()
    now = time.time()
    conn.execute(
        """INSERT INTO nx_subscribers (creator_id,fan_email,fan_name,price_paid,stripe_cust,started_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(creator_id,fan_email) DO UPDATE SET
             status='active', price_paid=excluded.price_paid,
             stripe_cust=excluded.stripe_cust, cancelled_at=NULL""",
        (creator_id, fan_email, fan_name, price_paid, stripe_cust, now)
    )
    conn.commit()
    conn.close()
    return {"creator_id": creator_id, "fan_email": fan_email, "status": "active"}


def list_subscribers(creator_id: int) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM nx_subscribers WHERE creator_id=? ORDER BY started_at DESC",
        (creator_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_subscriber_count(creator_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM nx_subscribers WHERE creator_id=? AND status='active'",
        (creator_id,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def cancel_subscriber(creator_id: int, fan_email: str) -> bool:
    conn = get_conn()
    conn.execute(
        "UPDATE nx_subscribers SET status='cancelled', cancelled_at=? WHERE creator_id=? AND fan_email=?",
        (time.time(), creator_id, fan_email)
    )
    conn.commit()
    conn.close()
    return True

# ── Transactions ───────────────────────────────────────────────────────────────


def record_transaction(creator_id: int, amount: float, tx_type: str = "subscription",
                       fan_email: str = "", stripe_id: str = "", status: str = "succeeded") -> int:
    platform_cut = round(amount * 0.10, 4)
    creator_cut = round(amount * 0.90, 4)
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO nx_transactions
           (creator_id,fan_email,amount,platform_cut,creator_cut,type,stripe_id,status,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (creator_id, fan_email, amount, platform_cut, creator_cut,
         tx_type, stripe_id, status, time.time())
    )
    tx_id = cur.lastrowid
    conn.commit()
    conn.close()
    return tx_id


def get_earnings(creator_id: int) -> Dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM nx_transactions WHERE creator_id=? AND status='succeeded' ORDER BY created_at DESC",
        (creator_id,)
    ).fetchall()
    conn.close()
    txs = [dict(r) for r in rows]
    now = time.time()
    month_start = now - 30 * 86400
    total = sum(t["creator_cut"] for t in txs)
    this_month = sum(t["creator_cut"] for t in txs if t["created_at"] >= month_start)
    by_type: Dict[str, float] = {}
    for t in txs:
        by_type[t["type"]] = round(by_type.get(t["type"], 0) + t["creator_cut"], 2)
    return {
        "total": round(total, 2),
        "this_month": round(this_month, 2),
        "by_type": by_type,
        "transactions": txs[:50],
    }

# ── Payouts ────────────────────────────────────────────────────────────────────


def request_payout(creator_id: int, amount: float, method: str = "bank") -> Dict:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO nx_payouts (creator_id,amount,method,requested_at) VALUES (?,?,?,?)",
        (creator_id, amount, method, time.time())
    )
    payout_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": payout_id, "amount": amount, "method": method, "status": "requested"}


def list_payouts(creator_id: int) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM nx_payouts WHERE creator_id=? ORDER BY requested_at DESC",
        (creator_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_payout_amount(creator_id: int) -> float:
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM nx_payouts WHERE creator_id=? AND status='requested'",
        (creator_id,)
    ).fetchone()
    conn.close()
    return round(row["total"] if row else 0, 2)


def get_reserved_payout_amount(creator_id: int) -> float:
    """Total earnings already claimed by payouts that have NOT been rejected/failed.
    Requested, processing, and completed payouts all reserve balance, so a creator
    can never withdraw the same dollar twice. Only explicitly rejected/failed/cancelled
    payouts release their reservation."""
    conn = get_conn()
    row = conn.execute(
        """SELECT COALESCE(SUM(amount),0) AS total FROM nx_payouts
           WHERE creator_id=? AND status NOT IN ('rejected','failed','cancelled')""",
        (creator_id,)
    ).fetchone()
    conn.close()
    return round(row["total"] if row else 0, 2)


def add_pending_subscriber(creator_id: int, fan_email: str, fan_name: str = "") -> Dict:
    """Record an unpaid subscription INTENT. Never grants paid access and never
    activates an existing subscriber — only a signature-verified Stripe webhook
    (via add_subscriber) may set status='active'. Existing rows are left untouched."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO nx_subscribers (creator_id,fan_email,fan_name,status,price_paid,started_at)
           VALUES (?,?,?,'pending',0,?)
           ON CONFLICT(creator_id,fan_email) DO NOTHING""",
        (creator_id, fan_email, fan_name, time.time())
    )
    conn.commit()
    conn.close()
    return {"creator_id": creator_id, "fan_email": fan_email, "status": "pending"}


def event_already_processed(event_id: str) -> bool:
    """True if this Stripe event id has already been handled (idempotency guard)."""
    if not event_id:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM nx_processed_events WHERE event_id=?", (event_id,)
    ).fetchone()
    conn.close()
    return bool(row)


def mark_event_processed(event_id: str) -> bool:
    """Record a Stripe event id as handled. Returns False if it was already present
    (i.e. a concurrent/duplicate delivery lost the race), True if freshly inserted."""
    if not event_id:
        return True
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO nx_processed_events (event_id,processed_at) VALUES (?,?)",
            (event_id, time.time())
        )
        conn.commit()
        inserted = True
    except sqlite3.IntegrityError:
        inserted = False
    finally:
        conn.close()
    return inserted

# ── Messages ───────────────────────────────────────────────────────────────────


def send_message(creator_id: int, fan_email: str, sender: str, body: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO nx_messages (creator_id,fan_email,sender,body,created_at) VALUES (?,?,?,?,?)",
        (creator_id, fan_email, sender, body, time.time())
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def list_messages(creator_id: int, fan_email: str = "") -> List[Dict]:
    conn = get_conn()
    if fan_email:
        rows = conn.execute(
            "SELECT * FROM nx_messages WHERE creator_id=? AND fan_email=? ORDER BY created_at",
            (creator_id, fan_email)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM nx_messages WHERE creator_id=? ORDER BY created_at DESC LIMIT 100",
            (creator_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_messages_read(creator_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE nx_messages SET read=1 WHERE creator_id=?", (creator_id,))
    conn.commit()
    conn.close()


def unread_message_count(creator_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM nx_messages WHERE creator_id=? AND read=0 AND sender='fan'",
        (creator_id,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0

# ── Stats summary ──────────────────────────────────────────────────────────────


def get_creator_stats(creator_id: int) -> Dict:
    earnings = get_earnings(creator_id)
    sub_count = get_active_subscriber_count(creator_id)
    post_count = len(list_posts(creator_id, limit=9999))
    pending_pay = get_pending_payout_amount(creator_id)
    unread_msgs = unread_message_count(creator_id)
    mrr = round(sub_count * (get_creator_by_id(creator_id) or {}).get("price", 9.99), 2)
    return {
        "subscribers": sub_count,
        "posts": post_count,
        "earnings_total": earnings["total"],
        "earnings_month": earnings["this_month"],
        "earnings_type": earnings["by_type"],
        "pending_payout": pending_pay,
        "mrr": mrr,
        "unread_messages": unread_msgs,
    }

# ── Fan auth ───────────────────────────────────────────────────────────────────


def get_fan_password_hash(fan_email: str) -> Optional[str]:
    conn = get_conn()
    row = conn.execute("SELECT hash FROM nx_fan_passwords WHERE fan_email=?", (fan_email,)).fetchone()
    conn.close()
    return row["hash"] if row else None


def set_fan_password(fan_email: str, hash_: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO nx_fan_passwords (fan_email,hash) VALUES (?,?) "
        "ON CONFLICT(fan_email) DO UPDATE SET hash=excluded.hash",
        (fan_email, hash_)
    )
    conn.commit()
    conn.close()


def create_fan_session(fan_email: str, token: str, expires_at: float) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM nx_fan_sessions WHERE fan_email=? AND expires_at < ?", (fan_email, time.time()))
    conn.execute(
        "INSERT INTO nx_fan_sessions (fan_email,token,expires_at,created_at) VALUES (?,?,?,?)",
        (fan_email, token, expires_at, time.time())
    )
    conn.commit()
    conn.close()


def verify_fan_token(token: str) -> Optional[str]:
    """Return fan_email if token valid, else None."""
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT fan_email FROM nx_fan_sessions WHERE token=? AND expires_at > ?",
        (token, time.time())
    ).fetchone()
    conn.close()
    return row["fan_email"] if row else None


def revoke_fan_token(token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM nx_fan_sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


def get_fan_subscriptions(fan_email: str) -> List[Dict]:
    """All active subscriptions for a fan across all creators."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.creator_id, s.price_paid, s.started_at, s.status,
                  c.name, c.handle, c.bio, c.avatar
           FROM nx_subscribers s JOIN nx_creators c ON s.creator_id = c.id
           WHERE s.fan_email=? AND s.status='active'""",
        (fan_email,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
