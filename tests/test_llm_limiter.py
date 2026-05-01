"""Unit tests for core.llm_limiter — deterministic, no network."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from core.llm_limiter import LLMCapacityTimeout, LLMLimiter, limiter_for, reset_all


class FakeClock:
    """Mockable monotonic clock. sleep() advances time but doesn't actually wait."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


@pytest.fixture
def clock():
    fc = FakeClock()
    with patch("core.llm_limiter.time.time", side_effect=fc.time), \
         patch("core.llm_limiter.time.sleep", side_effect=fc.sleep):
        yield fc


@pytest.fixture(autouse=True)
def reset_limiters():
    reset_all()
    yield
    reset_all()


def test_under_limit_returns_immediately(clock):
    lim = LLMLimiter("gpt-4o", tpm_limit=10_000, rpm_limit=100)
    start = clock.now
    lim.wait_for_capacity(estimated_tokens=500)
    assert clock.now == start, "first call should not sleep"


def test_over_limit_blocks_then_returns(clock):
    lim = LLMLimiter("gpt-4o", tpm_limit=1_000, rpm_limit=100)
    lim.wait_for_capacity(estimated_tokens=900)        # window: 900/1000
    start = clock.now
    lim.wait_for_capacity(estimated_tokens=500)        # over budget — must wait for window to slide
    assert clock.now > start, "should have slept"
    assert clock.now - start >= 60.0, "should sleep until oldest entry expires"


def test_window_slides_restores_capacity(clock):
    lim = LLMLimiter("gpt-4o", tpm_limit=1_000, rpm_limit=100, window=60.0)
    lim.wait_for_capacity(estimated_tokens=900)
    clock.now += 61.0                                   # advance past window
    start = clock.now
    lim.wait_for_capacity(estimated_tokens=900)        # window cleared — should be instant
    assert clock.now == start, "expired entries should be reclaimed"


def test_record_corrects_estimate(clock):
    lim = LLMLimiter("gpt-4o", tpm_limit=1_000, rpm_limit=100)
    lim.wait_for_capacity(estimated_tokens=500)
    lim.record(actual_tokens=900)                       # actual was higher
    # Now window has 900 used; a 200-token call should fit but a 200+ should not
    start = clock.now
    lim.wait_for_capacity(estimated_tokens=50)
    assert clock.now == start
    # But 200 more pushes us over 1000
    start = clock.now
    lim.wait_for_capacity(estimated_tokens=200)
    assert clock.now > start, "record() should reflect in subsequent waits"


def test_per_model_isolation(clock):
    g4o = limiter_for("gpt-4o")
    mini = limiter_for("gpt-4o-mini")
    assert g4o is not mini
    # Exhaust gpt-4o
    g4o.wait_for_capacity(estimated_tokens=g4o.tpm_limit)
    start = clock.now
    mini.wait_for_capacity(estimated_tokens=100)
    assert clock.now == start, "mini should not be affected by gpt-4o saturation"


def test_timeout_raises(clock):
    lim = LLMLimiter("gpt-4o", tpm_limit=100, rpm_limit=100, window=60.0)
    lim.wait_for_capacity(estimated_tokens=100)
    with pytest.raises(LLMCapacityTimeout):
        # Asking for more than total budget within the window can never be served
        lim.wait_for_capacity(estimated_tokens=101, timeout=5.0)


def test_rpm_ceiling_blocks(clock):
    lim = LLMLimiter("gpt-4o", tpm_limit=10_000_000, rpm_limit=2, window=60.0)
    lim.wait_for_capacity(estimated_tokens=1)
    lim.wait_for_capacity(estimated_tokens=1)
    start = clock.now
    lim.wait_for_capacity(estimated_tokens=1)          # over RPM, even though TPM has room
    assert clock.now > start, "RPM ceiling should also block"


def test_concurrent_safety_keeps_total_under_limit():
    """N threads racing — total tokens recorded must never exceed limit at any instant.

    This test uses real time.sleep (no clock mock) so the threading machinery works
    naturally — but the loop is bounded so it finishes fast.
    """
    lim = LLMLimiter("gpt-4o", tpm_limit=1_000, rpm_limit=10_000, window=2.0)
    errors: list[str] = []

    def worker():
        try:
            for _ in range(3):
                lim.wait_for_capacity(estimated_tokens=200, timeout=10.0)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"workers errored: {errors}"
    # At any window snapshot, total should be ≤ tpm_limit
    with lim._lock:
        lim._expire_old(__import__("time").time())
        total = lim._current_token_total()
    assert total <= lim.tpm_limit, f"window snapshot exceeded limit: {total}"
