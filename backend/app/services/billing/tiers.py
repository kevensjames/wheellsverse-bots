"""Tier registry — the single source of truth for plan metadata.

Replaces the Stage 5 `plans` table (which never existed in prod). Stripe is
the authoritative source for what was BOUGHT (price IDs); this registry is
the authoritative source for what each tier MEANS to NAI (display name,
default rate limit, mapping from tier <-> Stripe price ID via env var).

Tier vocabulary matches the prod CHECK constraint on
public.subscriptions.tier (and public.profiles.tier):
    free | pro | max | ultra
"free" only exists on profiles.tier — it's never a subscription row.

Price IDs are resolved LIVE from `settings` (not snapshotted at import) so
that pytest monkeypatching and runtime env reloads both work.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class TierSpec:
    code: str            # canonical tier name (matches profiles.tier CHECK)
    display_name: str    # human-facing label
    predictions_per_day: int  # rate limit; 0 = unlimited


# Static metadata only — price IDs are looked up live via _PRICE_ENV.
TIERS: dict[str, TierSpec] = {
    "free":  TierSpec("free",  "Free",  3),
    "pro":   TierSpec("pro",   "Pro",   999),
    "max":   TierSpec("max",   "Max",   999),
    "ultra": TierSpec("ultra", "Ultra", 999),
}


# Tier → env-var name on `settings`. Used by price_id_for / tier_for_price_id
# so monkeypatching settings.STRIPE_PRICE_PRO in tests takes effect immediately.
_PRICE_ENV: dict[str, str | None] = {
    "free":  None,
    "pro":   "STRIPE_PRICE_PRO",
    "max":   "STRIPE_PRICE_MAX",
    "ultra": "STRIPE_PRICE_ULTRA",
}


# ── helpers ─────────────────────────────────────────────────────────────


def get(tier_code: str) -> TierSpec | None:
    """Return the TierSpec for a tier code, or None if unknown."""
    return TIERS.get(tier_code)


def price_id_for(tier_code: str) -> str | None:
    """Stripe price ID for a tier, or None if the tier isn't configured.
    Reads `settings` live so env changes take effect on next call."""
    env_key = _PRICE_ENV.get(tier_code)
    if not env_key:
        return None
    return getattr(settings, env_key, "") or None


def tier_for_price_id(price_id: str | None) -> str | None:
    """Reverse map: Stripe price ID → tier code. Used by the webhook handler
    to decide what tier a checkout.session.completed event activates."""
    if not price_id:
        return None
    for tier_code, env_key in _PRICE_ENV.items():
        if env_key and getattr(settings, env_key, "") == price_id:
            return tier_code
    return None


def all_paid_tiers_configured() -> dict[str, bool]:
    """Diagnostic: which paid tiers have a Stripe price ID wired?"""
    return {
        code: bool(price_id_for(code))
        for code in TIERS
        if code != "free"
    }
