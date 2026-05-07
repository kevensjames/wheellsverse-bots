"""infra.brain.tools.agent_loop — protocol + helpers for LLM tool-calling.

This module owns the tool-calling protocol used by ``BrainClient.chat``. It
is intentionally protocol-only (parsing, prompt assembly) — the loop itself
lives in :class:`BrainClient` so it has straightforward access to the
router, policy, and executor without a tangled callback contract.

Wire format (per spec)
----------------------
The LLM emits **either** a JSON object with this exact shape::

    {"tool": "<tool_name>", "input": {...}}

…or normal natural-language text (the final answer). Anything that parses
as a JSON object containing a string ``"tool"`` field is interpreted as a
tool call; everything else is treated as the final response.

The parser is deliberately lenient: it accepts the JSON whether the model
returns it raw, inside a ``json`` code fence, or embedded after a short
preamble. This is the kind of slop that production LLMs produce.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .schema import ToolSchema

_log = logging.getLogger("infra.brain.tools.agent_loop")


# Hard upper bound on iterations for safety. The kwarg in BrainClient.chat
# defaults to this constant; callers can override but cannot exceed it.
DEFAULT_MAX_TOOL_ITERATIONS: int = 3


# ── Result type ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolCall:
    """A parsed tool-call envelope from the LLM."""

    name: str
    input: dict


# ── Parser ───────────────────────────────────────────────────────────────────


_FENCE_RE = re.compile(
    r"```(?:json)?\s*(?P<body>\{.*?\})\s*```", re.DOTALL | re.IGNORECASE
)


def parse_tool_call(content: str) -> Optional[ToolCall]:
    """Try to read a tool call out of an LLM response.

    Returns ``None`` if the content is not a tool call (i.e. it's the final
    answer). Returns a :class:`ToolCall` if the content contains a JSON
    object whose ``"tool"`` field is a non-empty string.

    Accepted shapes (in order of precedence):
      1. The entire trimmed content parses as a JSON object with ``"tool"``.
      2. A ``json`` code fence contains such an object.
      3. The first balanced ``{...}`` substring contains such an object.

    A malformed or non-tool envelope returns ``None`` — the caller treats it
    as the final response. We never raise from here; bad model output must
    not crash the chat loop.
    """
    if not content or not content.strip():
        return None

    text = content.strip()

    # 1) whole-string JSON
    candidate = _try_parse_call(text)
    if candidate is not None:
        return candidate

    # 2) ```json ... ``` fence
    m = _FENCE_RE.search(text)
    if m:
        candidate = _try_parse_call(m.group("body"))
        if candidate is not None:
            return candidate

    # 3) first balanced object inside the text
    obj_text = _first_json_object(text)
    if obj_text is not None:
        candidate = _try_parse_call(obj_text)
        if candidate is not None:
            return candidate

    return None


def _try_parse_call(raw: str) -> Optional[ToolCall]:
    """Parse ``raw`` and validate the {tool, input} envelope shape."""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("tool")
    if not isinstance(name, str) or not name.strip():
        return None
    inp = obj.get("input", {})
    if not isinstance(inp, dict):
        # Accept ``"input": null`` as empty dict; refuse anything else so
        # the model can't smuggle a string into an input slot expected to
        # be structured.
        if inp is None:
            inp = {}
        else:
            return None
    return ToolCall(name=name.strip(), input=inp)


def _first_json_object(text: str) -> Optional[str]:
    """Return the first balanced ``{...}`` substring, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# ── Prompt builder ───────────────────────────────────────────────────────────


def build_tool_use_prompt(schemas: Iterable[ToolSchema]) -> str:
    """Build the tool-use addendum for the system prompt.

    Returns an empty string when no schemas are given so callers can simply
    concatenate the result without conditional logic.
    """
    schemas = list(schemas)
    if not schemas:
        return ""

    blocks = "\n".join(s.to_prompt_block() for s in schemas)
    return (
        "## Tools\n"
        "You have access to the following tools when they would help answer "
        "the user. Each tool has a strict input schema.\n\n"
        f"{blocks}\n\n"
        "## Tool-call protocol\n"
        "When you want to call a tool, respond with **exactly** one JSON "
        "object on its own (no prose around it, no code fences):\n"
        '    {"tool": "TOOL_NAME", "input": { ... arguments ... }}\n'
        "When you don't need a tool, respond with normal natural-language "
        "text — the final answer for the user.\n"
        "After a tool runs you'll see its output as the next message; "
        "either call another tool or write the final answer."
    )


