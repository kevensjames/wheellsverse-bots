"""Spend tracker tests against real Postgres.

Requires a Postgres at TEST_DATABASE_URL (see backend/tests/conftest.py).
The `llm_call_log` and `profiles` tables must exist in that DB. In local-PG
mode they're created by `Base.metadata.create_all` (llm_call_log) and the
user fixture handles `users`; `profiles` is currently Supabase-only, so this
file is only exercised when the operator points TEST_DATABASE_URL at a
Postgres that contains both.
"""
import pytest

from app.services.router.spend_tracker import SpendTracker


def test_log_and_aggregate(db_session, free_user):
    tracker = SpendTracker(db_session, daily_cap_usd=10.0)
    uid = free_user.id

    tracker.log_call(
        user_id=uid, adapter="openai", model="gpt-4o-mini",
        input_tokens=100, output_tokens=50, cost_usd=0.001,
    )
    tracker.log_call(
        user_id=uid, adapter="anthropic", model="claude-sonnet-4-6",
        input_tokens=100, output_tokens=50, cost_usd=0.002,
    )
    db_session.commit()

    assert tracker.daily_spend(uid) == pytest.approx(0.003)
    assert tracker.monthly_spend(uid) == pytest.approx(0.003)
    assert tracker.over_daily_cap(uid) is False


def test_over_daily_cap(db_session, free_user):
    tracker = SpendTracker(db_session, daily_cap_usd=0.001)
    tracker.log_call(
        user_id=free_user.id, adapter="openai", model="gpt-4o",
        input_tokens=1000, output_tokens=500, cost_usd=0.01,
    )
    db_session.commit()
    assert tracker.over_daily_cap(free_user.id) is True


def test_log_failure_contributes_zero_cost(db_session, free_user):
    tracker = SpendTracker(db_session)
    tracker.log_call(
        user_id=free_user.id, adapter="anthropic", model="claude-sonnet-4-6",
        success=False, error_message="timeout",
    )
    db_session.commit()
    assert tracker.daily_spend(free_user.id) == pytest.approx(0.0)


def test_log_survives_request_rollback(db_session, free_user):
    """CORR-F5: the spend row is committed on its own session, so a rollback of
    the request transaction does not lose it (and can't let a charged call evade
    the soft cap). On the old code this asserted 0.0."""
    tracker = SpendTracker(db_session)
    tracker.log_call(
        user_id=free_user.id, adapter="openai", model="gpt-4o",
        input_tokens=10, output_tokens=5, cost_usd=0.005,
    )
    db_session.rollback()  # simulate the request transaction failing afterwards
    assert tracker.daily_spend(free_user.id) == pytest.approx(0.005)
