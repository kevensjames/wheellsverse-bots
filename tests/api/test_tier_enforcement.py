"""Week 2 acceptance — tier dependencies + chat-level enforcement helpers.

Covers:
  1. get_user_tier returns the profile's tier
  2. get_user_tier caches (second call doesn't re-hit Supabase)
  3. require_tier('pro') with free user raises 403
  4. require_tier('pro') with pro user passes
  5. model_allowed_for_tier matches TIER_CONFIG
  6. _enforce_model_whitelist raises 403 on violation
  7. _enforce_quota raises 402 when over limit (with feature flag on)
  8. _enforce_quota is a no-op when NARAI_QUOTA_ENABLED is off
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from core import narai_user
from narai.api.dependencies import tier as tier_dep
from narai.api.routes.chat import _enforce_model_whitelist, _enforce_quota


@pytest.fixture(autouse=True)
def _clear_tier_cache():
    """Reset the get_user_tier TTL cache between tests."""
    tier_dep._cache.clear()
    yield
    tier_dep._cache.clear()


@pytest.fixture
def mock_get_profile(monkeypatch):
    """Helper: stub core.narai_user.get_profile to return a chosen tier."""
    calls = {"count": 0}

    def install(tier_value: str | None):
        def _get_profile(user_id):
            calls["count"] += 1
            return {"id": user_id, "tier": tier_value} if tier_value is not None else None
        monkeypatch.setattr(narai_user, "get_profile", _get_profile)
        return calls

    return install


def test_get_user_tier_returns_profile_tier(mock_get_profile):
    mock_get_profile("pro")
    assert tier_dep.get_user_tier(user_id="alice") == "pro"


def test_get_user_tier_caches(mock_get_profile):
    calls = mock_get_profile("max")
    tier_dep.get_user_tier(user_id="bob")
    tier_dep.get_user_tier(user_id="bob")
    tier_dep.get_user_tier(user_id="bob")
    assert calls["count"] == 1, (
        f"expected 1 DB hit, got {calls['count']} — cache is broken"
    )


def test_get_user_tier_defaults_to_free_when_profile_missing(mock_get_profile):
    mock_get_profile(None)
    assert tier_dep.get_user_tier(user_id="ghost") == "free"


def test_require_tier_blocks_free_when_pro_required(mock_get_profile):
    mock_get_profile("free")
    dep = tier_dep.require_tier("pro")
    with pytest.raises(HTTPException) as exc:
        dep(tier=tier_dep.get_user_tier(user_id="alice"))
    assert exc.value.status_code == 403
    assert "tier >= pro" in exc.value.detail


def test_require_tier_passes_when_user_at_or_above(mock_get_profile):
    mock_get_profile("max")
    dep = tier_dep.require_tier("pro")
    result = dep(tier=tier_dep.get_user_tier(user_id="alice"))
    assert result == "max"


def test_require_tier_rejects_unknown_min_tier():
    with pytest.raises(ValueError):
        tier_dep.require_tier("godmode")


def test_model_allowed_for_tier_matches_config():
    # Spot-check the 4 documented tiers
    assert tier_dep.model_allowed_for_tier("claude-haiku-4-5-20251001", "free") is True
    assert tier_dep.model_allowed_for_tier("claude-opus-4-6", "free") is False
    assert tier_dep.model_allowed_for_tier("claude-sonnet-4-6", "pro") is True
    assert tier_dep.model_allowed_for_tier("claude-opus-4-6", "max") is True
    assert tier_dep.model_allowed_for_tier("claude-opus-4-6", "ultra") is True


# ── Week 2.5: provider-prefix normalization + preview_model ────────────────


def test_strip_provider_prefix_normalizes_litellm_names():
    """The router formats model names like 'claude/<name>' (litellm convention).
    TIER_CONFIG lists bare names. Strip ensures both match."""
    assert tier_dep._strip_provider_prefix("claude/claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"
    assert tier_dep._strip_provider_prefix("openai/gpt-4o") == "gpt-4o"
    assert tier_dep._strip_provider_prefix("ollama/llama3.2") == "llama3.2"
    # Bare names (no prefix) pass through unchanged
    assert tier_dep._strip_provider_prefix("gpt-4o-mini") == "gpt-4o-mini"
    assert tier_dep._strip_provider_prefix("claude-sonnet-4-6") == "claude-sonnet-4-6"
    # Edge: empty string
    assert tier_dep._strip_provider_prefix("") == ""


def test_model_allowed_for_tier_handles_provider_prefix():
    """Bug regression: Week 2's whitelist check failed for prefixed model names
    because TIER_CONFIG stores them bare. Week 2.5 normalizes both sides."""
    # Prefixed names should now match — these were the silent 403 bug
    assert tier_dep.model_allowed_for_tier("claude/claude-haiku-4-5-20251001", "free") is True
    assert tier_dep.model_allowed_for_tier("claude/claude-sonnet-4-6", "pro") is True
    assert tier_dep.model_allowed_for_tier("claude/claude-opus-4-6", "max") is True
    assert tier_dep.model_allowed_for_tier("openai/gpt-4o", "pro") is True
    # Disallowed combos still fail (prefix doesn't help)
    assert tier_dep.model_allowed_for_tier("claude/claude-opus-4-6", "free") is False


def test_preview_model_returns_primary_for_tier(monkeypatch):
    """preview_model must return what call()/stream() would dispatch to
    without invoking any LLM. Mirrors RouterConfig.primary_fast / primary_deep."""
    from infra.brain import router as router_mod

    # Use the default config's primaries (FAST_MODELS[0], DEEP_MODELS[0])
    fast_primary = router_mod._config.primary_fast
    deep_primary = router_mod._config.primary_deep
    assert router_mod.preview_model("fast") == fast_primary
    assert router_mod.preview_model("deep") == deep_primary

    # Unknown tier defaults to deep (mirrors stream()'s default tier="deep")
    assert router_mod.preview_model("medium") == deep_primary
    assert router_mod.preview_model("anything-else") == deep_primary


def test_preview_model_respects_env_overrides(monkeypatch):
    """If NARAI_FAST_MODEL / NARAI_DEEP_MODEL env vars set the primary,
    preview_model reflects that (so whitelist checks against a deployment's
    actual configured model, not just the default)."""
    from infra.brain import router as router_mod

    # Swap in a temporary RouterConfig with custom primaries
    custom = router_mod.RouterConfig(
        primary_fast="claude/claude-haiku-test",
        primary_deep="claude/claude-opus-test",
    )
    monkeypatch.setattr(router_mod, "_config", custom)
    assert router_mod.preview_model("fast") == "claude/claude-haiku-test"
    assert router_mod.preview_model("deep") == "claude/claude-opus-test"


def test_preview_model_chained_with_whitelist_blocks_disallowed_tier():
    """End-to-end: this is the chain chat_stream uses to enforce."""
    from infra.brain import router as router_mod

    previewed = router_mod.preview_model("deep")  # default = "claude/claude-sonnet-4-6"
    # A free user's whitelist doesn't allow sonnet → whitelist must say False
    assert tier_dep.model_allowed_for_tier(previewed, "free") is False
    # A max user's whitelist DOES allow sonnet → True
    assert tier_dep.model_allowed_for_tier(previewed, "max") is True


def test_enforce_model_whitelist_passes_on_match():
    # Should not raise
    _enforce_model_whitelist("claude-haiku-4-5-20251001", "free", "alice")


def test_enforce_model_whitelist_raises_403_on_mismatch():
    with pytest.raises(HTTPException) as exc:
        _enforce_model_whitelist("claude-opus-4-6", "free", "alice")
    assert exc.value.status_code == 403
    assert "not available on tier" in exc.value.detail


def test_enforce_quota_no_op_when_disabled(monkeypatch):
    monkeypatch.setenv("NARAI_QUOTA_ENABLED", "false")
    # Even with an over-limit RPC stub, disabled flag means no enforcement
    monkeypatch.setattr(
        narai_user, "increment_usage_via_rpc", lambda uid: 99999
    )
    # Should not raise
    _enforce_quota("alice", "free")


def test_enforce_quota_raises_402_when_over_limit(monkeypatch):
    monkeypatch.setenv("NARAI_QUOTA_ENABLED", "true")
    # free tier limit is 10 messages/day; return 11
    import narai.api.routes.chat as chat_module
    monkeypatch.setattr(chat_module, "increment_usage_via_rpc", lambda uid: 11)
    with pytest.raises(HTTPException) as exc:
        _enforce_quota("alice", "free")
    assert exc.value.status_code == 402
    assert "daily message limit reached" in exc.value.detail


def test_enforce_quota_passes_when_under_limit(monkeypatch):
    monkeypatch.setenv("NARAI_QUOTA_ENABLED", "true")
    import narai.api.routes.chat as chat_module
    monkeypatch.setattr(chat_module, "increment_usage_via_rpc", lambda uid: 5)
    # Should not raise
    _enforce_quota("alice", "free")


def test_enforce_quota_unlimited_tier_skips_check(monkeypatch):
    monkeypatch.setenv("NARAI_QUOTA_ENABLED", "true")
    # ultra has messages_day=None (unlimited). Even with an RPC stub that
    # would say "over", the limit=None short-circuit means no enforcement.
    rpc_called = {"yes": False}
    def _rpc(uid):
        rpc_called["yes"] = True
        return 999999
    import narai.api.routes.chat as chat_module
    monkeypatch.setattr(chat_module, "increment_usage_via_rpc", _rpc)
    _enforce_quota("alice", "ultra")
    assert rpc_called["yes"] is False, (
        "unlimited tier should not even call the RPC"
    )


def test_enforce_quota_fails_open_when_rpc_unavailable(monkeypatch):
    """RPC returning None (function not yet on live DB) → fail open, log warning."""
    monkeypatch.setenv("NARAI_QUOTA_ENABLED", "true")
    import narai.api.routes.chat as chat_module
    monkeypatch.setattr(chat_module, "increment_usage_via_rpc", lambda uid: None)
    # Should not raise — fail-open is the documented behavior
    _enforce_quota("alice", "free")
