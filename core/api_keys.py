#!/usr/bin/env python3
"""
core/api_keys.py
─────────────────────────────────────────────────────────────────────────────
Public API key management for the /v1/ external API.

Keys are stored as SHA-256 hashes in the api_keys table.
Format: wv_<uuid_hex> (no dashes)

Rate limiting: sliding window per key.
─────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import logging
import secrets
import time
import uuid
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Dict, List

from core.chat_db import _get_conn, _lock

logger = logging.getLogger("api_keys")

_rate_limiter: Dict[str, deque] = {}
_rl_lock = Lock()

PLAN_RATE_LIMITS = {
    "free": 10,         # 10 req/min
    "starter": 60,
    "pro": 300,
    "enterprise": -1,   # unlimited
}


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_key(name: str, plan: str = "free") -> Dict:
    """
    Generate a new API key.
    Returns {id, key (plaintext — only shown once), name, plan}
    """
    raw_key = "wv_" + secrets.token_hex(24)
    key_hash = _hash_key(raw_key)
    kid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    rate_limit = PLAN_RATE_LIMITS.get(plan, 10)
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO api_keys(id,name,key_hash,plan,created_at,request_count,rate_limit,active) "
            "VALUES(?,?,?,?,?,0,?,1)",
            (kid, name, key_hash, plan, now, rate_limit)
        )
        conn.commit()
    logger.info(f"[api_keys] Created key '{name}' plan={plan}")
    return {"id": kid, "key": raw_key, "name": name, "plan": plan}


def verify_key(raw_key: str) -> Dict:
    """
    Verify an API key and apply rate limiting.
    Returns {valid, plan, rate_limit, key_id} or {valid:False, reason:...}
    """
    if not raw_key or not raw_key.startswith("wv_"):
        return {"valid": False, "reason": "Invalid key format"}
    key_hash = _hash_key(raw_key)
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT id,plan,rate_limit,active FROM api_keys WHERE key_hash=?",
            (key_hash,)
        ).fetchone()
    if not row:
        return {"valid": False, "reason": "Key not found"}
    kid, plan, rate_limit, active = row
    if not active:
        return {"valid": False, "reason": "Key revoked"}

    # Rate limiting
    if rate_limit > 0:
        now = time.time()
        with _rl_lock:
            if kid not in _rate_limiter:
                _rate_limiter[kid] = deque()
            window = _rate_limiter[kid]
            # Remove timestamps older than 60s
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= rate_limit:
                return {"valid": False, "reason": f"Rate limit exceeded ({rate_limit}/min)"}
            window.append(now)

    # Update last_used + request_count
    now_str = datetime.utcnow().isoformat()
    with _lock:
        conn.execute(
            "UPDATE api_keys SET last_used=?, request_count=request_count+1 WHERE id=?",
            (now_str, kid)
        )
        conn.commit()

    return {"valid": True, "plan": plan, "rate_limit": rate_limit, "key_id": kid}


def revoke_key(key_id: str) -> bool:
    conn = _get_conn()
    with _lock:
        conn.execute("UPDATE api_keys SET active=0 WHERE id=?", (key_id,))
        conn.commit()
    return True


def rotate_key(key_id: str) -> Dict:
    """Revoke old key and create a new one with same name/plan."""
    conn = _get_conn()
    with _lock:
        row = conn.execute("SELECT name,plan FROM api_keys WHERE id=?", (key_id,)).fetchone()
    if not row:
        raise ValueError("Key not found")
    revoke_key(key_id)
    return create_key(row[0], row[1])


def list_keys() -> List[Dict]:
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id,name,plan,created_at,last_used,request_count,rate_limit,active FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"id": r[0], "name": r[1], "plan": r[2], "created_at": r[3],
         "last_used": r[4], "request_count": r[5], "rate_limit": r[6], "active": bool(r[7])}
        for r in rows
    ]
