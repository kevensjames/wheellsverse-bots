"""Per-request tier resolution + tier-gating dependencies.

`get_user_tier` reads ``public.profiles.tier`` for the authenticated user,
cached for 60 seconds so back-to-back requests don't hammer Supabase. The
threading lock guards concurrent dependency resolution under FastAPI's
async loop.

`require_tier(min_tier)` is a dependency factory that returns a Depends-
injectable which raises 403 when the user's tier is below `min_tier`.

Tier ranking (free < pro < max < ultra) is canonical here; do not duplicate
it in routes. If a future tier is added, update TIER_RANK and the model
whitelist in TIER_CONFIG together.
"""
from __future__ import annotations

import logging
from threading import Lock

from cachetools import TTLCache
from fastapi import Depends, HTTPException

from narai.api.auth import require_auth


log = logging.getLogger("narai.tier")

# Cache TTL is shorter than the BrainClient cache (10 min) because tier
# can change mid-session via a Stripe webhook upgrade — we want the new
# tier visible within ~1 minute, not 10.
_cache: TTLCache = TTLCache(maxsize=512, ttl=60)
_lock = Lock()


TIER_RANK = {"free": 0, "pro": 1, "max": 2, "ultra": 3}


def get_user_tier(user_id: str = Depends(require_auth)) -> str:
    """Look up the authenticated user's tier. Returns 'free' on lookup
    failure (fail-closed-to-cheapest, not fail-open)."""
    with _lock:
        cached = _cache.get(user_id)
        if cached is not None:
            return cached
    try:
        from core.narai_user import get_profile
        profile = get_profile(user_id)
        tier = (profile or {}).get("tier") or "free"
        if tier not in TIER_RANK:
            log.warning(f"unknown tier {tier!r} for user {user_id}, defaulting to free")
            tier = "free"
    except Exception as e:
        log.warning(f"tier lookup failed for {user_id}: {e}; defaulting to free")
        tier = "free"
    with _lock:
        _cache[user_id] = tier
    return tier


def require_tier(min_tier: str):
    """Dependency factory: returns a Depends that raises 403 when the
    user's tier is below ``min_tier``. Usage:

        @rt.post("/code")
        async def code_route(_: str = Depends(require_tier("pro"))):
            ...
    """
    if min_tier not in TIER_RANK:
        raise ValueError(f"unknown min_tier {min_tier!r}")
    min_rank = TIER_RANK[min_tier]

    def _check(tier: str = Depends(get_user_tier)) -> str:
        if TIER_RANK[tier] < min_rank:
            raise HTTPException(
                status_code=403,
                detail=f"this endpoint requires tier >= {min_tier}; current tier is {tier}",
            )
        return tier

    return _check


def model_allowed_for_tier(model: str, tier: str) -> bool:
    """Return True if ``model`` is in ``tier``'s whitelist. Uses
    TIER_CONFIG from core/narai_user.py as the single source of truth."""
    from core.narai_user import TIER_CONFIG
    cfg = TIER_CONFIG.get(tier) or TIER_CONFIG["free"]
    return model in (cfg.get("models") or [])
