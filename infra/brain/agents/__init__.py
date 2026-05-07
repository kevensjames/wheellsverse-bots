"""infra.brain.agents — multi-agent runtime layer.

Layered above the existing brain primitives (router / memory / rag /
skills / policy / tools / telemetry) without modifying any of them. The
runtime is driven by two cooperating agents:

  * :class:`PlannerAgent` converts a free-form request into a structured
    JSON plan. It cannot execute tools (uses ``max_tool_iterations=0``).

  * :class:`ExecutorAgent` walks the plan step by step, dispatching tool
    steps to :meth:`BrainClient.use_tool` and think steps to
    :meth:`BrainClient.chat` with tools off. It is the only agent that
    invokes tools.

Public surface (also re-exported from :mod:`infra.brain.interface`):

    BrainTask, TaskState, create_task
    AgentMessage, format_plan_message, format_tool_message
    PlannerAgent, parse_plan
    ExecutorAgent, DEFAULT_MAX_STEPS, HARD_MAX_STEPS
"""
from .executor import (
    DEFAULT_MAX_STEPS,
    ExecutorAgent,
    HARD_MAX_STEPS,
)
from .messages import (
    AgentMessage,
    format_plan_message,
    format_tool_message,
)
from .planner import (
    ALLOWED_STEP_TYPES,
    MAX_PLAN_STEPS,
    PlannerAgent,
    parse_plan,
)
from .task import (
    BrainTask,
    TaskState,
    create_task,
)

__all__ = [
    # task
    "BrainTask", "TaskState", "create_task",
    # messages
    "AgentMessage", "format_plan_message", "format_tool_message",
    # planner
    "PlannerAgent", "parse_plan",
    "MAX_PLAN_STEPS", "ALLOWED_STEP_TYPES",
    # executor
    "ExecutorAgent", "DEFAULT_MAX_STEPS", "HARD_MAX_STEPS",
]
