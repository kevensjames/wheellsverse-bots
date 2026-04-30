"""Tests for discord_subscription state machine.

Mirrors test_telegram_subscription. No Discord HTTP calls — those are
exercised separately by integration tests against a test guild.
"""
from __future__ import annotations

import importlib
import time
from pathlib import Path

import pytest


@pytest.fixture
def ds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reload module with a fresh temp DB and known env."""
    db = tmp_path / "discord_subs.db"
    monkeypatch.setenv("DISCORD_SUB_DB_PATH", str(db))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test:dummy")

    import narai.integrations.discord_subscription as mod
    return importlib.reload(mod)


def _checkout_session(token: str, *, sub="sub_AAA", cust="cus_AAA",
                     email="alice@example.com") -> dict:
    return {
        "id": "cs_test_123",
        "subscription": sub,
        "customer": cust,
        "customer_details": {"email": email},
        "metadata": {
            "discord_pairing_token": token,
            "product": "discord_role",
        },
    }


def test_pairing_token_starts_pending(ds):
    token = ds.new_pairing_token(discord_user_id="11111", discord_guild_id="22222")
    with ds._conn() as c:
        row = c.execute("SELECT status, discord_user_id, discord_guild_id FROM subs "
                        "WHERE pairing_token=?", (token,)).fetchone()
    assert row["status"] == "pending_payment"
    assert row["discord_user_id"] == "11111"
    assert row["discord_guild_id"] == "22222"


def test_full_happy_path(ds):
    token = ds.new_pairing_token(discord_user_id="42", discord_guild_id="999")
    ds.attach_session(token, "cs_test_123")

    row = ds.handle_checkout_completed(_checkout_session(token))
    assert row is not None
    assert row["status"] == "active"
    assert row["discord_user_id"] == "42"
    assert row["discord_guild_id"] == "999"
    assert row["stripe_subscription_id"] == "sub_AAA"

    active = ds.lookup_active_by_discord_user("42")
    assert active is not None
    assert active["customer_email"] == "alice@example.com"


def test_handle_checkout_ignores_non_discord_sessions(ds):
    """Sessions without discord_pairing_token must be passed through."""
    other = {
        "id": "cs_other",
        "subscription": "sub_X",
        "metadata": {"narai_plan": "pro"},
    }
    assert ds.handle_checkout_completed(other) is None


def test_handle_checkout_with_unknown_token_returns_none(ds, caplog):
    rogue = _checkout_session(token="never-minted")
    with caplog.at_level("WARNING"):
        assert ds.handle_checkout_completed(rogue) is None
    assert any("unknown token" in r.message for r in caplog.records)


def test_revoke_for_subscription(ds):
    token = ds.new_pairing_token(discord_user_id="42", discord_guild_id="999")
    ds.handle_checkout_completed(_checkout_session(token, sub="sub_BBB"))

    row = ds.revoke_for_subscription("sub_BBB")
    assert row is not None
    assert row["discord_user_id"] == "42"
    assert row["discord_guild_id"] == "999"

    # Idempotent — second revoke is a no-op
    assert ds.revoke_for_subscription("sub_BBB") is None
    # User no longer surfaces as active
    assert ds.lookup_active_by_discord_user("42") is None


def test_revoke_unknown_subscription_returns_none(ds):
    assert ds.revoke_for_subscription("sub_does_not_exist") is None
    assert ds.revoke_for_subscription("") is None


def test_subscription_updated_records_period_end(ds):
    token = ds.new_pairing_token(discord_user_id="42")
    ds.handle_checkout_completed(_checkout_session(token, sub="sub_C"))

    ds.handle_subscription_updated({"id": "sub_C", "current_period_end": 1_900_000_000})

    with ds._conn() as c:
        row = c.execute(
            "SELECT period_end FROM subs WHERE stripe_subscription_id=?", ("sub_C",)
        ).fetchone()
    assert row["period_end"] == 1_900_000_000


def test_list_active_subscribers(ds):
    for i in range(3):
        token = ds.new_pairing_token(discord_user_id=str(1000 + i), discord_guild_id="g")
        ds.handle_checkout_completed(_checkout_session(token, sub=f"sub_{i}",
                                                      email=f"u{i}@x.com"))
    active = ds.list_active_subscribers()
    assert len(active) == 3
    assert {a["discord_user_id"] for a in active} == {"1000", "1001", "1002"}


def test_revoking_one_user_doesnt_affect_others(ds):
    t1 = ds.new_pairing_token(discord_user_id="alice")
    t2 = ds.new_pairing_token(discord_user_id="bob")
    ds.handle_checkout_completed(_checkout_session(t1, sub="sub_A"))
    ds.handle_checkout_completed(_checkout_session(t2, sub="sub_B"))

    ds.revoke_for_subscription("sub_A")

    assert ds.lookup_active_by_discord_user("alice") is None
    bob = ds.lookup_active_by_discord_user("bob")
    assert bob is not None and bob["status"] == "active"
