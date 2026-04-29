"""Tests for telegram_subscription state machine.

Runs against a temp SQLite file so it doesn't pollute the real DB.
Stubs the env vars the module reads at call time. Stripe + Telegram
network calls are not made — we only exercise the local state transitions.
"""
from __future__ import annotations

import importlib
import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def ts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reload the module against a fresh temp DB and known env."""
    db = tmp_path / "subs.db"
    monkeypatch.setenv("TG_SUB_DB_PATH", str(db))
    monkeypatch.setenv("TELEGRAM_PRIVATE_CHANNEL_ID", "-1009999999999")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test:dummy")

    import narai.integrations.telegram_subscription as mod
    return importlib.reload(mod)


def _checkout_session(token: str, *, sub="sub_AAA", cust="cus_AAA",
                     email="alice@example.com") -> dict:
    return {
        "id": "cs_test_123",
        "subscription": sub,
        "customer": cust,
        "customer_details": {"email": email},
        "metadata": {"tg_pairing_token": token, "product": "tg_group"},
    }


def test_pairing_token_starts_pending_payment(ts):
    token = ts.new_pairing_token()
    assert ts.begin_pairing(token) == {
        "ok": False, "channel_id": None, "error": "wrong_status:pending_payment",
    }


def test_full_happy_path(ts):
    # 1. checkout token minted
    token = ts.new_pairing_token()
    ts.attach_session(token, "cs_test_123")

    # 2. stripe says payment succeeded
    returned = ts.handle_checkout_completed(_checkout_session(token))
    assert returned == token

    # 3. begin_pairing now allows the deep-link
    pre = ts.begin_pairing(token)
    assert pre["ok"] is True
    assert pre["channel_id"] == "-1009999999999"

    # 4. caller mints invite + finalizes
    ts.finalize_pairing(token, telegram_user_id=42, channel_id=pre["channel_id"],
                        invite_link="https://t.me/+abc123")

    active = ts.lookup_active_by_telegram_user(42)
    assert active is not None
    assert active["status"] == "active"
    assert active["last_invite_link"] == "https://t.me/+abc123"
    assert active["customer_email"] == "alice@example.com"
    assert active["stripe_subscription_id"] == "sub_AAA"


def test_unknown_token_rejected(ts):
    assert ts.begin_pairing("does-not-exist") == {
        "ok": False, "channel_id": None, "error": "unknown_token",
    }


def test_replay_rejects_after_active(ts):
    token = ts.new_pairing_token()
    ts.handle_checkout_completed(_checkout_session(token))
    ts.finalize_pairing(token, 42, "-1009999999999", "https://t.me/+abc123")

    pre = ts.begin_pairing(token)
    assert pre == {
        "ok": False, "channel_id": None, "error": "wrong_status:active",
    }


def test_expired_token_rejected(ts, monkeypatch: pytest.MonkeyPatch):
    token = ts.new_pairing_token()
    ts.handle_checkout_completed(_checkout_session(token))

    # Push the row's created_at back 25 hours.
    fake_old = int(time.time()) - (25 * 60 * 60)
    with ts._conn() as c:
        c.execute("UPDATE subs SET created_at=? WHERE pairing_token=?",
                  (fake_old, token))
        c.commit()

    pre = ts.begin_pairing(token)
    assert pre == {
        "ok": False, "channel_id": None, "error": "token_expired",
    }


def test_revoke_for_subscription_kicks_active_row(ts):
    token = ts.new_pairing_token()
    ts.handle_checkout_completed(_checkout_session(token, sub="sub_BBB"))
    ts.finalize_pairing(token, 99, "-1009999999999", "https://t.me/+xyz")

    row = ts.revoke_for_subscription("sub_BBB")
    assert row is not None
    assert row["telegram_user_id"] == 99
    assert row["channel_id"] == "-1009999999999"

    # subsequent revoke is a no-op
    assert ts.revoke_for_subscription("sub_BBB") is None
    # user no longer surfaces as active
    assert ts.lookup_active_by_telegram_user(99) is None


def test_revoke_unknown_subscription_returns_none(ts):
    assert ts.revoke_for_subscription("sub_does_not_exist") is None
    assert ts.revoke_for_subscription("") is None


def test_handle_checkout_ignores_non_tg_sessions(ts):
    """Sessions for other products (no tg_pairing_token) must be passed through silently."""
    other = {
        "id": "cs_other",
        "subscription": "sub_X",
        "metadata": {"narai_plan": "pro"},
    }
    assert ts.handle_checkout_completed(other) is None


def test_handle_checkout_with_unknown_token_logs_and_returns_none(ts, caplog):
    rogue = _checkout_session(token="never-minted")
    with caplog.at_level("WARNING"):
        assert ts.handle_checkout_completed(rogue) is None
    assert any("unknown pairing token" in r.message for r in caplog.records)


def test_subscription_updated_records_period_end(ts):
    token = ts.new_pairing_token()
    ts.handle_checkout_completed(_checkout_session(token, sub="sub_C"))

    ts.handle_subscription_updated({"id": "sub_C", "current_period_end": 1_900_000_000})

    with ts._conn() as c:
        row = c.execute(
            "SELECT period_end FROM subs WHERE stripe_subscription_id=?", ("sub_C",)
        ).fetchone()
    assert row["period_end"] == 1_900_000_000


def test_channel_not_configured_blocks_pairing(ts, monkeypatch: pytest.MonkeyPatch):
    token = ts.new_pairing_token()
    ts.handle_checkout_completed(_checkout_session(token))

    monkeypatch.setenv("TELEGRAM_PRIVATE_CHANNEL_ID", "")
    assert ts.begin_pairing(token) == {
        "ok": False, "channel_id": None, "error": "channel_not_configured",
    }


def test_list_active_subscribers(ts):
    for i in range(3):
        token = ts.new_pairing_token()
        ts.handle_checkout_completed(_checkout_session(token, sub=f"sub_{i}",
                                                      email=f"u{i}@x.com"))
        ts.finalize_pairing(token, 1000 + i, "-1009999999999", f"https://t.me/+{i}")

    active = ts.list_active_subscribers()
    assert len(active) == 3
    emails = {a["customer_email"] for a in active}
    assert emails == {"u0@x.com", "u1@x.com", "u2@x.com"}
