"""
core/narai_user.py
─────────────────────────────────────────────────────────────────────────────
NarAI User Layer — Supabase auth, tier management, session handling.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("narai.user")

# ─── Supabase client (lazy) ──────────────────────────────────────────────────

_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        try:
            from supabase import create_client
            url = os.getenv("SUPABASE_URL", "")
            key = os.getenv("SUPABASE_SERVICE_KEY", "")
            if not url or not key:
                raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
            _supabase = create_client(url, key)
        except Exception as e:
            log.error(f"Supabase init failed: {e}")
            raise
    return _supabase

# ─── Tier configuration ──────────────────────────────────────────────────────

TIER_CONFIG = {
    "free": {
        "label":          "Free",
        "price":          0,
        "messages_day":   10,
        "history_days":   7,
        "models":         ["claude-haiku-4-5-20251001"],
        "memory":         False,
        "code_mode":      False,
        "web_search":     False,
    },
    "pro": {
        "label":          "Pro",
        "price":          9.99,
        "stripe_price_id": os.getenv("STRIPE_PRICE_PRO", ""),
        "messages_day":   100,
        "history_days":   90,
        "models":         ["claude-sonnet-4-6", "gpt-4o"],
        "memory":         True,
        "code_mode":      False,
        "web_search":     False,
    },
    "max": {
        "label":          "Max",
        "price":          19.99,
        "stripe_price_id": os.getenv("STRIPE_PRICE_MAX", ""),
        "messages_day":   500,
        "history_days":   None,  # unlimited
        "models":         ["claude-sonnet-4-6", "claude-opus-4-6", "gpt-4o"],
        "memory":         True,
        "code_mode":      True,
        "web_search":     True,
    },
    "ultra": {
        "label":          "Ultra",
        "price":          50.00,
        "stripe_price_id": os.getenv("STRIPE_PRICE_ULTRA", ""),
        "messages_day":   None,  # unlimited
        "history_days":   None,  # unlimited
        "models":         ["claude-sonnet-4-6", "claude-opus-4-6", "gpt-4o", "gpt-4o-mini"],
        "memory":         True,
        "code_mode":      True,
        "web_search":     True,
        "api_access":     True,
    },
}

# ─── Profile helpers ─────────────────────────────────────────────────────────

def get_profile(user_id: str) -> Optional[dict]:
    """Fetch user profile from Supabase."""
    try:
        sb = get_supabase()
        res = sb.table("profiles").select("*").eq("id", user_id).single().execute()
        return res.data
    except Exception as e:
        log.error(f"get_profile({user_id}): {e}")
        return None


def get_profile_by_email(email: str) -> Optional[dict]:
    try:
        sb = get_supabase()
        res = sb.table("profiles").select("*").eq("email", email).single().execute()
        return res.data
    except Exception as e:
        log.error(f"get_profile_by_email({email}): {e}")
        return None


def update_profile(user_id: str, data: dict) -> bool:
    try:
        sb = get_supabase()
        sb.table("profiles").update(data).eq("id", user_id).execute()
        return True
    except Exception as e:
        log.error(f"update_profile({user_id}): {e}")
        return False

# ─── Message quota ───────────────────────────────────────────────────────────

def increment_usage_via_rpc(user_id: str) -> Optional[int]:
    """Atomically increment messages_used_today via the Postgres RPC.

    Returns the new count, or None if the RPC isn't available (function
    missing on the live DB, or transport error). Caller decides 402 by
    comparing against TIER_CONFIG[tier].messages_day.

    Apply the SQL function in supabase_schema.sql (search for
    ``increment_message_usage``) before flipping ``NARAI_QUOTA_ENABLED=true``.
    """
    try:
        sb = get_supabase()
        res = sb.rpc("increment_message_usage", {"p_user_id": user_id}).execute()
        return int(res.data) if res.data is not None else None
    except Exception as e:
        log.warning(f"increment_usage_via_rpc({user_id}) failed: {e}")
        return None


def check_and_increment_quota(user_id: str) -> dict:
    """
    Returns {"allowed": bool, "used": int, "limit": int | None, "tier": str}
    Resets daily counter if last_reset_date < today.
    """
    from datetime import date
    try:
        sb = get_supabase()
        profile = get_profile(user_id)
        if not profile:
            return {"allowed": False, "reason": "profile_not_found"}

        tier = profile.get("tier", "free")
        cfg = TIER_CONFIG.get(tier, TIER_CONFIG["free"])
        limit = cfg["messages_day"]  # None = unlimited

        # Reset daily count if needed
        today = date.today().isoformat()
        used = profile.get("messages_used_today", 0)
        last_reset = profile.get("last_reset_date", today)
        if last_reset < today:
            used = 0
            sb.table("profiles").update({
                "messages_used_today": 0,
                "last_reset_date": today
            }).eq("id", user_id).execute()

        # Check limit
        if limit is not None and used >= limit:
            return {
                "allowed": False,
                "reason":  "quota_exceeded",
                "used":    used,
                "limit":   limit,
                "tier":    tier,
            }

        # Increment
        sb.table("profiles").update({
            "messages_used_today": used + 1
        }).eq("id", user_id).execute()

        return {
            "allowed": True,
            "used":    used + 1,
            "limit":   limit,
            "tier":    tier,
        }
    except Exception as e:
        log.error(f"check_and_increment_quota({user_id}): {e}")
        # Fail open — don't block users on DB errors
        return {"allowed": True, "used": 0, "limit": None, "tier": "free"}

# ─── JWT verification ────────────────────────────────────────────────────────

def verify_token(token: str) -> Optional[dict]:
    """
    Verify a Supabase JWT token and return the user payload.
    Returns None if invalid.
    """
    try:
        sb = get_supabase()
        user = sb.auth.get_user(token)
        if user and user.user:
            return {"id": user.user.id, "email": user.user.email}
        return None
    except Exception as e:
        log.warning(f"verify_token failed: {e}")
        return None

# ─── Conversation helpers ────────────────────────────────────────────────────

def create_conversation(user_id: str, title: str = "New Chat") -> Optional[str]:
    """Create a new conversation, return its ID."""
    try:
        sb = get_supabase()
        res = sb.table("conversations").insert({
            "user_id": user_id,
            "title":   title,
        }).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as e:
        log.error(f"create_conversation({user_id}): {e}")
        return None


def list_conversations(user_id: str, limit: int = 50) -> list:
    """Return recent conversations for a user."""
    try:
        sb = get_supabase()
        res = (
            sb.table("conversations")
            .select("id, title, message_count, model_used, updated_at")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.error(f"list_conversations({user_id}): {e}")
        return []


def get_conversation_messages(conversation_id: str, user_id: str, limit: int = 100) -> list:
    """Return messages for a conversation (validates ownership)."""
    try:
        sb = get_supabase()
        # Verify ownership
        conv = sb.table("conversations").select("id").eq("id", conversation_id).eq("user_id", user_id).single().execute()
        if not conv.data:
            return []
        res = (
            sb.table("messages")
            .select("role, content, model_used, created_at")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.error(f"get_conversation_messages({conversation_id}): {e}")
        return []


def save_message(conversation_id: str, user_id: str, role: str, content: str, model_used: str = None) -> bool:
    """Save a message and update conversation title/count."""
    try:
        sb = get_supabase()
        sb.table("messages").insert({
            "conversation_id": conversation_id,
            "user_id":         user_id,
            "role":            role,
            "content":         content,
            "model_used":      model_used,
        }).execute()
        # Update conversation metadata
        sb.table("conversations").update({
            "message_count": sb.rpc("coalesce", {}).execute(),  # handled by trigger
            "updated_at":    "now()",
        }).eq("id", conversation_id).execute()
        return True
    except Exception as e:
        log.error(f"save_message({conversation_id}): {e}")
        return False


def save_messages_batch(conversation_id: str, user_id: str, pairs: list) -> bool:
    """
    Save multiple messages at once.
    pairs = [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    """
    try:
        sb = get_supabase()
        rows = [{
            "conversation_id": conversation_id,
            "user_id":         user_id,
            "role":            p["role"],
            "content":         p["content"],
            "model_used":      p.get("model_used"),
        } for p in pairs]
        sb.table("messages").insert(rows).execute()
        # Update conversation count and timestamp
        sb.table("conversations").update({
            "updated_at": "now()",
        }).eq("id", conversation_id).execute()
        return True
    except Exception as e:
        log.error(f"save_messages_batch({conversation_id}): {e}")
        return False

# ─── Memory helpers ──────────────────────────────────────────────────────────

def get_user_memory(user_id: str) -> list:
    """Return all memory notes for a user."""
    try:
        sb = get_supabase()
        res = (
            sb.table("memory_notes")
            .select("fact, category, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        log.error(f"get_user_memory({user_id}): {e}")
        return []


def add_memory_note(user_id: str, fact: str, category: str = "general", conversation_id: str = None) -> bool:
    """Add a memory note for a user."""
    try:
        sb = get_supabase()
        sb.table("memory_notes").insert({
            "user_id":               user_id,
            "fact":                  fact,
            "category":              category,
            "source_conversation_id": conversation_id,
        }).execute()
        return True
    except Exception as e:
        log.error(f"add_memory_note({user_id}): {e}")
        return False
