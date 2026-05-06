"""infra.brain.tools.executor — policy-gated tool execution.

The executor is the *only* code path that calls a tool's ``run`` function.
It enforces three guarantees:

  1. **Permission**: ``brain_client.allows_tool(name)`` must be True. If not,
     ``ToolPermissionError`` is raised before the tool runs.
  2. **Existence**: the tool must be registered in the client's
     ``tool_registry``. Otherwise ``ToolNotFoundError`` is raised.
  3. **Auditability**: every attempt — allowed, denied, succeeded, failed —
     emits a structured log line with the user/mode/tool/duration/outcome.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Avoids a circular import: BrainClient imports ToolExecutor at startup,
    # ToolExecutor only needs the type at type-check time.
    from ..interface import BrainClient


logger = logging.getLogger("infra.brain.tools")


# ── Errors ───────────────────────────────────────────────────────────────────


class ToolPermissionError(PermissionError):
    """Raised when the active :class:`BrainPolicy` does not authorize the
    requested tool. Subclass of stdlib ``PermissionError`` so callers that
    catch ``PermissionError`` keep working."""


class ToolNotFoundError(KeyError):
    """Raised when the requested tool name is not in the registry. Subclass
    of stdlib ``KeyError`` so existing handlers continue to match."""


# ── Executor ─────────────────────────────────────────────────────────────────


class ToolExecutor:
    """Runs registered tools on behalf of a :class:`BrainClient`.

    The executor holds a reference to the client (not a copy) so it always
    sees the current policy — even if the client's policy changes during a
    request lifetime.
    """

    def __init__(self, brain_client: "BrainClient") -> None:
        self.brain_client = brain_client

    async def execute(self, tool_name: str, input: dict) -> Any:
        """Authorize → look up → run. Returns the tool's result.

        Raises
        ------
        ToolPermissionError
            Policy denied the tool. Tool's ``run`` is never invoked.
        ToolNotFoundError
            Tool is allowed by policy but not registered.
        Exception
            Anything the tool itself raises; logged and re-raised verbatim.
        """
        client = self.brain_client
        user_id = getattr(client, "user_id", "?")
        mode = getattr(client.policy, "mode", "?")
        tel = getattr(client, "telemetry", None)

        # 1) Permission check — single source of truth is BrainPolicy.
        if not client.allows_tool(tool_name):
            self._log_denied(tool_name, user_id, mode)
            self._emit_tel(tel, "denied", tool_name, input,
                           duration_ms=0.0,
                           reason=f"policy {mode!r} does not authorize {tool_name!r}")
            raise ToolPermissionError(
                f"Policy {mode!r} does not authorize tool {tool_name!r}"
            )

        # 2) Existence check.
        try:
            tool = client.tool_registry.get(tool_name)
        except KeyError as e:
            self._log_missing(tool_name, user_id, mode)
            self._emit_tel(tel, "not_found", tool_name, input,
                           duration_ms=0.0, reason=str(e))
            raise ToolNotFoundError(str(e)) from e

        # 3) Run, with timing + structured logging + telemetry.
        self._emit_tel(tel, "start", tool_name, input)
        start = time.perf_counter()
        try:
            result = await tool.run(input)
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log_failed(tool_name, user_id, mode, duration_ms, e)
            self._emit_tel(tel, "error", tool_name, input,
                           duration_ms=duration_ms,
                           error_type=type(e).__name__, error=str(e))
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        self._log_succeeded(tool_name, user_id, mode, duration_ms)
        self._emit_tel(tel, "success", tool_name, input,
                       duration_ms=duration_ms)
        return result

    # ── Telemetry helper ─────────────────────────────────────────────────

    @staticmethod
    def _emit_tel(tel, outcome: str, tool: str, input: dict, **md) -> None:
        """Emit one of the tool_* events. ``outcome`` selects the event type.

        No-op if ``tel`` is None or disabled — keeps the executor's hot path
        a single attribute lookup when telemetry is off.
        """
        if tel is None or not getattr(tel, "enabled", False):
            return
        # Lazy import — keeps the import graph clean if the executor is
        # unit-tested without the full brain package.
        from ..telemetry import (
            EVENT_TOOL_START, EVENT_TOOL_SUCCESS, EVENT_TOOL_ERROR,
            EVENT_TOOL_DENIED, EVENT_TOOL_NOT_FOUND,
        )
        kind = {
            "start":     EVENT_TOOL_START,
            "success":   EVENT_TOOL_SUCCESS,
            "error":     EVENT_TOOL_ERROR,
            "denied":    EVENT_TOOL_DENIED,
            "not_found": EVENT_TOOL_NOT_FOUND,
        }.get(outcome, outcome)
        # Don't store full input — it can be large or sensitive. Store a
        # bounded summary instead so dashboards can spot patterns.
        try:
            input_keys = sorted(input.keys()) if isinstance(input, dict) else []
        except Exception:
            input_keys = []
        tel.emit(kind, tool=tool, input_keys=input_keys, **md)
        # Also bucket per-tool latencies so we can spot slow tools.
        if "duration_ms" in md and isinstance(md["duration_ms"], (int, float)):
            tel.record_latency(f"tool:{tool}", float(md["duration_ms"]))

    # ── Logging helpers ──────────────────────────────────────────────────

    @staticmethod
    def _log_denied(tool: str, user: str, mode: str) -> None:
        logger.warning(
            "tool denied",
            extra={"tool": tool, "user": user, "mode": mode, "outcome": "denied"},
        )

    @staticmethod
    def _log_missing(tool: str, user: str, mode: str) -> None:
        logger.warning(
            "tool not found",
            extra={"tool": tool, "user": user, "mode": mode, "outcome": "missing"},
        )

    @staticmethod
    def _log_succeeded(tool: str, user: str, mode: str, ms: float) -> None:
        logger.info(
            "tool ok",
            extra={
                "tool": tool, "user": user, "mode": mode,
                "outcome": "ok", "duration_ms": round(ms, 2),
            },
        )

    @staticmethod
    def _log_failed(
        tool: str, user: str, mode: str, ms: float, err: BaseException
    ) -> None:
        logger.error(
            "tool failed: %s",
            err,
            extra={
                "tool": tool, "user": user, "mode": mode,
                "outcome": "error", "duration_ms": round(ms, 2),
                "error_type": type(err).__name__,
            },
        )


__all__ = ["ToolExecutor", "ToolPermissionError", "ToolNotFoundError"]
