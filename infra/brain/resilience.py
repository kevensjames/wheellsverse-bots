"""Retry + rate-limit + circuit breaker. Every external call goes through this."""
import asyncio
import time
from collections import deque
from functools import wraps
from typing import Any, Callable, Type

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


# ── Minimal async-safe circuit breaker ───────────────────────────────────────

class CircuitBreakerError(Exception):
    pass


class CircuitBreaker:
    """Fail-fast circuit breaker: open after `fail_max` errors, reset after `timeout` s."""

    _CLOSED = "closed"
    _OPEN = "open"
    _HALF_OPEN = "half_open"

    def __init__(self, fail_max: int = 5, reset_timeout: float = 60.0, name: str = ""):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.name = name
        self._failures = 0
        self._opened_at: float | None = None
        self._state = self._CLOSED

    @property
    def current_state(self) -> str:
        if self._state == self._OPEN:
            if time.monotonic() - (self._opened_at or 0) >= self.reset_timeout:
                self._state = self._HALF_OPEN
        return self._state

    def _on_success(self) -> None:
        self._failures = 0
        self._state = self._CLOSED
        self._opened_at = None

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.fail_max:
            self._state = self._OPEN
            self._opened_at = time.monotonic()

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        if self.current_state == self._OPEN:
            raise CircuitBreakerError(f"Circuit open for service '{self.name}'")
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    async def call_async(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        if self.current_state == self._OPEN:
            raise CircuitBreakerError(f"Circuit open for service '{self.name}'")
        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise


_breakers: dict[str, CircuitBreaker] = {}


def _breaker(service: str) -> CircuitBreaker:
    if service not in _breakers:
        _breakers[service] = CircuitBreaker(fail_max=5, reset_timeout=60, name=service)
    return _breakers[service]


# ── Token-bucket rate limiter ─────────────────────────────────────────────────

class RateLimiter:
    """Simple sliding-window rate limiter: max `calls` per `period` seconds."""

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


# ── Decorator ─────────────────────────────────────────────────────────────────

def guarded(
    service: str,
    retries: int = 3,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    calls_per_minute: int = 60,
) -> Callable:
    """Apply retry + rate-limit + circuit breaker to any function."""

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
            return await breaker.call_async(fn, *args, **kwargs)

        return async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper

    return decorator


def breaker_status() -> dict[str, str]:
    return {name: cb.current_state for name, cb in _breakers.items()}
