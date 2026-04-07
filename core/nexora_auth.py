#!/usr/bin/env python3
"""
core/nexora_auth.py
─────────────────────────────────────────────────────────────────────────────
NEXORA platform — creator authentication.
  • Password hashing via SHA-256 + random salt (no extra deps)
  • Session tokens stored in nx_sessions table (30-day expiry)
  • No JWT library required — opaque tokens, DB-verified
─────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import re
import secrets
import time
from typing import Dict, Optional

from core.nexora_db import get_conn, init_db

_TOKEN_BYTES   = 32
_SESSION_DAYS  = 30
_SALT_HEX_LEN  = 32   # 16 bytes → 32 hex chars

# ── Password helpers ───────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(_SALT_HEX_LEN)
    h    = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${h}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, h = stored_hash.split("$", 1)
        return secrets.compare_digest(
            hashlib.sha256((salt + password).encode("utf-8")).hexdigest(), h
        )
    except Exception:
        return False

# ── Token helpers ──────────────────────────────────────────────────────────────

def _create_session(creator_id: int) -> str:
    token      = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = time.time() + _SESSION_DAYS * 86400
    conn = get_conn()
    # Prune expired sessions for this creator
    conn.execute(
        "DELETE FROM nx_sessions WHERE creator_id=? AND expires_at < ?",
        (creator_id, time.time())
    )
    conn.execute(
        "INSERT INTO nx_sessions (creator_id,token,expires_at,created_at) VALUES (?,?,?,?)",
        (creator_id, token, expires_at, time.time())
    )
    conn.commit()
    conn.close()
    return token

def verify_token(token: str) -> Optional[Dict]:
    """Return creator dict if token is valid, else None."""
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        """SELECT c.id, c.email, c.name, c.handle, c.bio, c.avatar,
                  c.price, c.payout_method, c.stripe_link, c.founding
           FROM nx_sessions s
           JOIN nx_creators c ON s.creator_id = c.id
           WHERE s.token = ? AND s.expires_at > ?""",
        (token, time.time())
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def revoke_token(token: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM nx_sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()

# ── Handle generator ───────────────────────────────────────────────────────────

def _unique_handle(conn, base: str) -> str:
    handle  = re.sub(r"[^a-z0-9_]", "", base.lower())[:24] or "creator"
    attempt = handle
    counter = 1
    while conn.execute("SELECT 1 FROM nx_creators WHERE handle=?", (attempt,)).fetchone():
        attempt = f"{handle}{counter}"
        counter += 1
    return attempt

# ── Public API ─────────────────────────────────────────────────────────────────

def register_creator(email: str, password: str, name: str) -> Dict:
    """
    Register a new creator.
    Returns {"token":..., "creator_id":..., "handle":...}
    or      {"error":...}
    """
    init_db()

    email = email.strip().lower()
    if not email or "@" not in email:
        return {"error": "Invalid email address"}
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters"}
    if not name.strip():
        return {"error": "Name is required"}

    conn = get_conn()
    if conn.execute("SELECT 1 FROM nx_creators WHERE email=?", (email,)).fetchone():
        conn.close()
        return {"error": "An account with that email already exists"}

    handle = _unique_handle(conn, name)
    now    = time.time()

    cur = conn.execute(
        "INSERT INTO nx_creators (email,name,handle,founding,created_at) VALUES (?,?,?,1,?)",
        (email, name.strip(), handle, now)
    )
    creator_id = cur.lastrowid
    conn.execute(
        "INSERT INTO nx_passwords (creator_id,hash) VALUES (?,?)",
        (creator_id, hash_password(password))
    )
    conn.commit()
    conn.close()

    token = _create_session(creator_id)
    return {"token": token, "creator_id": creator_id, "handle": handle, "name": name.strip()}


def login_creator(email: str, password: str) -> Dict:
    """
    Authenticate a creator.
    Returns {"token":..., "creator":...}
    or      {"error":...}
    """
    init_db()

    email = email.strip().lower()
    conn  = get_conn()
    row   = conn.execute(
        """SELECT c.id, c.active, p.hash
           FROM nx_creators c JOIN nx_passwords p ON c.id = p.creator_id
           WHERE c.email = ?""",
        (email,)
    ).fetchone()
    conn.close()

    if not row:
        return {"error": "Invalid email or password"}
    if not row["active"]:
        return {"error": "This account has been suspended"}
    if not verify_password(password, row["hash"]):
        return {"error": "Invalid email or password"}

    token   = _create_session(row["id"])
    creator = verify_token(token)
    return {"token": token, "creator": creator}


# ── Fan auth ───────────────────────────────────────────────────────────────────

def _create_fan_session(fan_email: str) -> str:
    from core.nexora_db import create_fan_session
    token      = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = time.time() + _SESSION_DAYS * 86400
    create_fan_session(fan_email, token, expires_at)
    return token


def register_fan(email: str, password: str) -> Dict:
    """
    Register a fan account (anyone can register; no creator sub required at signup).
    Returns {"token": ..., "fan_email": ...} or {"error": ...}
    """
    from core.nexora_db import get_fan_password_hash, set_fan_password, init_db
    init_db()
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"error": "Invalid email address"}
    if len(password) < 6:
        return {"error": "Password must be at least 6 characters"}
    if get_fan_password_hash(email):
        return {"error": "An account with that email already exists"}
    set_fan_password(email, hash_password(password))
    token = _create_fan_session(email)
    return {"token": token, "fan_email": email}


def login_fan(email: str, password: str) -> Dict:
    """
    Authenticate a fan.
    Returns {"token": ..., "fan_email": ..., "subscriptions": [...]} or {"error": ...}
    """
    from core.nexora_db import get_fan_password_hash, get_fan_subscriptions, init_db
    init_db()
    email = email.strip().lower()
    stored = get_fan_password_hash(email)
    if not stored or not verify_password(password, stored):
        return {"error": "Invalid email or password"}
    token = _create_fan_session(email)
    subs  = get_fan_subscriptions(email)
    return {"token": token, "fan_email": email, "subscriptions": subs}
