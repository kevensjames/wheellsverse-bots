"""Per-request personality resolution + selection helper.

`get_user_personality` reads ``public.profiles.personality`` for the
authenticated user, cached for 60 seconds so back-to-back chat turns
don't hammer Supabase. Mirrors the get_user_tier pattern from
narai/api/dependencies/tier.py.

`set_user_personality` is the write-side counterpart used by the
POST /personalities/select route.

Fail-open: if the ``personality`` column doesn't exist yet on the live
DB (migration deferred behind GitHub-flag dashboard access), the
read returns the default slug. Writes log a warning and return False,
so the route can surface a clean error to the client.
"""
from __future__ import annotations

import logging
from threading import Lock

from cachetools import TTLCache
from fastapi import Depends

from narai.api.auth import require_auth
from narai.core.personalities import (
    DEFAULT_PERSONALITY_SLUG,
    PERSONALITIES,
)


log = logging.getLogger("narai.personality")

# 60s TTL same as get_user_tier — personality can change mid-session via
# the POST /personalities/select route; the cache is invalidated explicitly
# by set_user_personality on successful update.
_cache: TTLCache = TTLCache(maxsize=512, ttl=60)
_lock = Lock()


def get_user_personality(user_id: str = Depends(require_auth)) -> str:
    """Return the user's selected personality slug. Defaults to the
    DEFAULT_PERSONALITY_SLUG ("companion") when no profile/column/value
    is present — fail-open so the chat pipeline never breaks on this."""
    with _lock:
        cached = _cache.get(user_id)
        if cached is not None:
            return cached
    try:
        from core.narai_user import get_profile
        profile = get_profile(user_id)
        slug = (profile or {}).get("personality") or DEFAULT_PERSONALITY_SLUG
        if slug not in PERSONALITIES:
            log.warning(
                f"unknown personality {slug!r} for user {user_id}, "
                f"defaulting to {DEFAULT_PERSONALITY_SLUG}"
            )
            slug = DEFAULT_PERSONALITY_SLUG
    except Exception as e:
        log.warning(
            f"personality lookup failed for {user_id}: {e}; "
            f"defaulting to {DEFAULT_PERSONALITY_SLUG}"
        )
        slug = DEFAULT_PERSONALITY_SLUG
    with _lock:
        _cache[user_id] = slug
    return slug


def set_user_personality(user_id: str, slug: str) -> bool:
    """Persist a new personality choice. Returns True on success, False
    on failure (column missing, DB error, unknown slug). The route layer
    decides how to surface failures to the client."""
    if slug not in PERSONALITIES:
        log.info(f"set_user_personality rejected unknown slug {slug!r}")
        return False
    try:
        from core.narai_user import update_profile
        ok = update_profile(user_id, {"personality": slug})
        if ok:
            # Invalidate cache so the next get_user_personality reflects
            # the new value immediately (don't wait for TTL).
            with _lock:
                _cache.pop(user_id, None)
            return True
        return False
    except Exception as e:
        log.warning(f"set_user_personality failed for {user_id}: {e}")
        return False
