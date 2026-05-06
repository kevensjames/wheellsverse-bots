"""infra.brain.tools — tool registration + policy-gated execution.

Public surface (re-exported from :mod:`infra.brain.interface` so consumers
need only the one import):

  Tool, ToolRegistry, ToolExecutor
  default_registry(), register()
  ToolPermissionError, ToolNotFoundError
  WEB_SEARCH_TOOL, register_demo_tools()
"""
from .registry import (
    Tool,
    ToolRegistry,
    ToolRun,
    default_registry,
    register,
)
from .executor import (
    ToolExecutor,
    ToolPermissionError,
    ToolNotFoundError,
)
from .schema import ToolSchema
from .agent_loop import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    ToolCall,
    parse_tool_call,
    build_tool_use_prompt,
    format_tool_result,
)
from .builtin import (
    WEB_SEARCH_TOOL,
    register_demo_tools,
)

__all__ = [
    "Tool",
    "ToolRegistry",
    "ToolRun",
    "ToolSchema",
    "ToolExecutor",
    "ToolPermissionError",
    "ToolNotFoundError",
    "default_registry",
    "register",
    "WEB_SEARCH_TOOL",
    "register_demo_tools",
]
