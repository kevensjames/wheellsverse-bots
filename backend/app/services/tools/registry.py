"""Tool registry. Knows every tool, exposes provider-specific schemas, executes.

Execution is GOVERNED: every tool call is audited, and any tool that causes an
external side effect (declared via a ``writes = True`` class attribute) is blocked
unless the request carries operator authorization (``ctx.allow_writes``) — and any
scope it declares is enabled. This closes the gap where the LLM tool loop invoked
tools with no scope/approval/audit (composio/MCP/CRM writes could run silently).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.services.governance import is_scope_enabled
from app.services.governance.audit_log import record_action
from app.services.tools.base import Tool, ToolContext, ToolError, ToolResult

logger = logging.getLogger(__name__)


def _tool_writes(tool: Tool) -> bool:
    """Whether a tool causes an external side effect. Read defensively so
    existing read/propose-only tools (no attribute) default to safe = False."""
    return bool(getattr(tool, "writes", False))


def _tool_scope(tool: Tool, name: str) -> str | None:
    """Optional governance scope a tool declares; None = no scope gate."""
    return getattr(tool, "scope", None)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool {name!r}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    # --- Schema export ---

    def openai_schema(self) -> list[dict[str, Any]]:
        """OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def anthropic_schema(self) -> list[dict[str, Any]]:
        """Anthropic tool-use format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in self._tools.values()
        ]

    # --- Execution (governed) ---

    def _audit(
        self,
        *,
        name: str,
        scope: str,
        ctx: ToolContext,
        writes: bool,
        arguments: dict[str, Any],
        success: bool,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Best-effort audit of one tool call. record_action never raises and
        redacts secret-keyed args, so this can't break tool execution."""
        try:
            record_action(
                action=f"tool.{name}",
                scope=scope,
                actor=str(getattr(ctx, "user_id", "unknown")),
                destructive=writes,
                approved=bool(getattr(ctx, "allow_writes", False)),
                inputs={"arguments": arguments},
                success=success,
                error=error,
                duration_ms=duration_ms,
            )
        except Exception as e:  # pragma: no cover - audit must never break exec
            logger.warning("tool audit swallowed for %s: %s", name, e)

    def execute(
        self, name: str, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        try:
            tool = self.get(name)
        except KeyError as e:
            self._audit(name=name, scope=f"tool.{name}", ctx=ctx, writes=False,
                        arguments=arguments, success=False, error=str(e))
            return ToolResult(
                call_id="", name=name, output={"error": str(e)}, is_error=True
            )

        writes = _tool_writes(tool)
        declared_scope = _tool_scope(tool, name)
        scope = declared_scope or f"tool.{name}"

        # ── Governance gate for side-effecting tools ──────────────────────
        if writes:
            # (a) optional scope opt-in (defense in depth for high-risk tools)
            if declared_scope and not is_scope_enabled(declared_scope):
                self._audit(name=name, scope=scope, ctx=ctx, writes=True,
                            arguments=arguments, success=False,
                            error=f"scope '{declared_scope}' not enabled")
                return ToolResult(
                    call_id="", name=name, is_error=True,
                    output={"error": f"blocked: tool '{name}' requires scope "
                                     f"'{declared_scope}' to be enabled"},
                )
            # (b) per-request operator authorization (default deny)
            if not getattr(ctx, "allow_writes", False):
                self._audit(name=name, scope=scope, ctx=ctx, writes=True,
                            arguments=arguments, success=False,
                            error="write tool blocked: operator authorization required")
                return ToolResult(
                    call_id="", name=name, is_error=True,
                    output={"error": f"blocked: tool '{name}' makes external "
                                     "changes and requires operator approval "
                                     "(allow_writes). It was not executed."},
                )

        # ── Execute + audit ───────────────────────────────────────────────
        t0 = time.time()
        try:
            output = tool.execute(ctx, **arguments)
        except ToolError as e:
            logger.warning("tool %s user error: %s", name, e)
            self._audit(name=name, scope=scope, ctx=ctx, writes=writes,
                        arguments=arguments, success=False, error=str(e),
                        duration_ms=int((time.time() - t0) * 1000))
            return ToolResult(
                call_id="", name=name, output={"error": str(e)}, is_error=True
            )
        except Exception as e:
            logger.exception("tool %s internal failure", name)
            self._audit(name=name, scope=scope, ctx=ctx, writes=writes,
                        arguments=arguments, success=False,
                        error=f"internal failure: {type(e).__name__}",
                        duration_ms=int((time.time() - t0) * 1000))
            return ToolResult(
                call_id="",
                name=name,
                output={"error": f"internal failure: {type(e).__name__}"},
                is_error=True,
            )

        self._audit(name=name, scope=scope, ctx=ctx, writes=writes,
                    arguments=arguments, success=True,
                    duration_ms=int((time.time() - t0) * 1000))
        return ToolResult(call_id="", name=name, output=output, is_error=False)
