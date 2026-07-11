"""Reliable check-in delivery: confirmed send, no silent loss, backed-off retry.

These lock in the fix for the audit's HIGH finding — a check-in whose Telegram
send fails must NOT be marked sent, and must be retried, not silently dropped.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import observability
from app.services.checkin import scheduler as sched
from app.services.checkin import storage as store


@pytest.fixture(autouse=True)
def _temp(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHECKIN_DB_PATH", tmp_path / "checkin.db")
    for v in (
        "KAI_SCOPE_CHECKIN", "KAI_CHECKIN_SCHEDULER_ENABLED",
        "KAI_CHECKIN_RETRY_BASE_SECONDS", "KAI_CHECKIN_RETRY_CAP_SECONDS",
        "KAI_CHECKIN_RETRY_MAX_AGE_HOURS", "KAI_CHECKIN_RETRY_MAX_ATTEMPTS",
    ):
        monkeypatch.delenv(v, raising=False)
    yield


def _set_send(monkeypatch, result):
    calls = {"n": 0}

    def fake(text):
        calls["n"] += 1
        return result

    monkeypatch.setattr(observability, "send_sync", fake)
    return calls


def test_successful_delivery_marks_sent(monkeypatch):
    _set_send(monkeypatch, True)
    r = sched.run_checkin()
    assert r["sent"] is True and r["already_done"] is False
    row = store.recent()[0]
    assert row.sent is True and row.attempts == 1


def test_failed_delivery_leaves_unsent_for_retry(monkeypatch):
    _set_send(monkeypatch, False)
    r = sched.run_checkin()
    assert r["sent"] is False and r["already_done"] is False
    row = store.recent()[0]
    assert row.sent is False              # NOT marked sent on failure — the core fix
    assert row.attempts == 1
    assert row.last_attempt_at is not None


def test_delivery_exception_is_treated_as_failure(monkeypatch):
    def boom(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(observability, "send_sync", boom)
    r = sched.run_checkin()
    assert r["sent"] is False
    assert store.recent()[0].sent is False


def test_deliver_false_claims_without_sending(monkeypatch):
    calls = _set_send(monkeypatch, True)
    r = sched.run_checkin(deliver=False)
    assert r["sent"] is False and r["already_done"] is False
    assert calls["n"] == 0                # no send attempted
    assert store.recent()[0].sent is False


def test_retry_redelivers_failed_checkin(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_CHECKIN", "1")
    monkeypatch.setenv("KAI_CHECKIN_RETRY_BASE_SECONDS", "0")  # always due
    _set_send(monkeypatch, False)
    sched.run_checkin()
    assert store.recent()[0].sent is False
    # Telegram recovers → the retry pass delivers it.
    _set_send(monkeypatch, True)
    res = sched.retry_due_unsent()
    assert res["delivered"] == 1
    assert store.recent()[0].sent is True


def test_preview_row_is_not_redelivered(monkeypatch):
    # A deliver=False preview claims the day (sent=0, attempts=0) but must NOT be
    # turned into a real send by the retry pass.
    monkeypatch.setenv("KAI_SCOPE_CHECKIN", "1")
    monkeypatch.setenv("KAI_CHECKIN_RETRY_BASE_SECONDS", "0")
    calls = _set_send(monkeypatch, True)
    sched.run_checkin(deliver=False)          # preview: claim only, no send
    res = sched.retry_due_unsent()
    assert res["attempted"] == 0              # preview left alone
    assert calls["n"] == 0
    assert store.recent()[0].sent is False


def test_crashed_send_is_still_retried(monkeypatch):
    # A deliver=True claim stamps last_attempt_at (pending). If the process died
    # before the first record_attempt (attempts stays 0), the row must STILL be
    # retried — not abandoned like a preview. See finding [3].
    monkeypatch.setenv("KAI_SCOPE_CHECKIN", "1")
    monkeypatch.setenv("KAI_CHECKIN_RETRY_BASE_SECONDS", "0")
    store.record_checkin("20260101", "hi", sent=False, pending=True)  # crashed-real-send shape
    _set_send(monkeypatch, True)
    res = sched.retry_due_unsent()
    assert res["delivered"] == 1
    assert store.recent()[0].sent is True


def test_retry_is_scope_gated(monkeypatch):
    # scope OFF (deleted in fixture) → retry no-ops even with unsent rows
    _set_send(monkeypatch, False)
    sched.run_checkin()
    res = sched.retry_due_unsent()
    assert res.get("skipped") == "scope_off"


def test_retry_respects_backoff(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_CHECKIN", "1")
    monkeypatch.setenv("KAI_CHECKIN_RETRY_BASE_SECONDS", "3600")  # 1h base
    _set_send(monkeypatch, False)
    sched.run_checkin()                   # attempts=1, last_attempt=now
    _set_send(monkeypatch, True)
    res = sched.retry_due_unsent()        # only ~instant later → not yet due
    assert res["attempted"] == 0
    assert store.recent()[0].sent is False


def test_retry_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_CHECKIN", "1")
    monkeypatch.setenv("KAI_CHECKIN_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("KAI_CHECKIN_RETRY_MAX_ATTEMPTS", "2")
    _set_send(monkeypatch, False)
    sched.run_checkin()                   # attempts=1
    assert sched.retry_due_unsent()["attempted"] == 1   # attempts→2
    # attempts now == max (2) → no further attempts
    assert sched.retry_due_unsent()["attempted"] == 0


def test_is_due_backoff_math():
    class Row:
        pass

    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    r = Row()
    r.attempts = 1
    r.last_attempt_at = (now - timedelta(seconds=30)).isoformat()
    assert sched._is_due(r, now, base=60, cap=3600) is False   # 30s < 60s
    r.last_attempt_at = (now - timedelta(seconds=90)).isoformat()
    assert sched._is_due(r, now, base=60, cap=3600) is True     # 90s >= 60s
    r.last_attempt_at = None
    assert sched._is_due(r, now, base=60, cap=3600) is True     # never attempted


def test_idempotent_dedup_still_holds(monkeypatch):
    _set_send(monkeypatch, True)
    assert sched.run_checkin()["already_done"] is False
    assert sched.run_checkin()["already_done"] is True          # same UTC day
