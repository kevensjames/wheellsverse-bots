"""Week 3 acceptance — Stripe → Supabase tier upgrade bridge.

Covers:
  1. _tier_for_price maps STRIPE_PRICE_{PRO,MAX,ULTRA} env vars → tier names
  2. _tier_for_price returns None for non-NAI price IDs
  3. _extract_price_id pulls from subscription.items.data[0].price.id
  4. _ts_to_iso converts Unix seconds → ISO timestamptz
  5. handle_checkout_completed links Stripe customer to existing profile
  6. handle_checkout_completed returns None for unknown email
  7. handle_subscription_updated upgrades tier on matching NAI price
  8. handle_subscription_updated skips non-NAI prices (returns None)
  9. handle_subscription_updated for unlinked customer returns None
 10. handle_subscription_deleted downgrades to free
 11. handle_subscription_deleted skips non-NAI prices
 12. Idempotency: re-running handle_subscription_updated produces same result
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from core import narai_user
from narai.integrations import nai_subscription as nai


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _set_stripe_prices(monkeypatch):
    """Pin known price IDs for the env-var lookups."""
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_test_pro")
    monkeypatch.setenv("STRIPE_PRICE_MAX", "price_test_max")
    monkeypatch.setenv("STRIPE_PRICE_ULTRA", "price_test_ultra")


class _FakeSupabaseTable:
    """Recording shim — captures all calls + returns scripted responses."""

    def __init__(self, parent, name: str):
        self.parent = parent
        self.name = name
        self._select_cols = None
        self._eq_filters: list = []
        self._upsert_payload = None
        self._update_payload = None
        self._on_conflict = None

    def select(self, cols):
        self._select_cols = cols
        return self

    def eq(self, col, val):
        self._eq_filters.append((col, val))
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._upsert_payload = payload
        self._on_conflict = on_conflict
        return self

    def execute(self):
        # Log the call for assertion
        self.parent.calls.append({
            "table": self.name,
            "select": self._select_cols,
            "eq": list(self._eq_filters),
            "update": self._update_payload,
            "upsert": self._upsert_payload,
            "on_conflict": self._on_conflict,
        })
        # Return scripted data for select-by-stripe_customer_id queries
        if self._select_cols and any(f[0] == "stripe_customer_id" for f in self._eq_filters):
            cid = dict(self._eq_filters)["stripe_customer_id"]
            row = self.parent.profile_by_customer.get(cid)
            return SimpleNamespace(data=[row] if row else [])
        return SimpleNamespace(data=[])


class _FakeSupabase:
    """Minimal Supabase client shim. Tests script profile_by_customer to
    control what profiles "exist" for stripe_customer_id lookups."""

    def __init__(self):
        self.calls: list = []
        self.profile_by_customer: dict = {}  # customer_id → profile dict
        self.profile_by_email: dict = {}     # email → profile dict

    def table(self, name: str):
        return _FakeSupabaseTable(self, name)


@pytest.fixture
def fake_sb(monkeypatch):
    """Returns a _FakeSupabase shim. Wires get_supabase, get_profile_by_email,
    and update_profile to use it."""
    fake = _FakeSupabase()
    monkeypatch.setattr(narai_user, "get_supabase", lambda: fake)
    monkeypatch.setattr(
        narai_user, "get_profile_by_email",
        lambda email: fake.profile_by_email.get(email)
    )
    update_calls: list = []
    def _update(user_id, data):
        update_calls.append({"user_id": user_id, "data": data})
        # Also reflect in profile_by_customer for subsequent lookups
        for prof in fake.profile_by_customer.values():
            if prof["id"] == user_id:
                prof.update(data)
        return True
    monkeypatch.setattr(narai_user, "update_profile", _update)
    fake.update_calls = update_calls
    return fake


# ── Unit: _tier_for_price ─────────────────────────────────────────────────


def test_tier_for_price_maps_known_env_vars():
    assert nai._tier_for_price("price_test_pro") == "pro"
    assert nai._tier_for_price("price_test_max") == "max"
    assert nai._tier_for_price("price_test_ultra") == "ultra"


def test_tier_for_price_returns_none_for_unknown():
    assert nai._tier_for_price("price_some_other_product") is None
    assert nai._tier_for_price("price_shopify_starter") is None


def test_tier_for_price_returns_none_for_empty():
    assert nai._tier_for_price("") is None
    assert nai._tier_for_price(None) is None


def test_tier_for_price_returns_none_when_env_var_empty(monkeypatch):
    """If STRIPE_PRICE_PRO isn't set in env, an empty string isn't 'pro'."""
    monkeypatch.setenv("STRIPE_PRICE_PRO", "")
    assert nai._tier_for_price("") is None


# ── Unit: _extract_price_id ────────────────────────────────────────────────


def test_extract_price_id_from_well_formed_subscription():
    sub = {"items": {"data": [{"price": {"id": "price_abc"}}]}}
    assert nai._extract_price_id(sub) == "price_abc"


def test_extract_price_id_empty_subscription():
    assert nai._extract_price_id({}) == ""
    assert nai._extract_price_id({"items": {}}) == ""
    assert nai._extract_price_id({"items": {"data": []}}) == ""


# ── Unit: _ts_to_iso ───────────────────────────────────────────────────────


def test_ts_to_iso_converts_unix_seconds():
    # 1700000000 = 2023-11-14T22:13:20+00:00
    out = nai._ts_to_iso(1700000000)
    assert out is not None
    assert "2023-11-14" in out
    assert out.endswith("+00:00")


def test_ts_to_iso_returns_none_for_none():
    assert nai._ts_to_iso(None) is None


# ── handle_checkout_completed ──────────────────────────────────────────────


def test_checkout_completed_links_existing_profile_by_email(fake_sb):
    """First checkout: customer not yet linked, but profile exists by email.
    Should find by email and persist the stripe_customer_id."""
    fake_sb.profile_by_email["alice@x.com"] = {
        "id": "user-uuid-alice",
        "email": "alice@x.com",
        "tier": "free",
    }
    session = {
        "customer": "cus_alice123",
        "customer_email": "alice@x.com",
    }
    result = nai.handle_checkout_completed(session)
    assert result is not None
    assert result["id"] == "user-uuid-alice"
    assert result["stripe_customer_id"] == "cus_alice123"
    # Verify update_profile was called to persist the link
    assert any(
        c["user_id"] == "user-uuid-alice"
        and c["data"].get("stripe_customer_id") == "cus_alice123"
        for c in fake_sb.update_calls
    )


def test_checkout_completed_returns_none_for_unknown_email(fake_sb):
    """No profile matches the email → return None (logs warning)."""
    session = {
        "customer": "cus_stranger999",
        "customer_email": "stranger@x.com",
    }
    result = nai.handle_checkout_completed(session)
    assert result is None


def test_checkout_completed_handles_customer_details_email(fake_sb):
    """Real Stripe sessions sometimes carry the email under
    customer_details.email instead of customer_email."""
    fake_sb.profile_by_email["bob@x.com"] = {
        "id": "user-uuid-bob",
        "email": "bob@x.com",
        "tier": "free",
    }
    session = {
        "customer": "cus_bob456",
        "customer_details": {"email": "bob@x.com"},
    }
    result = nai.handle_checkout_completed(session)
    assert result is not None
    assert result["id"] == "user-uuid-bob"


# ── handle_subscription_updated ────────────────────────────────────────────


def test_subscription_updated_upgrades_tier_for_nai_price(fake_sb):
    """Linked customer + NAI price → upgrade profile tier."""
    fake_sb.profile_by_customer["cus_alice123"] = {
        "id": "user-uuid-alice",
        "email": "alice@x.com",
        "stripe_customer_id": "cus_alice123",
        "tier": "free",
    }
    subscription = {
        "id": "sub_alice_pro_001",
        "customer": "cus_alice123",
        "status": "active",
        "cancel_at_period_end": False,
        "current_period_start": 1700000000,
        "current_period_end": 1702592000,
        "items": {"data": [{"price": {"id": "price_test_pro"}}]},
    }
    result = nai.handle_subscription_updated(subscription)
    assert result is not None
    assert result["tier"] == "pro"
    assert result["id"] == "user-uuid-alice"
    # Verify profiles.tier was updated
    assert any(
        c["user_id"] == "user-uuid-alice" and c["data"].get("tier") == "pro"
        for c in fake_sb.update_calls
    )
    # Verify subscriptions table got an upsert
    upserts = [c for c in fake_sb.calls if c["table"] == "subscriptions" and c["upsert"]]
    assert len(upserts) == 1
    assert upserts[0]["upsert"]["tier"] == "pro"
    assert upserts[0]["upsert"]["stripe_subscription_id"] == "sub_alice_pro_001"
    assert upserts[0]["on_conflict"] == "stripe_subscription_id"


def test_subscription_updated_skips_non_nai_price(fake_sb):
    """Shopify-merchant or other product subscription → return None,
    DON'T touch profiles.tier."""
    subscription = {
        "id": "sub_shopify_001",
        "customer": "cus_someone",
        "status": "active",
        "items": {"data": [{"price": {"id": "price_some_shopify_thing"}}]},
    }
    result = nai.handle_subscription_updated(subscription)
    assert result is None
    # Verify NO profile updates happened
    assert fake_sb.update_calls == []


