"""infra.brain.telemetry — observability for the brain runtime.

Public surface (also re-exported from ``infra.brain.interface`` so external
consumers never need to import this package directly):

  Event, KNOWN_EVENT_TYPES + EVENT_* string constants
  Counters, Histogram, HistogramRegistry
  TelemetryCollector
  get_current_telemetry() — ContextVar accessor for memory/rag/etc.
  log_event() — logging bridge (plumbed automatically by the collector)
"""
from .events import (
    Event,
    KNOWN_EVENT_TYPES,
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
)
from .metrics import Counters, Histogram, HistogramRegistry
from .collector import TelemetryCollector, get_current_telemetry
from .logger import log_event

__all__ = [
    # events
    "Event", "KNOWN_EVENT_TYPES",
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
    # metrics
    "Counters", "Histogram", "HistogramRegistry",
    # collector + context
    "TelemetryCollector", "get_current_telemetry",
    # logger bridge
    "log_event",
]
