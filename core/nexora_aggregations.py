#!/usr/bin/env python3
"""core/nexora_aggregations.py — token-derived multi-entity feeds (replaces Base44 nexoraData)."""
from typing import Dict

from core.nexora_db import get_conn
from core.nexora_entities import entity_query, entity_get


def home_feed(actor: Dict) -> Dict:
    email = actor["email"]
    return {
        "ok": True,
        "creators": entity_query("CreatorProfile", {"status": "approved"}, None, 500),
        "posts": entity_query("Post", {"status": "published"}, "-created_date", 200),
        "follows": entity_query("Follow", {"fan_email": email}, None, None),
        "subscriptions": entity_query("Subscription", {"fan_email": email, "status": "active"}, None, None),
        "purchases": entity_query("ContentPurchase", {"fan_email": email}, None, None),
    }


def fan_data(actor: Dict) -> Dict:
    email = actor["email"]
    return {
        "ok": True,
        "creators": entity_query("CreatorProfile", {"status": "approved"}, None, 500),
        "follows": entity_query("Follow", {"fan_email": email}, None, None),
        "subscriptions": entity_query("Subscription", {"fan_email": email, "status": "active"}, None, None),
    }


def dashboard_data(actor: Dict) -> Dict:
    email = actor["email"]
    profiles = entity_query("CreatorProfile", {"user_email": email}, None, 1)
    if not profiles:
        return {"ok": True, "profile": None}
    return {
        "ok": True,
        "profile": profiles[0],
        "posts": entity_query("Post", {"creator_email": email}, "-created_date", None),
        "transactions": entity_query("Transaction", {"to_email": email}, "-created_date", None),
        "subscriptions": entity_query("Subscription", {"creator_email": email, "status": "active"}, None, None),
        "payouts": entity_query("PayoutRequest", {"creator_email": email}, "-created_date", None),
        "notifications": entity_query("Notification", {"user_email": email, "is_read": False}, None, None),
    }


def toggle_live(actor: Dict, is_live: bool) -> Dict:
    profiles = entity_query("CreatorProfile", {"user_email": actor["email"]}, None, 1)
    if not profiles:
        return {"ok": False, "error": "No creator profile"}
    pid = profiles[0]["id"]
    conn = get_conn()
    conn.execute("UPDATE nx_creators SET is_live=? WHERE id=?", (1 if is_live else 0, pid))
    conn.commit()
    conn.close()
    return {"ok": True, "profile": entity_get("CreatorProfile", pid)}
