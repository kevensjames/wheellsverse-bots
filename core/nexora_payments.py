#!/usr/bin/env python3
"""core/nexora_payments.py — Stripe Checkout session creation + webhook record handling."""
import os
from typing import Dict


def _stripe():
    import stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    return stripe


def _checkout(name: str, amount_cents: int, success_url: str, cancel_url: str, metadata: Dict) -> Dict:
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {"currency": "usd", "product_data": {"name": name}, "unit_amount": amount_cents},
            "quantity": 1,
        }],
        success_url=success_url or "",
        cancel_url=cancel_url or "",
        metadata=metadata,
    )
    return {"checkout_url": session.url}


def create_subscription_checkout(actor: Dict, body: Dict) -> Dict:
    price = float(body.get("subscription_price") or 0)
    if price <= 0:
        raise ValueError("invalid subscription price")
    return _checkout(
        f"Subscription to {body.get('creator_name', 'creator')}",
        int(round(price * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "subscription", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "creator_profile_id": str(body.get("creator_profile_id", ""))},
    )


def create_tip_checkout(actor: Dict, body: Dict) -> Dict:
    amount = float(body.get("amount") or 0)
    if amount < 1:
        raise ValueError("tip minimum is $1")
    return _checkout(
        f"Tip to {body.get('creator_name', 'creator')}",
        int(round(amount * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "tip", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "message": (body.get("message") or "")[:200],
         "livestream_id": str(body.get("livestream_id") or "")},
    )


def create_ppv_checkout(actor: Dict, body: Dict) -> Dict:
    amount = float(body.get("amount") or body.get("ppv_price") or 0)
    if amount <= 0:
        raise ValueError("invalid PPV price")
    return _checkout(
        body.get("title") or body.get("post_title") or "Exclusive content",
        int(round(amount * 100)),
        body.get("success_url", ""), body.get("cancel_url", ""),
        {"type": "ppv", "fan_email": actor["email"],
         "creator_email": body.get("creator_email", ""),
         "post_id": str(body.get("post_id", ""))},
    )


import time as _time
from core.nexora_db import get_conn

PLATFORM_FEE_PCT = 10  # 10% platform / 90% creator
SUB_PERIOD_SECS = 30 * 86400  # one subscription period (current flow is one-shot mode='payment')


def _split(amount: float):
    platform = round(amount * PLATFORM_FEE_PCT / 100.0, 2)
    return platform, round(amount - platform, 2)


def _creator_row(conn, creator_email: str):
    return conn.execute("SELECT id FROM nx_creators WHERE email=? OR user_email=?",
                        (creator_email, creator_email)).fetchone()


def _notify(conn, user_email: str, ntype: str, title: str, message: str):
    conn.execute("INSERT INTO nx_notifications (user_email,type,title,message,is_read,created_at) "
                 "VALUES (?,?,?,?,0,?)", (user_email, ntype, title, message, _time.time()))


import sqlite3 as _sqlite3


def _event_seen(conn, event_id: str) -> bool:
    """Idempotency ledger for non-checkout events, keyed on the Stripe event id
    (evt_...). Insert-or-noop: returns True if this event was already processed.
    Complements (does not replace) the per-session stripe_id guard on checkout."""
    if not event_id:
        return False
    try:
        conn.execute("INSERT INTO nx_payment_events (event_id,type,created_at) VALUES (?,?,?)",
                     (event_id, "", _time.time()))
        return False   # NOT committed here — commits atomically with the caller's mutation
    except _sqlite3.IntegrityError:
        return True   # PRIMARY KEY collision -> already seen


def handle_stripe_event(event: Dict) -> Dict:
    """Dispatch a verified Stripe event. checkout.session.completed records the
    inbound payment; refund/dispute/Connect events are routed to their handlers
    (added in later phases). Unknown types are ack'd so Stripe stops retrying."""
    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    if etype == "checkout.session.completed":
        return _handle_checkout(event, obj)
    if etype == "charge.refunded":
        return _handle_refund(event, obj)
    if etype == "charge.dispute.created":
        return _handle_dispute(event, obj)
    if etype in ("account.updated", "transfer.created", "payout.paid", "payout.failed"):
        return _handle_connect_event(etype, obj)
    return {"received": True, "ignored": etype}


def _find_payout_for_connect(conn, obj: Dict):
    """Resolve the nx_payouts row a Connect transfer/payout event refers to:
    by metadata.payout_id (set on the Transfer at disburse time), then by the
    stored transfer/payout id."""
    meta = obj.get("metadata", {}) or {}
    pid = meta.get("payout_id")
    if pid:
        row = conn.execute("SELECT * FROM nx_payouts WHERE id=?", (pid,)).fetchone()
        if row:
            return row
    oid = obj.get("id", "")
    if oid:
        return conn.execute("SELECT * FROM nx_payouts WHERE stripe_transfer_id=? OR stripe_payout_id=?",
                            (oid, oid)).fetchone()
    return None


def _handle_connect_event(etype: str, obj: Dict) -> Dict:
    """Mirror Stripe Connect state into our rows, then recalc the affected creator.
    account.updated -> KYC/payouts_enabled; payout.paid/transfer.created -> mark the
    PayoutRequest 'paid'; payout.failed -> 'failed' (frees the balance again).
    recalc stays the single balance writer — paid payouts are subtracted there."""
    conn = get_conn()
    creator_email = ""
    try:
        if etype == "account.updated":
            acct = obj.get("id", "")
            enabled = 1 if obj.get("payouts_enabled") else 0
            status = "complete" if enabled else ("pending" if obj.get("details_submitted") else "started")
            conn.execute("UPDATE nx_creators SET stripe_payouts_enabled=?, stripe_onboarding_status=? "
                         "WHERE stripe_account_id=?", (enabled, status, acct))
            conn.commit()
            return {"received": True, "account_updated": acct, "payouts_enabled": bool(enabled)}
        payout = _find_payout_for_connect(conn, obj)
        if payout is None:
            return {"received": True, "no_matching_payout": obj.get("id")}
        creator_email = payout["creator_email"] or ""
        if etype == "payout.failed":
            if payout["status"] != "failed":   # idempotent
                conn.execute("UPDATE nx_payouts SET status='failed', failure_reason=? WHERE id=?",
                             (obj.get("failure_message") or "payout failed", payout["id"]))
        else:  # payout.paid / transfer.created -> confirm disbursement
            if payout["status"] != "paid":     # idempotent
                conn.execute("UPDATE nx_payouts SET status='paid', completed_at=? WHERE id=?",
                             (_time.time(), payout["id"]))
        conn.commit()
    finally:
        conn.close()
    if creator_email:
        try:
            from core.nexora_ops import recalc_creator_stats
            recalc_creator_stats(creator_email)
        except Exception as e:  # noqa: BLE001 — self-heals via recalc_all()
            return {"received": True, "recalc_deferred": str(e)}
    return {"received": True, "connect": etype}


def _find_txn_by_charge(conn, obj: Dict):
    """Resolve the original nx_transactions row for a refund/dispute charge object.
    Correlate by payment_intent (persisted at checkout), then charge id. No
    amount-based fallback — guessing risks reversing the wrong creator's earnings."""
    pi = obj.get("payment_intent") or ""
    # A charge.refunded object's own id IS the charge id; a charge.dispute.created
    # object's id is dp_... and the charge is in obj["charge"]. Try both against charge_id.
    charge_candidates = [c for c in (obj.get("charge"), obj.get("id")) if c]
    row = None
    if pi:
        row = conn.execute("SELECT * FROM nx_transactions WHERE payment_intent=? ORDER BY id DESC LIMIT 1",
                           (pi,)).fetchone()
    for ch in charge_candidates:
        if row is not None:
            break
        row = conn.execute("SELECT * FROM nx_transactions WHERE charge_id=? ORDER BY id DESC LIMIT 1",
                           (ch,)).fetchone()
    return row


def _revoke_access(conn, txn: Dict) -> None:
    """Re-lock content after a full refund/dispute. Subscription -> cancelled;
    PPV -> remove the purchase row; tip -> nothing to revoke."""
    ttype = txn["type"]
    cid = txn["creator_id"]
    fan = txn["fan_email"]
    if ttype == "subscription":
        conn.execute("UPDATE nx_subscribers SET status='cancelled', cancelled_at=? "
                     "WHERE creator_id=? AND fan_email=?", (_time.time(), cid, fan))
    elif ttype == "ppv":
        # Revoke the EXACT post that was refunded (post_id is persisted on the txn),
        # not just the most-recent purchase — a fan may own several PPV posts.
        pid = txn["post_id"] if "post_id" in txn.keys() else 0
        if pid:
            conn.execute("DELETE FROM nx_content_purchases WHERE creator_id=? AND fan_email=? AND post_id=?",
                         (cid, fan, pid))
        else:
            conn.execute("DELETE FROM nx_content_purchases WHERE id = ("
                         "SELECT id FROM nx_content_purchases WHERE creator_id=? AND fan_email=? "
                         "ORDER BY created_at DESC LIMIT 1)", (cid, fan))


def _reverse_earnings(event: Dict, obj: Dict, full_status: str) -> Dict:
    """Shared refund/dispute mechanic. Full reversal flips the txn status off
    'succeeded' (so recalc drops it entirely) + revokes access. Partial reduces
    creator_amount AND creator_cut in place (status stays 'succeeded') so both
    recalc (sums creator_amount) and the payout gate (sums creator_cut) agree.
    Then recalc — the single counter writer — recomputes earnings/balance."""
    creator_email = ""
    is_full = True
    conn = get_conn()
    try:
        if _event_seen(conn, event.get("id", "")):
            return {"received": True, "duplicate_event": event.get("id")}
        txn = _find_txn_by_charge(conn, obj)
        if txn is None:
            return {"received": True, "no_matching_txn": obj.get("payment_intent") or obj.get("id")}
        if txn["status"] in ("refunded", "disputed"):
            # Already fully reversed — never re-open a reversed row (would resurrect earnings).
            return {"received": True, "already_processed": txn["id"]}
        creator_email = txn["to_email"]
        amount_cents = obj.get("amount", 0) or 0
        refunded_cents = obj.get("amount_refunded", 0) or 0
        # Disputes are a full clawback. Refunds may be partial.
        is_full = (full_status == "disputed") or bool(obj.get("refunded")) \
            or (amount_cents > 0 and refunded_cents >= amount_cents)
        if is_full:
            conn.execute("UPDATE nx_transactions SET status=?, refunded_amount=? WHERE id=?",
                         (full_status, round(txn["amount"], 2), txn["id"]))
            _revoke_access(conn, txn)
        else:
            # Recompute net from the ORIGINAL gross (txn.amount is never mutated) and
            # Stripe's CUMULATIVE amount_refunded, so repeated partials stay correct.
            orig_gross = txn["amount"]
            refunded_total = round(refunded_cents / 100.0, 2)
            net_gross = max(0.0, round(orig_gross - refunded_total, 2))
            new_creator = round(net_gross * (1 - PLATFORM_FEE_PCT / 100.0), 2)
            new_platform = round(net_gross - new_creator, 2)
            conn.execute(
                "UPDATE nx_transactions SET creator_amount=?, creator_cut=?, platform_fee=?, "
                "platform_cut=?, refunded_amount=? WHERE id=?",
                (new_creator, new_creator, new_platform, new_platform, refunded_total, txn["id"]))
        conn.commit()
    finally:
        conn.close()
    if creator_email:
        try:
            from core.nexora_ops import recalc_creator_stats
            recalc_creator_stats(creator_email)
        except Exception as e:  # noqa: BLE001 — self-heals via recalc_all()
            return {"received": True, "recalc_deferred": str(e)}
    return {"received": True, "reversed": full_status, "full": is_full}


def _handle_refund(event: Dict, obj: Dict) -> Dict:
    return _reverse_earnings(event, obj, full_status="refunded")


def _handle_dispute(event: Dict, obj: Dict) -> Dict:
    return _reverse_earnings(event, obj, full_status="disputed")


def _handle_checkout(event: Dict, obj: Dict) -> Dict:
    meta = obj.get("metadata", {}) or {}
    t = meta.get("type")
    amount = (obj.get("amount_total", 0) or 0) / 100.0
    fan_email = meta.get("fan_email", "")
    creator_email = meta.get("creator_email", "")
    stripe_id = obj.get("id", "")
    payment_intent = obj.get("payment_intent", "") or ""
    post_id = int(meta.get("post_id") or 0)
    platform, creator_amount = _split(amount)
    now = _time.time()
    conn = get_conn()
    # Idempotency: Stripe retries webhooks at-least-once. A transaction already
    # recorded for this session id means we've processed it — no-op.
    if stripe_id and conn.execute("SELECT 1 FROM nx_transactions WHERE stripe_id=?",
                                  (stripe_id,)).fetchone():
        conn.close()
        return {"received": True, "duplicate": stripe_id}
    crow = _creator_row(conn, creator_email)
    cid = crow["id"] if crow else None
    if cid is None:
        # Unknown creator — ack so Stripe stops retrying; ops reconciles out of band.
        conn.close()
        return {"received": True, "unknown_creator": creator_email}
    try:
        # NOTE: creator counters (subscriber_count, total_earnings,
        # available_balance) are NOT incremented here. recalc_creator_stats()
        # below recomputes them from source rows so there is exactly ONE writer
        # of available_balance — eliminating the accumulator-vs-projection
        # divergence (webhook +=  vs  recalc = earn-paid).
        if t == "subscription":
            # UPSERT (not raw INSERT): nx_subscribers has UNIQUE(creator_id,fan_email),
            # so a repeat purchase with a new stripe_id would 500 on INSERT. On renewal,
            # EXTEND expires_at = MAX(existing, now) + period: an active sub stacks time
            # onto its remaining window; an expired/lapsed sub restarts from now.
            conn.execute(
                "INSERT INTO nx_subscribers (creator_id,fan_email,status,price_paid,started_at,"
                "creator_email,amount,expires_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(creator_id,fan_email) DO UPDATE SET "
                "  status='active', cancelled_at=NULL, "
                "  price_paid=excluded.price_paid, amount=excluded.amount, "
                "  creator_email=excluded.creator_email, "
                "  expires_at = MAX(COALESCE(nx_subscribers.expires_at, ?), ?) + ?",
                (cid, fan_email, "active", amount, now, creator_email, amount, now + SUB_PERIOD_SECS,
                 now, now, SUB_PERIOD_SECS))
            _notify(conn, creator_email, "new_subscriber", "New subscriber!", f"{fan_email} subscribed")
        elif t == "ppv":
            conn.execute("INSERT INTO nx_content_purchases (fan_email,creator_email,creator_id,post_id,amount,created_at) "
                         "VALUES (?,?,?,?,?,?)",
                         (fan_email, creator_email, cid, int(meta.get("post_id") or 0), amount, now))
            _notify(conn, creator_email, "system", "Content unlocked", f"{fan_email} purchased your content")
        elif t == "tip":
            conn.execute("INSERT INTO nx_tips (from_email,to_email,creator_id,amount,message,livestream_id,created_at) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (fan_email, creator_email, cid, amount, meta.get("message", ""),
                          int(meta.get("livestream_id") or 0) or None, now))
            _notify(conn, creator_email, "system", "You got a tip!", f"{fan_email} tipped ${amount:.2f}")
        else:
            conn.close()
            return {"received": True, "ignored_type": t}
        try:
            conn.execute(
                "INSERT INTO nx_transactions (creator_id,fan_email,amount,platform_cut,creator_cut,type,stripe_id,"
                "status,created_at,from_email,to_email,creator_amount,platform_fee,description,payment_intent,post_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fan_email, amount, platform, creator_amount, t, stripe_id, "succeeded", now,
                 fan_email, creator_email, creator_amount, platform, f"{t} payment", payment_intent, post_id))
            conn.commit()
        except _sqlite3.IntegrityError:
            # A concurrent Stripe retry raced past the SELECT-1 fast path; the
            # partial UNIQUE index on stripe_id rejects the duplicate. Roll back
            # the whole event (subscriber/tip/ppv insert included) — no double-credit.
            conn.rollback()
            return {"received": True, "duplicate": stripe_id}
    finally:
        conn.close()
    # Single source of truth for all creator counters. Runs after commit/close
    # because recalc opens its own connection (WAL: a separate connection can't
    # see uncommitted writes). Best-effort: the payment is already durably
    # recorded above; if reconciliation fails, recalc_all() (startup/cron sweep)
    # heals the drift. Surfacing a 500 here would only trigger a Stripe retry,
    # which hits idempotency and returns early WITHOUT re-running recalc.
    try:
        from core.nexora_ops import recalc_creator_stats
        recalc_creator_stats(creator_email)
    except Exception as e:  # noqa: BLE001 — counters self-heal via recalc_all()
        return {"received": True, "recalc_deferred": str(e)}
    return {"received": True}