def test_subscription_updated_for_unlinked_customer_returns_none(fake_sb):
    """customer_id has no matching profile (checkout.session.completed missed?)
    → return None (logs warning), don't crash."""
    subscription = {
        "id": "sub_orphan_001",
        "customer": "cus_orphan_no_profile",
        "status": "active",
        "items": {"data": [{"price": {"id": "price_test_pro"}}]},
    }
    result = nai.handle_subscription_updated(subscription)
    assert result is None


def test_subscription_updated_handles_max_and_ultra(fake_sb):
    """Verify all 3 tiers map correctly, not just pro."""
    for tier_name, price in [("max", "price_test_max"), ("ultra", "price_test_ultra")]:
        fake_sb.profile_by_customer[f"cus_{tier_name}"] = {
            "id": f"user-uuid-{tier_name}",
            "email": f"{tier_name}@x.com",
            "stripe_customer_id": f"cus_{tier_name}",
            "tier": "free",
        }
        subscription = {
            "id": f"sub_{tier_name}_001",
            "customer": f"cus_{tier_name}",
            "status": "active",
            "items": {"data": [{"price": {"id": price}}]},
        }
        result = nai.handle_subscription_updated(subscription)
        assert result is not None, f"failed to handle {tier_name}"
        assert result["tier"] == tier_name


