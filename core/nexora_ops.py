#!/usr/bin/env python3
"""core/nexora_ops.py — recompute persisted creator counters from source rows."""
from typing import Dict, List

from core.nexora_db import get_conn


def recalc_creator_stats(email: str) -> Dict:
    email = (email or "").strip().lower()
    conn = get_conn()
    sub = conn.execute("SELECT COUNT(*) n FROM nx_subscribers WHERE creator_email=? AND status='active'",
                       (email,)).fetchone()["n"]
    fol = conn.execute("SELECT COUNT(*) n FROM nx_follows WHERE creator_email=?", (email,)).fetchone()["n"]
    earn = conn.execute("SELECT COALESCE(SUM(creator_amount),0) s FROM nx_transactions WHERE to_email=?",
                        (email,)).fetchone()["s"]
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM nx_payouts WHERE creator_email=? AND status='paid'",
                        (email,)).fetchone()["s"]
    earn = round(earn, 2)
    bal = round(earn - paid, 2)
    conn.execute("UPDATE nx_creators SET subscriber_count=?, follower_count=?, total_earnings=?, available_balance=? "
                 "WHERE email=? OR user_email=?", (sub, fol, earn, bal, email, email))
    conn.commit()
    conn.close()
    return {"email": email, "subscriber_count": sub, "follower_count": fol,
            "total_earnings": earn, "available_balance": bal}


def recalc_all() -> List[Dict]:
    conn = get_conn()
    emails = [r["email"] for r in conn.execute("SELECT email FROM nx_creators")]
    conn.close()
    return [recalc_creator_stats(e) for e in emails]
