#!/usr/bin/env python3
"""core/nexora_users.py — canonical Nexora identity (nx_users) + role logic."""
import time
from typing import Dict, List, Optional

from core.nexora_db import get_conn, init_db

VALID_ROLES = {"admin", "creator", "fan"}


def _user_dict(row) -> Dict:
    return {
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "is_suspended": bool(row["is_suspended"]),
        "age_verified": bool(row["age_verified"]),
        "avatar_url": row["avatar_url"],
    }


def upsert_user(email: str, *, full_name: Optional[str] = None,
                role: Optional[str] = None, avatar_url: Optional[str] = None) -> Dict:
    email = email.strip().lower()
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM nx_users WHERE email=?", (email,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO nx_users (email, full_name, role, avatar_url, created_at) "
            "VALUES (?,?,?,?,?)",
            (email, full_name or "", role if role in VALID_ROLES else "fan",
             avatar_url or "", time.time()),
        )
    else:
        sets, vals = [], []
        if full_name is not None:
            sets.append("full_name=?"); vals.append(full_name)
        if role in VALID_ROLES and row["role"] != "admin":
            sets.append("role=?"); vals.append(role)
        if avatar_url is not None:
            sets.append("avatar_url=?"); vals.append(avatar_url)
        if sets:
            vals.append(email)
            conn.execute(f"UPDATE nx_users SET {', '.join(sets)} WHERE email=?", vals)
    conn.commit()
    out = conn.execute("SELECT * FROM nx_users WHERE email=?", (email,)).fetchone()
    conn.close()
    return _user_dict(out)


def get_user(email: str) -> Optional[Dict]:
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM nx_users WHERE email=?",
                       (email.strip().lower(),)).fetchone()
    conn.close()
    return _user_dict(row) if row else None


def _set_field(email: str, field: str, value) -> None:
    conn = get_conn()
    conn.execute(f"UPDATE nx_users SET {field}=? WHERE email=?",
                 (value, email.strip().lower()))
    conn.commit()
    conn.close()


def set_role(email: str, role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role}")
    _set_field(email, "role", role)


def set_suspended(email: str, suspended: bool) -> None:
    _set_field(email, "is_suspended", 1 if suspended else 0)


def set_age_verified(email: str) -> None:
    _set_field(email, "age_verified", 1)


def check_access(user: Optional[Dict], *allowed_roles: str) -> bool:
    return bool(user) and user.get("role") in allowed_roles


def resolve_user(token: str) -> Optional[Dict]:
    """Resolve an opaque bearer token (creator OR fan) to the canonical User.
    Upserts nx_users so identity exists even for pre-nx_users accounts."""
    if not token:
        return None
    from core.nexora_auth import verify_token            # creator
    from core.nexora_db import verify_fan_token          # fan -> email str

    creator = verify_token(token)
    if creator:
        return upsert_user(creator["email"], full_name=creator.get("name"),
                           role="creator", avatar_url=creator.get("avatar") or None)
    fan_email = verify_fan_token(token)
    if fan_email:
        return upsert_user(fan_email, role="fan")
    return None
