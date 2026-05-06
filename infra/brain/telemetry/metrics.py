"""infra.brain.telemetry.metrics — counters + sliding-window histograms.

Lightweight, in-memory primitives. Locked with ``threading.Lock`` for
correctness under mixed sync/async access; the GIL makes contention
negligible at brain frequencies (a handful of events per chat turn).

Both :class:`Counters` and :class:`Histogram` produce JSON-friendly
snapshots so they can be flushed to logs / dashboards / tests.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Iterable, Optional


# ── Counters ─────────────────────────────────────────────────────────────────


class Counters:
    """Integer counters with optional per-user / per-mode dimensions.

    All increments touch the global counter; if ``user`` or ``mode`` is
    given, the corresponding sub-counter is incremented too. The split keeps
    snapshots cheap to render — no aggregation work at read time.
    """

    def __init__(self) -> None:
        self._global: dict[str, int] = defaultdict(int)
        self._by_user: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._by_mode: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._lock = threading.Lock()

    def incr(
        self,
        key: str,
        by: int = 1,
        *,
        user: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._global[key] += by
            if user:
                self._by_user[user][key] += by
            if mode:
                self._by_mode[mode][key] += by

    def get(self, key: str) -> int:
        with self._lock:
            return self._global.get(key, 0)

    def snapshot(self) -> dict:
        """Return a JSON-friendly view of the counters."""
        with self._lock:
            return {
                "events": dict(self._global),
                "by_user": {
                    u: dict(c) for u, c in self._by_user.items()
                },
                "by_mode": {
                    m: dict(c) for m, c in self._by_mode.items()
                },
            }

    def clear(self) -> None:
        with self._lock:
            self._global.clear()
            self._by_user.clear()
            self._by_mode.clear()


# ── Histogram ────────────────────────────────────────────────────────────────


class Histogram:
    """Sliding-window numeric distribution.

    Holds the last ``max_samples`` values (deque, O(1) append). Stats are
    computed lazily at snapshot time — no running aggregates to break under
    concurrency.
    """

    def __init__(self, max_samples: int = 1024) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        self._samples: deque = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def record(self, value: float) -> None:
        # Fast path: single deque append, lock just for thread safety.
        with self._lock:
            self._samples.append(float(value))

    def stats(self) -> dict:
        """Return ``{count, min, max, mean, p50, p95, p99}`` (zeroes when empty)."""
        with self._lock:
            if not self._samples:
                return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0,
                        "p50": 0.0, "p95": 0.0, "p99": 0.0}
            samples = sorted(self._samples)
        n = len(samples)
        return {
            "count": n,
            "min": samples[0],
            "max": samples[-1],
            "mean": sum(samples) / n,
            "p50": samples[_pct_idx(n, 0.50)],
            "p95": samples[_pct_idx(n, 0.95)],
            "p99": samples[_pct_idx(n, 0.99)],
        }

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


def _pct_idx(n: int, p: float) -> int:
    # Nearest-rank percentile — OK for tiny samples and avoids interpolation
    # surprises in tests. Index is clamped to [0, n-1].
    if n <= 0:
        return 0
    return min(n - 1, max(0, int(round(p * (n - 1)))))


# ── Histogram registry — keyed bag of histograms by metric name ─────────────


class HistogramRegistry:
    """Lazy bag of named histograms — created on first record."""

    def __init__(self, max_samples_per_key: int = 1024) -> None:
        self._max = max_samples_per_key
        self._hist: dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def record(self, key: str, value: float) -> None:
        with self._lock:
            h = self._hist.get(key)
            if h is None:
                h = Histogram(max_samples=self._max)
                self._hist[key] = h
        h.record(value)

    def keys(self) -> Iterable[str]:
        with self._lock:
            return list(self._hist.keys())

    def snapshot(self) -> dict:
        with self._lock:
            keys = list(self._hist.keys())
            histos = dict(self._hist)
        return {k: histos[k].stats() for k in sorted(keys)}

    def clear(self) -> None:
        with self._lock:
            self._hist.clear()


__all__ = ["Counters", "Histogram", "HistogramRegistry"]
