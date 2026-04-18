"""Retry + rate-limit + circuit breaker. Every external call goes through this."""
import asyncio
import time
from collections import deque
from functools import wraps
from typing import Any, Callable, Type

import pybreaker
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ── Circuit breakers per service ─────────────────────────────────────────────

_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def _breaker(service: str) -> pybreaker.CircuitBreaker:
    if service not in _breakers:
        _breakers[service] = pybreaker.CircuitBreaker(
            fail_max=5,
            reset_timeout=60,
            name=service,
        )
    return _breakers[service]


# ── Token-bucket rate limiter ─────────────────────────────────────────────────

class RateLimiter:
    """Simple token-bucket: max `calls` per `period` seconds."""

    def __init__(self, calls: int, period: float):
        self._calls = calls
        self._period = period
        self._timestamps: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > self._period:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._calls:
            sleep_for = self._period - (now - self._timestamps[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._timestamps.append(time.monotonic())

    async def async_acquire(self) -> None:
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > self._period:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._calls:
            sleep_for = self._period - (now - self._timestamps[0])
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
        self._timestamps.append(time.monotonic())


_rate_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(service: str, calls: int = 60, period: float = 60.0) -> RateLimiter:
    if service not in _rate_limiters:
        _rate_limiters[service] = RateLimiter(calls, period)
    return _rate_limiters[service]


# ── Decorator: wrap any external call ────────────────────────────────────────

def guarded(
    service: str,
    retries: int = 3,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    calls_per_minute: int = 60,
):
    """Decorator that applies retry + rate-limit + circuit breaker to a function."""

    def decorator(fn: Callable) -> Callable:
        limiter = get_rate_limiter(service, calls=calls_per_minute)
        breaker = _breaker(service)

        @retry(
            retry=retry_if_exception_type(exceptions),
            stop=stop_after_attempt(retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            reraise=True,
        )
        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            limiter.acquire()
            return breaker.call(fn, *args, **kwargs)

        @retry(
            retry=retry_if_exception_type(exceptions),
            stop=stop_after_attempt(retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            reraise=True,
        )
        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            await limiter.async_acquire()
            return breaker.call(fn, *args, **kwargs)

        return async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper

    return decorator


def breaker_status() -> dict[str, str]:
    return {name: str(cb.current_state) for name, cb in _breakers.items()}
