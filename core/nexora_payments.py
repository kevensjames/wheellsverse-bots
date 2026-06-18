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


def _split(amount: float):
    platform = round(amount * PLATFORM_FEE_PCT / 100.0, 2)
    return platform, round(amount - platform, 2)


def _creator_row(conn, creator_email: str):
    return conn.execute("SELECT id FROM nx_creators WHERE email=? OR user_email=?",
                        (creator_email, creator_email)).fetchone()


def _notify(conn, user_email: str, ntype: str, title: str, message: str):
    conn.execute("INSERT INTO nx_notifications (user_email,type,title,message,is_read,created_at) "
                 "VALUES (?,?,?,?,0,?)", (user_email, ntype, title, message, _time.time()))


def handle_stripe_event(event: Dict) -> Dict:
    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    meta = obj.get("metadata", {}) or {}
    if etype != "checkout.session.completed":
        return {"received": True, "ignored": etype}
    t = meta.get("type")
    amount = (obj.get("amount_total", 0) or 0) / 100.0
    fan_email = meta.get("fan_email", "")
    creator_email = meta.get("creator_email", "")
    stripe_id = obj.get("id", "")
    platform, creator_amount = _split(amount)
    now = _time.time()
    conn = get_conn()
    crow = _creator_row(conn, creator_email)
    cid = crow["id"] if crow else None
    try:
        if t == "subscription":
            conn.execute(
                "INSERT INTO nx_subscribers (creator_id,fan_email,status,price_paid,started_at,"
                "creator_email,amount,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (cid or 0, fan_email, "active", amount, now, creator_email, amount, now + 30 * 86400))
            if cid:
                conn.execute("UPDATE nx_creators SET subscriber_count=subscriber_count+1, "
                             "total_earnings=total_earnings+?, available_balance=available_balance+? WHERE id=?",
                             (creator_amount, creator_amount, cid))
            _notify(conn, creator_email, "new_subscriber", "New subscriber!", f"{fan_email} subscribed")
        elif t == "ppv":
            conn.execute("INSERT INTO nx_content_purchases (fan_email,creator_email,creator_id,post_id,amount,created_at) "
                         "VALUES (?,?,?,?,?,?)",
                         (fan_email, creator_email, cid, int(meta.get("post_id") or 0), amount, now))
            if cid:
                conn.execute("UPDATE nx_creators SET total_earnings=total_earnings+?, available_balance=available_balance+? WHERE id=?",
                             (creator_amount, creator_amount, cid))
            _notify(conn, creator_email, "system", "Content unlocked", f"{fan_email} purchased your content")
        elif t == "tip":
            conn.execute("INSERT INTO nx_tips (from_email,to_email,creator_id,amount,message,livestream_id,created_at) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (fan_email, creator_email, cid, amount, meta.get("message", ""),
                          int(meta.get("livestream_id") or 0) or None, now))
            if cid:
                conn.execute("UPDATE nx_creators SET total_earnings=total_earnings+?, available_balance=available_balance+? WHERE id=?",
                             (creator_amount, creator_amount, cid))
            _notify(conn, creator_email, "system", "You got a tip!", f"{fan_email} tipped ${amount:.2f}")
        else:
            conn.close()
            return {"received": True, "ignored_type": t}
        conn.execute(
            "INSERT INTO nx_transactions (creator_id,fan_email,amount,platform_cut,creator_cut,type,stripe_id,"
            "status,created_at,from_email,to_email,creator_amount,platform_fee,description) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid or 0, fan_email, amount, platform, creator_amount, t, stripe_id, "succeeded", now,
             fan_email, creator_email, creator_amount, platform, f"{t} payment"))
        conn.commit()
    finally:
        conn.close()
    return {"received": True}