# ── handle_subscription_deleted ────────────────────────────────────────────


def test_subscription_deleted_downgrades_to_free(fake_sb):
    """Linked NAI subscription gets canceled → profile.tier → free."""
    fake_sb.profile_by_customer["cus_alice123"] = {
        "id": "user-uuid-alice",
        "email": "alice@x.com",
        "stripe_customer_id": "cus_alice123",
        "tier": "pro",
    }
    subscription = {
        "id": "sub_alice_pro_001",
        "customer": "cus_alice123",
        "status": "canceled",
        "items": {"data": [{"price": {"id": "price_test_pro"}}]},
    }
    result = nai.handle_subscription_deleted(subscription)
    assert result is not None
    assert result["tier"] == "free"
    # Verify profile downgrade
    assert any(
        c["user_id"] == "user-uuid-alice" and c["data"].get("tier") == "free"
        for c in fake_sb.update_calls
    )
    # Verify subscriptions row marked canceled (NOT deleted)
    status_updates = [
        c for c in fake_sb.calls
        if c["table"] == "subscriptions" and c["update"] and c["update"].get("status") == "canceled"
    ]
    assert len(status_updates) == 1


def test_subscription_deleted_skips_non_nai_price(fake_sb):
    """Non-NAI subscription canceled → return None, don't touch profile."""
    subscription = {
        "id": "sub_other_001",
        "customer": "cus_someone",
        "status": "canceled",
        "items": {"data": [{"price": {"id": "price_some_other_thing"}}]},
    }
    result = nai.handle_subscription_deleted(subscription)
    assert result is None
    assert fake_sb.update_calls == []


# ── Idempotency ────────────────────────────────────────────────────────────


def test_subscription_updated_is_idempotent(fake_sb):
    """Stripe retries the same event → re-applying produces the same outcome.
    UPSERT on stripe_subscription_id handles the dedup."""
    fake_sb.profile_by_customer["cus_alice123"] = {
        "id": "user-uuid-alice",
        "email": "alice@x.com",
        "stripe_customer_id": "cus_alice123",
        "tier": "free",
    }
    subscription = {
        "id": "sub_alice_pro_001",
        "customer": "cus_alice123",
        "status": "active",
        "items": {"data": [{"price": {"id": "price_test_pro"}}]},
    }
    r1 = nai.handle_subscription_updated(subscription)
    r2 = nai.handle_subscription_updated(subscription)
    r3 = nai.handle_subscription_updated(subscription)
    assert r1["tier"] == r2["tier"] == r3["tier"] == "pro"
    # All upserts use the same on_conflict key — Supabase replaces, doesn't duplicate
    upserts = [c for c in fake_sb.calls if c["table"] == "subscriptions" and c["upsert"]]
    assert len(upserts) == 3  # one per call
    for u in upserts:
        assert u["on_conflict"] == "stripe_subscription_id"
        assert u["upsert"]["stripe_subscription_id"] == "sub_alice_pro_001"
