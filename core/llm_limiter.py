"""Global sliding-window TPM/RPM limiter for OpenAI calls.

Coordinates concurrent bot requests so the org-tier ceiling
(30,000 tokens/minute on gpt-4o for the free tier) is never exceeded
by a retry storm.

Pattern mirrors `core/discord_bot.py::_is_rate_limited` — sliding-window
deque, per-key isolation — adapted for tokens-per-minute instead of
messages-per-window.

Public API:
    limiter_for(model)        -> LLMLimiter
    LLMLimiter.wait_for_capacity(estimated_tokens, timeout=120) -> blocks
    LLMLimiter.record(actual_tokens) -> corrects window after the call

Configuration (env, all optional):
    OPENAI_TPM_LIMIT_GPT_4O        default 28_000  (28k buffer < 30k ceiling)
    OPENAI_TPM_LIMIT_GPT_4O_MINI   default 180_000
    OPENAI_RPM_LIMIT               default 450
    OPENAI_LIMITER_TIMEOUT         default 120     seconds
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Deque, Tuple

logger = logging.getLogger("llm_limiter")


class LLMCapacityTimeout(RuntimeError):
    """Raised when wait_for_capacity exceeds its timeout — caller should pause this job."""


class LLMLimiter:
    """Sliding-window token + request limiter for one model.

    Thread-safe. Releases the lock while sleeping so other threads
    can re-check capacity (otherwise calls serialize and we lose
    the throughput we just saved).
    """

    def __init__(
        self,
        model: str,
        tpm_limit: int,
        rpm_limit: int,
        window: float = 60.0,
    ) -> None:
        self.model = model
        self.tpm_limit = tpm_limit
        self.rpm_limit = rpm_limit
        self.window = window
        self._tokens: Deque[Tuple[float, int]] = deque()
        self._requests: Deque[float] = deque()
        self._lock = threading.Lock()

    def _expire_old(self, now: float) -> None:
        cutoff = now - self.window
        while self._tokens and self._tokens[0][0] < cutoff:
            self._tokens.popleft()
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()

    def _current_token_total(self) -> int:
        return sum(t for _, t in self._tokens)

    def wait_for_capacity(self, estimated_tokens: int, timeout: float = 120.0) -> None:
        """Block until the sliding window has room for estimated_tokens.

        Raises LLMCapacityTimeout if room doesn't appear within `timeout` seconds.
        """
        deadline = time.time() + timeout
        while True:
            with self._lock:
                now = time.time()
                self._expire_old(now)
                token_total = self._current_token_total()
                request_total = len(self._requests)

                tokens_ok = token_total + estimated_tokens <= self.tpm_limit
                requests_ok = request_total + 1 <= self.rpm_limit

                if tokens_ok and requests_ok:
                    self._tokens.append((now, estimated_tokens))
                    self._requests.append(now)
                    return

                # Compute how long until the oldest entry expires
                oldest_token_ts = self._tokens[0][0] if self._tokens else now
                oldest_req_ts = self._requests[0] if self._requests else now
                wait_until = min(oldest_token_ts, oldest_req_ts) + self.window
                wait_seconds = max(0.05, wait_until - now)

            if time.time() + wait_seconds > deadline:
                raise LLMCapacityTimeout(
                    f"{self.model}: waited >{timeout}s for capacity "
                    f"(tokens={token_total}/{self.tpm_limit}, "
                    f"requests={request_total}/{self.rpm_limit}/min)"
                )
            logger.debug(
                f"{self.model}: at capacity ({token_total}/{self.tpm_limit} tpm, "
                f"{request_total}/{self.rpm_limit} rpm) — sleeping {wait_seconds:.1f}s"
            )
            time.sleep(min(wait_seconds, 5.0))  # cap individual sleeps so timeout is responsive

    def record(self, actual_tokens: int) -> None:
        """Correct the most-recent estimate with actual usage from the OpenAI response.

        We added `estimated_tokens` to the deque pre-call; if the actual was higher,
        bump the most recent entry so subsequent waiters see the true cost.
        """
        with self._lock:
            if not self._tokens:
                # Estimate already expired — record as fresh entry
                self._tokens.append((time.time(), actual_tokens))
                return
            ts, est = self._tokens[-1]
            if actual_tokens > est:
                self._tokens[-1] = (ts, actual_tokens)


# ─── Per-model singleton registry ──────────────────────────────────────────

_DEFAULT_TPM = {
    "gpt-4o": int(os.getenv("OPENAI_TPM_LIMIT_GPT_4O", "28000")),
    "gpt-4o-mini": int(os.getenv("OPENAI_TPM_LIMIT_GPT_4O_MINI", "180000")),
}
_DEFAULT_RPM = int(os.getenv("OPENAI_RPM_LIMIT", "450"))
_FALLBACK_TPM = int(os.getenv("OPENAI_TPM_LIMIT_DEFAULT", "28000"))

_limiters: dict[str, LLMLimiter] = {}
_registry_lock = threading.Lock()


def limiter_for(model: str) -> LLMLimiter:
    """Get-or-create the singleton limiter for `model`. Thread-safe."""
    with _registry_lock:
        if model not in _limiters:
            tpm = _DEFAULT_TPM.get(model, _FALLBACK_TPM)
            _limiters[model] = LLMLimiter(model=model, tpm_limit=tpm, rpm_limit=_DEFAULT_RPM)
            logger.info(f"LLMLimiter[{model}] initialized: {tpm} tpm, {_DEFAULT_RPM} rpm")
        return _limiters[model]


def reset_all() -> None:
    """Clear all limiter state — used by tests only."""
    with _registry_lock:
        _limiters.clear()
