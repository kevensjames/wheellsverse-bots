"""infra.brain.agents.task — the unit of work for the agent runtime.

A :class:`BrainTask` is a *frozen* dataclass that flows through the runtime
in well-defined stages:

  created  → planner.plan()  →  planned  → executor.run()  →  done | failed

Frozen-ness is deliberate: each stage produces a new instance via
:func:`dataclasses.replace`, so callers can hold older snapshots safely
(useful for telemetry, retries, audit trails). The state machine is
expressed in the ``state`` field — never mutated in place.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional


TaskState = Literal["created", "planned", "running", "done", "failed"]


@dataclass(frozen=True)
class BrainTask:
    """Immutable record of a multi-step agent task.

    Fields
    ------
    id:
        Stable identifier. Used as the correlation ID for every telemetry
        event the planner / executor emit while working on this task.
    input:
        The user's request, verbatim. The planner reads this; the executor
        does not (it walks ``plan`` instead).
    plan:
        Filled in by :class:`PlannerAgent`. ``None`` until planning completes.
        Shape: ``{"steps": [{"type": "tool"|"think", ...}, ...]}``.
    state:
        Current phase. See :data:`TaskState` for the allowed values.
    result:
        Filled in by :class:`ExecutorAgent`. ``None`` until execution
        completes. Shape: ``{"steps": [{...per-step record...}, ...],
        "final": <last successful step's output>}``.
    """

    id: str
    input: str
    plan: Optional[dict] = None
    state: TaskState = "created"
    result: Optional[dict] = None


def create_task(input: str) -> BrainTask:
    """Construct a fresh task in the ``created`` state.

    The id is a UUID4 hex prefix; short enough for log readability, long
    enough that collisions across a process lifetime are negligible.
    """
    if not isinstance(input, str):
        raise TypeError(f"BrainTask.input must be str, got {type(input).__name__}")
    return BrainTask(
        id=uuid.uuid4().hex[:12],
        input=input,
    )


__all__ = ["BrainTask", "TaskState", "create_task"]
