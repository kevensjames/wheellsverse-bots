"""infra.brain.telemetry.events — structured event schema.

A telemetry :class:`Event` is a frozen, JSON-serializable record produced
at every interesting step in the brain runtime. The event surface is small
and stable so consumers (logging sinks, dashboards, test assertions) can
rely on its shape.

Event types are kept as plain string constants (not an Enum) so external
sinks can match on them without taking a Python dependency on the brain.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


# ── Event-type vocabulary (stable strings) ───────────────────────────────────
#
# Group prefixes — keep these as the only namespacing convention so a sink
# can subscribe by prefix (e.g. "tool_*", "loop_*") without parsing.

# chat lifecycle
EVENT_CHAT_START: str = "chat_start"
EVENT_CHAT_END: str = "chat_end"

# agent loop
EVENT_LOOP_ITERATION_START: str = "loop_iteration_start"
EVENT_LOOP_ITERATION_END: str = "loop_iteration_end"
EVENT_LOOP_FINISHED: str = "loop_finished"
EVENT_LOOP_MAX_ITERATIONS: str = "loop_max_iterations"

# tool executor
EVENT_TOOL_START: str = "tool_start"
EVENT_TOOL_SUCCESS: str = "tool_success"
EVENT_TOOL_ERROR: str = "tool_error"
EVENT_TOOL_DENIED: str = "tool_denied"
EVENT_TOOL_NOT_FOUND: str = "tool_not_found"

# memory
EVENT_MEMORY_RECALL: str = "memory_recall"
EVENT_MEMORY_HIT: str = "memory_hit"
EVENT_MEMORY_MISS: str = "memory_miss"

# rag
EVENT_RAG_QUERY: str = "rag_query"
EVENT_RAG_HIT: str = "rag_hit"
EVENT_RAG_MISS: str = "rag_miss"

# agent runtime — task lifecycle
EVENT_TASK_START: str = "task_start"
EVENT_TASK_END: str = "task_end"

# agent runtime — planner
EVENT_PLAN_START: str = "plan_start"
EVENT_PLAN_END: str = "plan_end"

# agent runtime — executor
EVENT_STEP_START: str = "step_start"
EVENT_STEP_SUCCESS: str = "step_success"
EVENT_STEP_ERROR: str = "step_error"


KNOWN_EVENT_TYPES: frozenset[str] = frozenset({
    EVENT_CHAT_START, EVENT_CHAT_END,
    EVENT_LOOP_ITERATION_START, EVENT_LOOP_ITERATION_END,
    EVENT_LOOP_FINISHED, EVENT_LOOP_MAX_ITERATIONS,
    EVENT_TOOL_START, EVENT_TOOL_SUCCESS, EVENT_TOOL_ERROR,
    EVENT_TOOL_DENIED, EVENT_TOOL_NOT_FOUND,
    EVENT_MEMORY_RECALL, EVENT_MEMORY_HIT, EVENT_MEMORY_MISS,
    EVENT_RAG_QUERY, EVENT_RAG_HIT, EVENT_RAG_MISS,
    EVENT_TASK_START, EVENT_TASK_END,
    EVENT_PLAN_START, EVENT_PLAN_END,
    EVENT_STEP_START, EVENT_STEP_SUCCESS, EVENT_STEP_ERROR,
})


# ── Event ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Event:
    """Immutable telemetry record.

    Fields
    ------
    timestamp:
        Unix epoch seconds (float). Set by :meth:`make`.
    user_id:
        The brain client's bound user identifier.
    mode:
        The active policy's mode (``"nai"`` | ``"narai"`` | custom).
    event_type:
        One of the ``EVENT_*`` constants above (or any custom string for
        plug-in events; stable strings are encouraged but not enforced).
    metadata:
        Arbitrary JSON-serializable payload. Convention: keep keys
        snake_case and stable; numbers prefer float for durations
        (`duration_ms`).
    """

    timestamp: float
    user_id: str
    mode: str
    event_type: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def make(
        cls,
        *,
        user_id: str,
        mode: str,
        event_type: str,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "Event":
        """Create an event stamped with the current wall-clock time."""
        return cls(
            timestamp=time.time(),
            user_id=user_id,
            mode=mode,
            event_type=event_type,
            metadata=dict(metadata) if metadata else {},
        )

    def to_dict(self) -> dict:
        """JSON-friendly representation. Metadata is shallow-copied; keys
        with non-serializable values are coerced to ``repr`` so callers can
        always serialize without a custom encoder."""
        meta: dict = {}
        for k, v in (self.metadata or {}).items():
            try:
                # Cheap test: if it's a primitive, list, or dict it'll round-trip.
                if isinstance(v, (str, int, float, bool, type(None))):
                    meta[k] = v
                elif isinstance(v, (list, tuple)):
                    meta[k] = list(v)
                elif isinstance(v, dict):
                    meta[k] = v
                else:
                    meta[k] = repr(v)
            except Exception:
                meta[k] = "<unrepresentable>"
        return {
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "mode": self.mode,
            "event_type": self.event_type,
            "metadata": meta,
        }


__all__ = [
    "Event",
    "KNOWN_EVENT_TYPES",
    # event-type constants
    "EVENT_CHAT_START", "EVENT_CHAT_END",
    "EVENT_LOOP_ITERATION_START", "EVENT_LOOP_ITERATION_END",
    "EVENT_LOOP_FINISHED", "EVENT_LOOP_MAX_ITERATIONS",
    "EVENT_TOOL_START", "EVENT_TOOL_SUCCESS", "EVENT_TOOL_ERROR",
    "EVENT_TOOL_DENIED", "EVENT_TOOL_NOT_FOUND",
    "EVENT_MEMORY_RECALL", "EVENT_MEMORY_HIT", "EVENT_MEMORY_MISS",
    "EVENT_RAG_QUERY", "EVENT_RAG_HIT", "EVENT_RAG_MISS",
    "EVENT_TASK_START", "EVENT_TASK_END",
    "EVENT_PLAN_START", "EVENT_PLAN_END",
    "EVENT_STEP_START", "EVENT_STEP_SUCCESS", "EVENT_STEP_ERROR",
]
