#!/usr/bin/env python3
"""core/nexora_entities.py — declarative entity registry + FE<->row mapping + REST ops."""
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.nexora_db import get_conn, init_db

# field spec: FE name -> (column, type)  type in {str,int,float,bool,json,ts}
ENTITIES = {
    "CreatorProfile": {
        "table": "nx_creators", "pk": "id", "owner_col": "user_email",
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "display_name": ("display_name", "str"), "bio": ("bio", "str"),
            "category": ("category", "str"), "avatar_url": ("avatar", "str"),
            "cover_url": ("cover_url", "str"), "social_links": ("social_links", "json"),
            "subscription_price": ("price", "float"), "status": ("status", "str"),
            "verification_status": ("verification_status", "str"),
            "total_earnings": ("total_earnings", "float"),
            "available_balance": ("available_balance", "float"),
            "subscriber_count": ("subscriber_count", "int"),
            "follower_count": ("follower_count", "int"),
            "is_live": ("is_live", "bool"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email", "status"],
        "writable": ["display_name", "bio", "category", "avatar_url", "cover_url",
                     "social_links", "subscription_price"],
        "create_roles": ["fan", "creator", "admin"], "read_public": True,
    },
    "Post": {
        "table": "nx_posts", "pk": "id", "owner_col": "creator_email",
        "fields": {
            "id": ("id", "int"), "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "title": ("title", "str"), "text": ("text", "str"),
            "media_urls": ("media_urls", "json"), "media_type": ("media_type", "str"),
            "access_type": ("access_type", "str"), "ppv_price": ("ppv_price", "float"),
            "status": ("status", "str"), "like_count": ("like_count", "int"),
            "comment_count": ("comment_count", "int"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "creator_email", "creator_profile_id", "status", "access_type"],
        "writable": ["title", "text", "media_urls", "media_type", "access_type",
                     "ppv_price", "status"],
        "create_roles": ["creator", "admin"], "read_public": True,
    },
    "Subscription": {
        "table": "nx_subscribers", "pk": "id", "owner_col": "fan_email",
        "fields": {
            "id": ("id", "int"), "fan_email": ("fan_email", "str"),
            "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "amount": ("amount", "float"), "status": ("status", "str"),
            "created_date": ("started_at", "ts"),
        },
        "filterable": ["id", "fan_email", "creator_email", "status"],
        "writable": ["status"],
        "create_roles": ["admin"], "read_public": False,
    },
    "Transaction": {
        "table": "nx_transactions", "pk": "id", "owner_col": "to_email",
        "fields": {
            "id": ("id", "int"), "from_email": ("from_email", "str"),
            "to_email": ("to_email", "str"), "amount": ("amount", "float"),
            "creator_amount": ("creator_amount", "float"),
            "platform_fee": ("platform_fee", "float"), "type": ("type", "str"),
            "status": ("status", "str"), "description": ("description", "str"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "from_email", "to_email", "type", "status"],
        "writable": [], "create_roles": ["admin"], "read_public": False,
    },
    "PayoutRequest": {
        "table": "nx_payouts", "pk": "id", "owner_col": "creator_email",
        "fields": {
            "id": ("id", "int"), "creator_email": ("creator_email", "str"),
            "amount": ("amount", "float"), "payout_method": ("payout_method", "str"),
            "status": ("status", "str"), "admin_notes": ("admin_notes", "str"),
            "created_date": ("requested_at", "ts"),
        },
        "filterable": ["id", "creator_email", "status"],
        "writable": ["status", "admin_notes"],
        "create_roles": ["creator", "admin"], "read_public": False,
    },
    "User": {
        "table": "nx_users", "pk": "email", "owner_col": "email",
        "fields": {
            "id": ("email", "str"), "email": ("email", "str"),
            "full_name": ("full_name", "str"), "role": ("role", "str"),
            "is_suspended": ("is_suspended", "bool"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["email", "role", "is_suspended"],
        "writable": ["is_suspended", "full_name"],
        "create_roles": ["admin"], "read_public": False,
    },
}


def _iso(epoch) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _to_fe(entity: str, row) -> Dict:
    spec = ENTITIES[entity]
    keys = row.keys() if hasattr(row, "keys") else []
    out = {}
    for fe, (col, typ) in spec["fields"].items():
        if col not in keys:
            continue
        v = row[col]
        if v is None:
            out[fe] = None
        elif typ == "bool":
            out[fe] = bool(v)
        elif typ == "int":
            out[fe] = int(v)
        elif typ == "float":
            out[fe] = float(v)
        elif typ == "json":
            try:
                out[fe] = json.loads(v) if isinstance(v, str) else v
            except Exception:
                out[fe] = v
        elif typ == "ts":
            out[fe] = _iso(v)
        else:
            out[fe] = v
    return out


def _from_fe(entity: str, body: Dict) -> Dict:
    spec = ENTITIES[entity]
    cols = {}
    for fe in spec["writable"]:
        if fe in body:
            col, typ = spec["fields"][fe]
            v = body[fe]
            if typ == "json" and not isinstance(v, str):
                v = json.dumps(v)
            elif typ == "bool":
                v = 1 if v else 0
            cols[col] = v
    return cols
