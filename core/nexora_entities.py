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
        "create_upsert_by": "email",
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
        "create_link_creator": ["creator_id", "creator_profile_id"],
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
        "create_roles": [], "read_public": False,
        "self_cols": ["fan_email", "creator_email"],
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
        "writable": [], "create_roles": [], "read_public": False,
        "self_cols": ["from_email", "to_email"],
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
        "writable": ["amount", "payout_method"],
        "writable_admin": ["status", "admin_notes"],
        "create_roles": ["creator", "admin"], "read_public": False,
        "self_cols": ["creator_email"],
        "create_link_creator": ["creator_id"],
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
        "self_cols": ["email"],
    },
    "Follow": {
        "table": "nx_follows", "pk": "id", "owner_col": "fan_email",
        "fields": {
            "id": ("id", "int"), "fan_email": ("fan_email", "str"),
            "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "fan_email", "creator_email", "creator_profile_id"],
        "writable": ["creator_email", "creator_profile_id"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["fan_email", "creator_email"],
    },
    "Notification": {
        "table": "nx_notifications", "pk": "id", "owner_col": "user_email",
        "owner_from_body": True,
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "type": ("type", "str"), "title": ("title", "str"),
            "message": ("message", "str"), "link": ("link", "str"),
            "is_read": ("is_read", "bool"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email", "is_read", "type"],
        "writable": ["type", "title", "message", "link", "is_read"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["user_email"],
    },
    "ContentPurchase": {
        "table": "nx_content_purchases", "pk": "id", "owner_col": "fan_email",
        "fields": {
            "id": ("id", "int"), "fan_email": ("fan_email", "str"),
            "creator_email": ("creator_email", "str"), "creator_id": ("creator_id", "int"),
            "post_id": ("post_id", "int"), "amount": ("amount", "float"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "fan_email", "creator_email", "post_id"],
        "writable": [], "create_roles": [],
        "read_public": False, "self_cols": ["fan_email", "creator_email"],
    },
    "FanProfile": {
        "table": "nx_fan_profiles", "pk": "id", "owner_col": "user_email",
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "bio": ("bio", "str"), "preferences": ("preferences", "json"),
            "blocked_creators": ("blocked_creators", "json"),
            "is_age_verified": ("is_age_verified", "bool"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email"],
        "writable": ["bio", "preferences", "blocked_creators"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["user_email"],
    },
    "LiveStream": {
        "table": "nx_livestreams", "pk": "id", "owner_col": "creator_email",
        "create_link_creator": ["creator_profile_id"],
        "fields": {
            "id": ("id", "int"), "creator_email": ("creator_email", "str"),
            "creator_profile_id": ("creator_profile_id", "int"),
            "title": ("title", "str"), "description": ("description", "str"),
            "access_type": ("access_type", "str"), "price": ("price", "float"),
            "status": ("status", "str"), "viewer_count": ("viewer_count", "int"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "creator_email", "creator_profile_id", "status"],
        "writable": ["title", "description", "access_type", "price", "status"],
        "create_roles": ["creator", "admin"], "read_public": True,
    },
    "Tip": {
        "table": "nx_tips", "pk": "id", "owner_col": "to_email",
        "fields": {
            "id": ("id", "int"), "from_email": ("from_email", "str"),
            "to_email": ("to_email", "str"), "creator_id": ("creator_id", "int"),
            "amount": ("amount", "float"), "message": ("message", "str"),
            "livestream_id": ("livestream_id", "int"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "from_email", "to_email"],
        "writable": [], "create_roles": [],
        "read_public": False, "self_cols": ["from_email", "to_email"],
    },
    "Report": {
        "table": "nx_reports", "pk": "id", "owner_col": "reporter_email",
        "fields": {
            "id": ("id", "int"), "reporter_email": ("reporter_email", "str"),
            "reported_email": ("reported_email", "str"), "reason": ("reason", "str"),
            "details": ("details", "str"), "status": ("status", "str"),
            "admin_notes": ("admin_notes", "str"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "reporter_email", "reported_email", "status"],
        "writable": ["reported_email", "reason", "details"],
        "writable_admin": ["status", "admin_notes"],
        "create_roles": ["fan", "creator", "admin"],
        "read_public": False, "self_cols": ["reporter_email"],
    },
    "ModerationAction": {
        "table": "nx_moderation_actions", "pk": "id", "owner_col": "admin_email",
        "immutable": True,
        "fields": {
            "id": ("id", "int"), "admin_email": ("admin_email", "str"),
            "target_user_email": ("target_user_email", "str"), "action_type": ("action_type", "str"),
            "reason": ("reason", "str"), "notes": ("notes", "str"),
            "related_report_id": ("related_report_id", "int"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "admin_email", "target_user_email"],
        "writable": ["target_user_email", "action_type", "reason", "notes", "related_report_id"],
        "create_roles": ["admin"],
        "read_public": False, "self_cols": ["admin_email"],
    },
    "AuditLog": {
        "table": "nx_audit_logs", "pk": "id", "owner_col": "actor_email",
        "immutable": True,
        "fields": {
            "id": ("id", "int"), "actor_email": ("actor_email", "str"),
            "action": ("action", "str"), "entity_type": ("entity_type", "str"),
            "entity_id": ("entity_id", "str"), "details": ("details", "str"),
            "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "actor_email", "action", "entity_type"],
        "writable": ["action", "entity_type", "entity_id", "details"],
        "create_roles": ["admin"],
        "read_public": False, "self_cols": ["actor_email"],
    },
    "CreatorVerification": {
        "table": "nx_creator_verifications", "pk": "id", "owner_col": "user_email",
        "fields": {
            "id": ("id", "int"), "user_email": ("user_email", "str"),
            "legal_full_name": ("legal_full_name", "str"), "date_of_birth": ("date_of_birth", "str"),
            "country": ("country", "str"), "document_type": ("document_type", "str"),
            "document_front_url": ("document_front_url", "str"),
            "document_back_url": ("document_back_url", "str"), "selfie_url": ("selfie_url", "str"),
            "consent_confirmed": ("consent_confirmed", "bool"), "status": ("status", "str"),
            "reviewed_at": ("reviewed_at", "str"),
            "reviewed_by_admin_email": ("reviewed_by_admin_email", "str"),
            "review_notes": ("review_notes", "str"),
            "submitted_at": ("created_at", "ts"), "created_date": ("created_at", "ts"),
        },
        "filterable": ["id", "user_email", "status"],
        "writable": ["legal_full_name", "date_of_birth", "country", "document_type",
                     "document_front_url", "document_back_url", "selfie_url", "consent_confirmed"],
        "writable_admin": ["status", "reviewed_at", "reviewed_by_admin_email", "review_notes"],
        "create_roles": ["creator", "admin"],
        "read_public": False, "self_cols": ["user_email"],
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
            try:
                out[fe] = _iso(v)
            except Exception:
                out[fe] = None
        else:
            out[fe] = v
    return out


def _from_fe(entity: str, body: Dict, include_admin: bool = False) -> Dict:
    spec = ENTITIES[entity]
    allowed = list(spec["writable"])
    if include_admin:
        allowed += spec.get("writable_admin", [])
    cols = {}
    for fe in allowed:
        if fe in body:
            col, typ = spec["fields"][fe]
            v = body[fe]
            if typ == "json" and not isinstance(v, str):
                v = json.dumps(v)
            elif typ == "bool":
                v = 1 if v else 0
            cols[col] = v
    return cols


def entity_query(entity: str, criteria: Optional[Dict], sort: Optional[str],
                 limit: Optional[int]) -> List[Dict]:
    spec = ENTITIES[entity]
    init_db()
    where, params = [], []
    for fe, val in (criteria or {}).items():
        if fe in spec["filterable"]:
            col, typ = spec["fields"][fe]
            if typ == "bool":
                val = 1 if str(val).lower() in ("1", "true") else 0
            where.append(f"{col}=?"); params.append(val)
    sql = f"SELECT * FROM {spec['table']}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if sort:
        desc = sort.startswith("-")
        fe = sort[1:] if desc else sort
        col = spec["fields"].get(fe, (None,))[0]
        if col:
            sql += f" ORDER BY {col} {'DESC' if desc else 'ASC'}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_to_fe(entity, r) for r in rows]


def entity_get(entity: str, pk_value) -> Optional[Dict]:
    spec = ENTITIES[entity]
    init_db()
    conn = get_conn()
    row = conn.execute(f"SELECT * FROM {spec['table']} WHERE {spec['pk']}=?", (pk_value,)).fetchone()
    conn.close()
    return _to_fe(entity, row) if row else None


def _creator_id_for(email: str):
    conn = get_conn()
    row = conn.execute("SELECT id FROM nx_creators WHERE email=?", (email,)).fetchone()
    conn.close()
    return row["id"] if row else None


def _owner_email(entity: str, pk_value) -> Optional[str]:
    spec = ENTITIES[entity]
    conn = get_conn()
    row = conn.execute(f"SELECT {spec['owner_col']} AS o FROM {spec['table']} WHERE {spec['pk']}=?",
                       (pk_value,)).fetchone()
    conn.close()
    return row["o"] if row else None


def _require_owner_or_admin(entity: str, pk_value, actor: Dict) -> None:
    if actor.get("role") == "admin":
        return
    owner = _owner_email(entity, pk_value)
    if owner is None or owner != actor.get("email"):
        raise PermissionError("not allowed")


def entity_create(entity: str, body: Dict, actor: Dict) -> Dict:
    spec = ENTITIES[entity]
    if actor.get("role") not in spec.get("create_roles", []):
        raise PermissionError("not allowed")
    init_db()
    cols = _from_fe(entity, body)
    if spec.get("owner_from_body"):
        # entity is created FOR a recipient (e.g. Notification) — owner comes from the body
        owner_fe = next(fe for fe, (c, _t) in spec["fields"].items() if c == spec["owner_col"])
        if owner_fe not in body:
            raise PermissionError("recipient required")
        cols[spec["owner_col"]] = body[owner_fe]
    else:
        cols[spec["owner_col"]] = actor["email"]        # stamp ownership from token
    # Upsert mode: update an existing row instead of inserting (e.g. CreatorProfile over nx_creators,
    # where the creator's row already exists from registration).
    upsert_col = spec.get("create_upsert_by")
    if upsert_col:
        conn = get_conn()
        row = conn.execute(
            f"SELECT {spec['pk']} AS pk FROM {spec['table']} WHERE {upsert_col}=?",
            (actor["email"],)).fetchone()
        if row is not None:
            pk = row["pk"]
            if cols:
                sets = ",".join(f"{k}=?" for k in cols)
                conn.execute(f"UPDATE {spec['table']} SET {sets} WHERE {spec['pk']}=?",
                             [*cols.values(), pk])
                conn.commit()
            conn.close()
            return entity_get(entity, pk)
        conn.close()
    # (falls through to normal INSERT when no existing row)
    ts_col = spec["fields"]["created_date"][0]
    cols.setdefault(ts_col, time.time())
    # Resolve legacy/profile creator-id link columns from the owner's creator row.
    link_cols = spec.get("create_link_creator", [])
    if link_cols:
        cid = _creator_id_for(actor["email"])
        if cid is None:
            raise PermissionError("creator profile required")
        for c in link_cols:
            cols.setdefault(c, cid)
    keys = list(cols.keys())
    placeholders = ",".join("?" for _ in keys)
    conn = get_conn()
    cur = conn.execute(f"INSERT INTO {spec['table']} ({','.join(keys)}) VALUES ({placeholders})",
                       [cols[k] for k in keys])
    new_pk = actor["email"] if spec["pk"] == spec["owner_col"] else cur.lastrowid
    conn.commit(); conn.close()
    return entity_get(entity, new_pk)


def entity_update(entity: str, pk_value, body: Dict, actor: Dict) -> Optional[Dict]:
    if ENTITIES[entity].get("immutable"):
        raise PermissionError("immutable")
    init_db()
    _require_owner_or_admin(entity, pk_value, actor)
    spec = ENTITIES[entity]
    is_admin = actor.get("role") == "admin"
    cols = _from_fe(entity, body, include_admin=is_admin)
    if cols:
        sets = ",".join(f"{k}=?" for k in cols)
        conn = get_conn()
        conn.execute(f"UPDATE {spec['table']} SET {sets} WHERE {spec['pk']}=?",
                     [*cols.values(), pk_value])
        conn.commit(); conn.close()
    # Money reconciliation: when a payout is marked paid, recompute the creator's
    # balance from source so available_balance reflects the disbursement.
    if entity == "PayoutRequest" and cols.get("status") == "paid":
        updated = entity_get(entity, pk_value)
        if updated and updated.get("creator_email"):
            from core.nexora_ops import recalc_creator_stats
            recalc_creator_stats(updated["creator_email"])
    return entity_get(entity, pk_value)


def entity_delete(entity: str, pk_value, actor: Dict) -> None:
    if ENTITIES[entity].get("immutable"):
        raise PermissionError("immutable")
    init_db()
    _require_owner_or_admin(entity, pk_value, actor)
    spec = ENTITIES[entity]
    conn = get_conn()
    conn.execute(f"DELETE FROM {spec['table']} WHERE {spec['pk']}=?", (pk_value,))
    conn.commit(); conn.close()
