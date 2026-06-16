"""NAI subscription bridge — Stripe → Supabase profiles.tier upgrades.

Mirrors the architecture of telegram_subscription.py and discord_subscription.py:
the main /api/stripe/webhook handler in core/api.py dispatches relevant events
into the handle_* functions defined here.

Scope: only acts on prices matching STRIPE_PRICE_PRO / STRIPE_PRICE_MAX /
STRIPE_PRICE_ULTRA. Other prices (Shopify-merchant tiers, Telegram circle,
Bot Pack, Discord paid role) are skipped — they have their own handlers.

Idempotency: profiles.tier UPDATE is naturally idempotent; the subscriptions
table has UNIQUE(stripe_subscription_id) so UPSERT replaces duplicates safely.
A Stripe retry of the same event re-applies the same tier — harmless.

Downgrade timing: cancel_at_period_end=True is recorded but the tier stays
until Stripe sends customer.subscription.deleted (which fires when the
cancellation actually takes effect — usually at period end). Industry-
standard SaaS behavior: paid period, served period.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("narai.nai_subscription")


# ─── Price ↔ Tier mapping ────────────────────────────────────────────────────

def _tier_for_price(price_id: Optional[str]) -> Optional[str]:
    """Return the NAI tier name for a Stripe price ID, or None if the price
    isn't one of our 3 NAI prices. Lets the webhook dispatcher silently
    skip non-NAI subscription events (Shopify merchant tiers, etc.)."""
    if not price_id:
        return None
    if price_id == os.getenv("STRIPE_PRICE_PRO", ""):
        return "pro"
    if price_id == os.getenv("STRIPE_PRICE_MAX", ""):
        return "max"
    if price_id == os.getenv("STRIPE_PRICE_ULTRA", ""):
        return "ultra"
    return None


def _extract_price_id(subscription: dict) -> str:
    """Pull the line-item price ID out of a Stripe subscription object."""
    items = (subscription.get("items") or {}).get("data") or []
    if not items:
        return ""
    return ((items[0].get("price") or {}).get("id")) or ""


def _ts_to_iso(ts: Optional[int]) -> Optional[str]:
    """Stripe sends Unix seconds; Supabase wants ISO timestamptz."""
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


# ─── Customer → profile resolution ───────────────────────────────────────────

def _associate_customer(customer_id: str, email: str) -> Optional[dict]:
    """Look up the profile matching this Stripe customer. Prefer
    profiles.stripe_customer_id; fall back to email; on first match by
    email, persist the Stripe customer ID so future events resolve quickly.

    Returns the profile dict or None if no match.
    """
    from core.narai_user import get_supabase, get_profile_by_email, update_profile

    if not customer_id:
        return None
    try:
        sb = get_supabase()
        res = (
            sb.table("profiles")
            .select("*")
            .eq("stripe_customer_id", customer_id)
            .execute()
        )
        if res.data:
            return res.data[0]
        # Fall back to email lookup + persist the link
        if email:
            prof = get_profile_by_email(email)
            if prof:
                update_profile(prof["id"], {"stripe_customer_id": customer_id})
                log.info(
                    f"linked stripe customer={customer_id[:14]}… → profile={prof['id']}"
                )
                return {**prof, "stripe_customer_id": customer_id}
        log.warning(
            f"no profile match for stripe customer={customer_id[:14]}… email={email!r}"
        )
        return None
    except Exception as e:
        log.error(f"_associate_customer failed: {e}")
        return None


def _profile_by_customer_id(customer_id: str) -> Optional[dict]:
    """Look up profile by Stripe customer ID only — used by subscription
    events that don't carry an email. Returns None if no profile linked
    (which should be rare — checkout.session.completed normally lands
    first and creates the association)."""
    from core.narai_user import get_supabase

    if not customer_id:
        return None
    try:
        sb = get_supabase()
        res = (
            sb.table("profiles")
            .select("*")
            .eq("stripe_customer_id", customer_id)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        log.error(f"_profile_by_customer_id failed: {e}")
        return None


# ─── Tier application + subscription mirror ─────────────────────────────────

def _apply_tier(profile_id: str, tier: str, subscription: dict) -> None:
    """Update profiles.tier + upsert the subscriptions row. Two REST calls;
    not transactional, but profiles.tier is the source of truth — the
    subscriptions table is a mirror for audit/portal."""
    from core.narai_user import get_supabase, update_profile

    update_profile(profile_id, {"tier": tier})
    try:
        sb = get_supabase()
        sb.table("subscriptions").upsert(
            {
                "user_id": profile_id,
                "tier": tier,
                "stripe_subscription_id": subscription.get("id"),
                "stripe_price_id": _extract_price_id(subscription),
                "status": subscription.get("status", "active"),
                "cancel_at_period_end": subscription.get("cancel_at_period_end", False),
                "current_period_start": _ts_to_iso(subscription.get("current_period_start")),
                "current_period_end": _ts_to_iso(subscription.get("current_period_end")),
            },
            on_conflict="stripe_subscription_id",
        ).execute()
    except Exception as e:
        log.warning(f"subscriptions upsert failed (non-fatal): {e}")


# ─── Public webhook handlers (called by core/api.py:stripe_webhook) ─────────

def handle_checkout_completed(session: dict) -> Optional[dict]:
    """On checkout.session.completed: associate the Stripe customer with our
    profile (so future events can be resolved). The actual tier upgrade
    happens via customer.subscription.created/updated which arrives separately
    and carries the price ID natively.

    Returns the profile dict (now linked) or None.
    """
    customer = session.get("customer") or ""
    email = (
        (session.get("customer_details") or {}).get("email")
        or session.get("customer_email")
        or ""
    )
    profile = _associate_customer(customer, email)
    if profile:
        log.info(
            f"checkout.session.completed: customer={customer[:14]}… → user={profile['id']}"
        )
    return profile


def handle_subscription_updated(subscription: dict) -> Optional[dict]:
    """customer.subscription.created and customer.subscription.updated both
    land here. Extract the price ID, map to tier, apply. Non-NAI prices
    are skipped (returns None).

    Returns the updated profile (with new tier) or None.
    """
    price_id = _extract_price_id(subscription)
    tier = _tier_for_price(price_id)
    if tier is None:
        return None  # not an NAI subscription — let other dispatchers handle
    customer = subscription.get("customer") or ""
    profile = _profile_by_customer_id(customer)
    if not profile:
        log.warning(
            f"subscription.updated for unlinked customer={customer[:14]}… "
            f"price={price_id} tier={tier} — was checkout.session.completed missed?"
        )
        return None
    _apply_tier(profile["id"], tier, subscription)
    log.info(
        f"tier upgraded: user={profile['id']} tier={tier} "
        f"sub={subscription.get('id', '')[:14]}…"
    )
    return {**profile, "tier": tier}


def handle_subscription_deleted(subscription: dict) -> Optional[dict]:
    """customer.subscription.deleted fires when the cancellation actually
    takes effect (either immediately or at period end, depending on how
    the cancel was scheduled). Downgrade to free.

    Returns the updated profile or None.
    """
    price_id = _extract_price_id(subscription)
    if _tier_for_price(price_id) is None:
        return None  # not an NAI subscription
    customer = subscription.get("customer") or ""
    profile = _profile_by_customer_id(customer)
    if not profile:
        log.warning(
            f"subscription.deleted for unlinked customer={customer[:14]}…"
        )
        return None
    from core.narai_user import get_supabase, update_profile

    update_profile(profile["id"], {"tier": "free"})
    try:
        sb = get_supabase()
        sb.table("subscriptions").update({"status": "canceled"}).eq(
            "stripe_subscription_id", subscription.get("id", "")
        ).execute()
    except Exception as e:
        log.warning(f"subscriptions status update failed (non-fatal): {e}")
    log.info(f"tier downgraded to free: user={profile['id']}")
    return {**profile, "tier": "free"}
