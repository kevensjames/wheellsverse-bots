#!/usr/bin/env python3
"""core/nexora_admin.py — out-of-band admin account management.

Usage:
    python -m core.nexora_admin seed-admin <email> <password>
    python -m core.nexora_admin set-role  <email> <admin|creator|fan>
"""
import sys
import time

from core.nexora_db import get_conn, init_db
from core.nexora_auth import hash_password, _unique_handle
from core.nexora_users import upsert_user, set_role


def seed_admin(email: str, password: str) -> None:
    """Create (or promote) an admin. Stores a password via the creator table so
    the admin can log in through the standard login flow."""
    email = email.strip().lower()
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT id FROM nx_creators WHERE email=?", (email,)).fetchone()
    if row is None:
        handle = _unique_handle(conn, email.split("@")[0])
        cur = conn.execute(
            "INSERT INTO nx_creators (email,name,handle,founding,created_at) "
            "VALUES (?,?,?,0,?)", (email, "Admin", handle, time.time()))
        cid = cur.lastrowid
    else:
        cid = row["id"]
    conn.execute("INSERT OR REPLACE INTO nx_passwords (creator_id,hash) VALUES (?,?)",
                 (cid, hash_password(password)))
    conn.commit()
    conn.close()
    upsert_user(email, full_name="Admin", role="admin")
    set_role(email, "admin")          # force admin even if upsert kept a prior role


def _main(argv):
    if len(argv) == 3 and argv[0] == "seed-admin":
        seed_admin(argv[1], argv[2]); print(f"admin seeded: {argv[1]}")
    elif len(argv) == 3 and argv[0] == "set-role":
        set_role(argv[1], argv[2]); print(f"{argv[1]} -> {argv[2]}")
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    _main(sys.argv[1:])
