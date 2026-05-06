"""infra.brain.telemetry.collector — central event sink + ContextVar bridge.

A :class:`TelemetryCollector` is bound to one ``(user_id, mode)`` pair —
typically created by a :class:`BrainClient` at construction time. It owns
counters, latency histograms, and a bounded ring buffer of recent
:class:`Event` records.

The collector also doubles as the ContextVar-bound *current* telemetry
sink. ``BrainClient.chat`` activates its own collector for the duration of
a turn; module-level functions in :mod:`infra.brain.memory` and
:mod:`infra.brain.rag` look up the active collector via
:func:`get_current_telemetry` and emit events without taking a brain
dependency. This keeps memory/rag APIs unchanged.

When ``enabled=False``, every emit / record / latency call short-circuits
on the first attribute lookup — overhead per call is one bool check.
"""
from __future__ import annotations

import contextlib
import contextvars
import time
from collections import deque
from typing import Any, Iterator, Mapping, Optional

from .events import Event
from .logger import log_event
from .metrics import Counters, HistogramRegistry


# ── ContextVar plumbing ──────────────────────────────────────────────────────
#
# ``ContextVar`` correctly propagates across ``await`` boundaries within an
# asyncio task and is independent across tasks — perfect for scoping a
# telemetry collector to one ``chat()`` invocation while several may run
# concurrently.

_current_telemetry: contextvars.ContextVar[Optional["TelemetryCollector"]] = (
    contextvars.ContextVar("brain_telemetry", default=None)
)


def get_current_telemetry() -> Optional["TelemetryCollector"]:
    """Return the active in-context collector, or ``None`` if none set."""
    return _current_telemetry.get()


# ── Collector ────────────────────────────────────────────────────────────────


class TelemetryCollector:
    """Bounded, in-memory telemetry sink for one brain client.

    Public surface (per the architecture spec):
        record(event)        → store an Event (and forward to logger)
        flush()              → drain the ring buffer
        get_stats()          → counters + latency snapshot

    Convenience:
        emit(event_type, **md)         → build + record an Event
        record_latency(key, value_ms)  → record into a histogram
        activate()                     → context manager that scopes self
                                         onto the ContextVar (for memory/rag)
    """

    def __init__(
        self,
        *,
        user_id: str = "?",
        mode: str = "?",
        enabled: bool = True,
        buffer_size: int = 4096,
        histogram_samples: int = 1024,
    ) -> None:
        self.user_id = user_id
        self.mode = mode
        self._enabled = bool(enabled)
        self._counters = Counters()
        self._latencies = HistogramRegistry(max_samples_per_key=histogram_samples)
        self._events: deque[Event] = deque(maxlen=buffer_size)
        self._created_at = time.time()

    # ── State ────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    # ── Recording ────────────────────────────────────────────────────────

    def record(self, event: Event) -> None:
        """Persist an event: counters + buffer + structured log."""
        if not self._enabled:
            return
        # Update counters under their own lock; histograms updated separately
        # via record_latency (we don't auto-extract from metadata to keep the
        # contract explicit for callers).
        self._counters.incr(
            event.event_type,
            user=event.user_id or None,
            mode=event.mode or None,
        )
        self._events.append(event)
        # Forward to the logger bridge — separate concern, may be a no-op
        # if telemetry logging is filtered upstream.
        try:
            log_event(event)
        except Exception:
            # Logger faults must never propagate into the brain's hot path.
            pass

    def emit(
        self,
        event_type: str,
        *,
        user_id: Optional[str] = None,
        mode: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        **extra_metadata: Any,
    ) -> None:
        """Build an :class:`Event` and record it. The collector's bound
        ``user_id``/``mode`` are used unless explicit values are passed.
        Extra kwargs are folded into metadata for ergonomic call sites:
            tel.emit("memory_recall", duration_ms=2.4, hits=3)
        """
        if not self._enabled:
            return
        meta: dict[str, Any] = {}
        if metadata:
            meta.update(metadata)
        if extra_metadata:
            meta.update(extra_metadata)
        event = Event.make(
            user_id=user_id or self.user_id,
            mode=mode or self.mode,
            event_type=event_type,
            metadata=meta,
        )
        self.record(event)

    def record_latency(self, key: str, value_ms: float) -> None:
        """Record a duration sample into the histogram bag under ``key``."""
        if not self._enabled:
            return
        self._latencies.record(key, value_ms)

    # ── Drain / inspect ──────────────────────────────────────────────────

    def flush(self) -> list[dict]:
        """Drain the ring buffer; returns a list of JSON-friendly events.

        After flushing, the buffer is empty but counters and histograms are
        preserved (they are aggregates, not a queue). Use :meth:`clear`
        to reset everything.
        """
        if not self._enabled:
            return []
        out = [e.to_dict() for e in self._events]
        self._events.clear()
        return out

    def get_stats(self) -> dict:
        """Combined counters + latency snapshot + buffer size."""
        snap = self._counters.snapshot() if self._enabled else {
            "events": {}, "by_user": {}, "by_mode": {},
        }
        return {
            "enabled": self._enabled,
            "user_id": self.user_id,
            "mode": self.mode,
            "uptime_seconds": time.time() - self._created_at,
            "events": snap.get("events", {}),
            "by_user": snap.get("by_user", {}),
            "by_mode": snap.get("by_mode", {}),
            "latencies_ms": self._latencies.snapshot() if self._enabled else {},
            "buffer_size": len(self._events),
        }

    def clear(self) -> None:
        """Reset counters, latencies, and buffer. Bound ids preserved."""
        self._counters.clear()
        self._latencies.clear()
        self._events.clear()

    # ── Context-manager activation ───────────────────────────────────────

    @contextlib.contextmanager
    def activate(self) -> Iterator["TelemetryCollector"]:
        """Bind ``self`` to the ContextVar for the duration of the ``with``.

        Used by :meth:`BrainClient.chat` so memory / rag instrumentation
        can resolve the active collector via :func:`get_current_telemetry`
        without an explicit parameter chain.
        """
        token = _current_telemetry.set(self)
        try:
            yield self
        finally:
            _current_telemetry.reset(token)


__all__ = [
    "TelemetryCollector",
    "get_current_telemetry",
]
