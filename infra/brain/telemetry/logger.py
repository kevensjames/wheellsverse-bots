"""infra.brain.telemetry.logger — logging bridge.

Every recorded :class:`Event` is also emitted on the ``infra.brain.telemetry``
logger as a structured INFO record. Operators can plumb that channel into
their existing log infrastructure (Sentry, OpenTelemetry, plain JSON files)
without taking a Python dependency on the brain.

The bridge is decoupled from the collector so an in-process consumer (a
test, a CLI tool) can flush events and process them without ever waking
the logger.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .events import Event


_logger = logging.getLogger("infra.brain.telemetry")


def log_event(event: "Event") -> None:
    """Emit ``event`` on the telemetry logger as a structured record.

    The event-type doubles as the log message so log filters can route on
    a single field. The full event is attached as ``extra={"event": {...}}``
    for structured-log consumers.
    """
    _logger.info(
        event.event_type,
        extra={
            "telemetry": True,
            "event": {
                "timestamp": event.timestamp,
                "user_id": event.user_id,
                "mode": event.mode,
                "event_type": event.event_type,
                "metadata": dict(event.metadata or {}),
            },
        },
    )


__all__ = ["log_event"]
