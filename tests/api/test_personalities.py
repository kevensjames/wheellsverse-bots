"""Week 4-B acceptance — personality presets module + dependency + routes.

Covers:
  1. All 6 archetypes defined with required fields (slug/name/desc/prompt)
  2. DEFAULT_PERSONALITY_SLUG resolves to a real preset
  3. get_personality fails open to default on unknown/empty slug
  4. modifier_for_personality returns a non-empty fragment for every slug
  5. list_personalities exposes the picker payload (no prompt fragment leaked)
  6. get_user_personality returns the profile's slug
  7. get_user_personality caches (no double DB hit)
  8. get_user_personality fails open to default when profile/column missing
  9. set_user_personality invalidates the cache on success
 10. set_user_personality rejects unknown slugs
"""
from __future__ import annotations

import pytest

from core import narai_user
from narai.api.dependencies import personality as personality_dep
from narai.core.personalities import (
    DEFAULT_PERSONALITY_SLUG,
    PERSONALITIES,
    get_personality,
    list_personalities,
    modifier_for_personality,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    personality_dep._cache.clear()
    yield
    personality_dep._cache.clear()


# ── Personalities module ────────────────────────────────────────────────────


def test_six_archetypes_defined_with_required_fields():
    expected_slugs = {"companion", "coach", "coder", "writer", "trader", "strategist"}
    assert set(PERSONALITIES.keys()) == expected_slugs
    for slug, p in PERSONALITIES.items():
        assert p.slug == slug
        assert p.name
        assert p.description
        assert p.system_prompt_fragment
        # The fragment should explicitly label itself so the LLM knows
        # which preset is active (helps with debugging + telemetry)
        assert "[PERSONALITY:" in p.system_prompt_fragment


def test_default_slug_resolves_to_real_preset():
    assert DEFAULT_PERSONALITY_SLUG in PERSONALITIES


def test_get_personality_fails_open_to_default_on_unknown():
    assert get_personality(None).slug == DEFAULT_PERSONALITY_SLUG
    assert get_personality("").slug == DEFAULT_PERSONALITY_SLUG
    assert get_personality("not-a-real-archetype").slug == DEFAULT_PERSONALITY_SLUG


def test_get_personality_returns_correct_preset_for_known_slug():
    assert get_personality("coder").slug == "coder"
    assert get_personality("companion").slug == "companion"


def test_modifier_for_personality_returns_non_empty_fragment_for_every_slug():
    for slug in PERSONALITIES:
        frag = modifier_for_personality(slug)
        assert frag, f"empty fragment for {slug}"
        assert "[PERSONALITY:" in frag


def test_list_personalities_excludes_prompt_fragment():
    """Picker UI only needs slug/name/description — don't leak the prompt
    text (could be long; also reduces accidental over-exposure)."""
    listing = list_personalities()
    assert len(listing) == 6
    for item in listing:
        assert set(item.keys()) == {"slug", "name", "description"}
        assert "system_prompt_fragment" not in item


# ── get_user_personality (TTL-cached resolver) ─────────────────────────────


@pytest.fixture
def mock_get_profile(monkeypatch):
    """Stub core.narai_user.get_profile, counting calls so cache hits
    can be verified."""
    calls = {"count": 0}

    def install(personality_value):
        def _get_profile(user_id):
            calls["count"] += 1
            if personality_value is None:
                return None  # simulate column missing OR profile missing
            return {"id": user_id, "personality": personality_value}
        monkeypatch.setattr(narai_user, "get_profile", _get_profile)
        return calls

    return install


def test_get_user_personality_returns_profile_value(mock_get_profile):
    mock_get_profile("coder")
    assert personality_dep.get_user_personality(user_id="alice") == "coder"


def test_get_user_personality_caches(mock_get_profile):
    calls = mock_get_profile("strategist")
    personality_dep.get_user_personality(user_id="bob")
    personality_dep.get_user_personality(user_id="bob")
    personality_dep.get_user_personality(user_id="bob")
    assert calls["count"] == 1, (
        f"expected 1 DB hit, got {calls['count']} — cache broken"
    )


def test_get_user_personality_defaults_when_profile_missing(mock_get_profile):
    mock_get_profile(None)
    assert personality_dep.get_user_personality(user_id="ghost") == DEFAULT_PERSONALITY_SLUG


def test_get_user_personality_defaults_when_column_missing(monkeypatch):
    """Profile exists but personality column doesn't (migration not applied)
    → query returns row without personality key → fail open to default."""
    def _get_profile(user_id):
        return {"id": user_id, "email": "x@y.com", "tier": "free"}  # no personality
    monkeypatch.setattr(narai_user, "get_profile", _get_profile)
    assert personality_dep.get_user_personality(user_id="alice") == DEFAULT_PERSONALITY_SLUG


def test_get_user_personality_defaults_on_unknown_value(monkeypatch):
    """Profile has a personality value that isn't one of the 6 — guard
    against schema drift or manual SQL edits putting bad data in the column."""
    def _get_profile(user_id):
        return {"id": user_id, "personality": "rogue-archetype-from-future"}
    monkeypatch.setattr(narai_user, "get_profile", _get_profile)
    assert personality_dep.get_user_personality(user_id="alice") == DEFAULT_PERSONALITY_SLUG


def test_get_user_personality_defaults_on_db_error(monkeypatch):
    def _get_profile(user_id):
        raise RuntimeError("supabase down")
    monkeypatch.setattr(narai_user, "get_profile", _get_profile)
    assert personality_dep.get_user_personality(user_id="alice") == DEFAULT_PERSONALITY_SLUG


# ── set_user_personality (write + cache-invalidate) ────────────────────────


def test_set_user_personality_invalidates_cache_on_success(monkeypatch):
    """After a successful write, the next get_user_personality must read
    the new value, not the stale cache."""
    state = {"value": "companion"}

    def _get_profile(user_id):
        return {"id": user_id, "personality": state["value"]}

    def _update_profile(user_id, data):
        state["value"] = data["personality"]
        return True

    monkeypatch.setattr(narai_user, "get_profile", _get_profile)
    monkeypatch.setattr(narai_user, "update_profile", _update_profile)

    # Warm cache with the old value
    assert personality_dep.get_user_personality(user_id="alice") == "companion"
    # Switch personality
    assert personality_dep.set_user_personality("alice", "coder") is True
    # Cache should be invalidated → next read returns new value
    assert personality_dep.get_user_personality(user_id="alice") == "coder"


def test_set_user_personality_rejects_unknown_slug():
    """Bad input is caught before hitting the DB."""
    assert personality_dep.set_user_personality("alice", "not-a-real-archetype") is False
    assert personality_dep.set_user_personality("alice", "") is False


def test_set_user_personality_returns_false_when_update_fails(monkeypatch):
    """Persistence failure surfaces as False so the route can return 503."""
    monkeypatch.setattr(narai_user, "update_profile", lambda *a, **kw: False)
    assert personality_dep.set_user_personality("alice", "coder") is False


def test_set_user_personality_returns_false_on_exception(monkeypatch):
    def _update_profile(user_id, data):
        raise RuntimeError("column doesn't exist")
    monkeypatch.setattr(narai_user, "update_profile", _update_profile)
    assert personality_dep.set_user_personality("alice", "coder") is False
