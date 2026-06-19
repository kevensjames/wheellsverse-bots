#!/usr/bin/env python3
"""core/nexora_subscriptions.py — subscription expiry sweep.

nx_subscribers.expires_at is set on the subscription webhook but nothing read it,
so subs were perpetual. This module flips active + past-due subscriptions to
status='expired' so they drop out of recalc_creator_stats' COUNT(status='active').

recalc_creator_stats stays the SINGLE writer of creator counters — we only flip
source rows here, then call recalc per affected creator (after commit).
"""
import time
from typing import Dict, Optional

from core.nexora_db import get_conn

_PRED = "status='active' AND expires_at IS NOT NULL AND expires_at < ?"


def expire_subscriptions(now: Optional[float] = None, grace_secs: float = 0) -> Dict:
    """Flip active subs whose expires_at < now-grace_secs to 'expired'. Idempotent.

    NULL expires_at rows are treated as never-expiring (legacy rows created via
    add_subscriber, which never sets expires_at) and are NOT swept — sweeping them
    would mass-expire every legacy subscriber and zero all MRR.

    Returns {expired_count, affected:[creator_emails]}.
    """
    now = time.time() if now is None else now
    cutoff = now - grace_secs
    conn = get_conn()
    try:
        rows = conn.execute(
            f"SELECT DISTINCT creator_email FROM nx_subscribers WHERE {_PRED}", (cutoff,)
        ).fetchall()
        affected = [r["creator_email"] for r in rows if r["creator_email"]]
        cur = conn.execute(f"UPDATE nx_subscribers SET status='expired' WHERE {_PRED}", (cutoff,))
        expired = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return {"expired_count": expired, "affected": affected}


def sweep_and_recalc(grace_secs: float = 0) -> Dict:
    """Expire past-due subs, then recalc each affected creator on a fresh connection
    (WAL: a separate connection can't see uncommitted writes, so recalc runs after commit)."""
    from core.nexora_ops import recalc_creator_stats
    out = expire_subscriptions(grace_secs=grace_secs)
    for email in out["affected"]:
        recalc_creator_stats(email)
    out["creators_recalced"] = len(out["affected"])
    return out