def format_tool_result(
    tool_name: str,
    result: object,
    error: Optional[str] = None,
    *,
    iteration: Optional[int] = None,
) -> str:
    """Render a tool's outcome into the next user-turn payload.

    The model sees a single labeled message so the convention is obvious
    even without prior context (handy when memory is wiped between turns).

    Audit Issue #5 closure (PR #8, 2026-05-06): when the body exceeds
    the 8000-byte cap, this function now (a) emits a
    ``tool_result_truncated`` telemetry event with the original size,
    truncated size, tool name, and optional iteration index, and (b)
    prepends a clear inline marker the planner LLM can see — the prior
    ``…[truncated]`` suffix was too easy for the model to gloss over.
    The cap itself is unchanged — protecting the context window remains
    the load-bearing reason this truncation exists.
    """
    if error is not None:
        return f"[tool:{tool_name} ERROR] {error}"
    try:
        body = json.dumps(result, default=str, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        body = repr(result)
    # Trim runaway tool outputs — keeps the model focused and protects the
    # context window. The full result is still available to the caller via
    # the executor's return value.
    if len(body) > 8000:
        original_size = len(body)
        body = body[:8000]
        # Emit telemetry first so dashboards see truncations even if the
        # downstream prompt assembly fails for any reason.
        _emit_truncation_event(
            tool=tool_name,
            original_size=original_size,
            truncated_size=8000,
            iteration=iteration,
        )
        marker = (
            f"[TRUNCATED: original size {original_size} bytes; "
            f"kept first 8000 bytes]"
        )
        # Inline marker prepended to the body so the planner LLM sees
        # the truncation immediately, before the (now-incomplete) data.
        body = f"{marker}\n{body}"
    return f"[tool:{tool_name} OK] {body}"


def _emit_truncation_event(
    *,
    tool: str,
    original_size: int,
    truncated_size: int,
    iteration: Optional[int],
) -> None:
    """Forward a ``tool_result_truncated`` event to the active collector.

    No-op when no collector is bound — same ContextVar bridge pattern
    used by the rest of the brain (Phase D/E/F/G modules). Failure to
    emit must never break tool-result rendering."""
    try:
        from ..telemetry import get_current_telemetry
    except Exception:  # pragma: no cover
        return
    col = get_current_telemetry()
    if col is None:
        return
    try:
        col.emit(
            "tool_result_truncated",
            tool=tool,
            original_size=original_size,
            truncated_size=truncated_size,
            iteration=iteration,
        )
    except Exception:  # pragma: no cover
        _log.debug("tool truncation telemetry emit failed", exc_info=True)


# ── Telemetry helpers ────────────────────────────────────────────────────────
#
# Pure helpers that emit the loop's lifecycle events on whichever
# TelemetryCollector the caller passes in. Kept here so the loop's
# observability vocabulary lives next to its other protocol concerns.
# All helpers are no-ops when ``tel`` is ``None`` or disabled — the loop
# can call them unconditionally without hot-path checks.


def emit_iteration_start(tel, *, iteration: int, message_preview: str = "") -> None:
    if tel is None or not getattr(tel, "enabled", False):
        return
    from ..telemetry import EVENT_LOOP_ITERATION_START
    tel.emit(
        EVENT_LOOP_ITERATION_START,
        iteration=iteration,
        message_preview=(message_preview or "")[:120],
    )


def emit_iteration_end(
    tel,
    *,
    iteration: int,
    outcome: str,
    tool: Optional[str] = None,
    duration_ms: float = 0.0,
) -> None:
    if tel is None or not getattr(tel, "enabled", False):
        return
    from ..telemetry import EVENT_LOOP_ITERATION_END
    tel.emit(
        EVENT_LOOP_ITERATION_END,
        iteration=iteration,
        outcome=outcome,
        tool=tool,
        duration_ms=duration_ms,
    )
    tel.record_latency("loop_iteration", duration_ms)


def emit_loop_finished(tel, *, iterations: int, outcome: str = "final_answer") -> None:
    if tel is None or not getattr(tel, "enabled", False):
        return
    from ..telemetry import EVENT_LOOP_FINISHED
    tel.emit(EVENT_LOOP_FINISHED, iterations=iterations, outcome=outcome)


def emit_loop_max_iterations(tel, *, max_iters: int) -> None:
    if tel is None or not getattr(tel, "enabled", False):
        return
    from ..telemetry import EVENT_LOOP_MAX_ITERATIONS
    tel.emit(EVENT_LOOP_MAX_ITERATIONS, max_iters=max_iters)


__all__ = [
    "ToolCall",
    "DEFAULT_MAX_TOOL_ITERATIONS",
    "parse_tool_call",
    "build_tool_use_prompt",
    "format_tool_result",
    # telemetry helpers
    "emit_iteration_start",
    "emit_iteration_end",
    "emit_loop_finished",
    "emit_loop_max_iterations",
]
