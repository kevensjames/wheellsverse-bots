"""infra.brain.agents.planner — produces a structured JSON plan.

The planner is the *only* agent that converts a free-form user request
into a structured plan. It uses :meth:`BrainClient.chat` with
``max_tool_iterations=0`` so tool execution is **architecturally
impossible** here — even if the planning LLM emits a tool-call envelope
by accident, the loop is disabled and the response is returned as plain
content. The planner then validates the JSON itself.

Output schema (the only shape the planner ever emits)::

    {"steps": [
        {"type": "tool", "name": "<tool_name>", "input": { ... }},
        {"type": "think", "prompt": "<optional reasoning prompt>"},
        ...
    ]}

The validator is strict: malformed plans set ``task.state="failed"`` and
record the parse error in ``task.result``. The executor refuses to run a
failed task.
"""
from __future__ import annotations

import dataclasses
import json
import re
import time
from typing import TYPE_CHECKING, Optional

from ..telemetry import EVENT_PLAN_END, EVENT_PLAN_START
from ..tools.schema import ToolSchema
from .task import BrainTask

if TYPE_CHECKING:
    from ..interface import BrainClient


# ── Constants ────────────────────────────────────────────────────────────────


MAX_PLAN_STEPS: int = 10
ALLOWED_STEP_TYPES: frozenset[str] = frozenset({"tool", "think"})


# ── Public agent ─────────────────────────────────────────────────────────────


class PlannerAgent:
    """LLM-driven JSON plan producer.

    Construction is cheap: a planner is just a thin wrapper over a
    :class:`BrainClient`. The planner does not own state — every
    :meth:`plan` call is independent.
    """

    def __init__(self, brain: "BrainClient") -> None:
        self.brain = brain

    async def plan(self, task: BrainTask) -> BrainTask:
        """Produce a structured plan for ``task.input``.

        Returns a *new* :class:`BrainTask` (frozen — uses
        ``dataclasses.replace``) with either:

          * ``state="planned"``, ``plan={"steps": [...]}`` on success.
          * ``state="failed"``,  ``result={"error": "...", "raw": "..."}``
            on parse / validation failure.
        """
        tel = self.brain.telemetry
        t0 = time.perf_counter()
        if tel.enabled:
            tel.emit(
                EVENT_PLAN_START,
                task_id=task.id,
                input_len=len(task.input or ""),
            )

        system_prompt = _build_planner_system_prompt(self.brain)

        try:
            # max_tool_iterations=0 → planner CANNOT execute tools.
            # use_memory/use_rag=False → no context contamination of the
            # JSON-only output channel.
            result = await self.brain.chat(
                task.input,
                system=system_prompt,
                max_tool_iterations=0,
                use_memory=False,
                use_rag=False,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            if tel.enabled:
                tel.emit(
                    EVENT_PLAN_END,
                    task_id=task.id,
                    duration_ms=duration_ms,
                    ok=False,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                tel.record_latency("plan", duration_ms)
            return dataclasses.replace(
                task,
                state="failed",
                result={"error": f"planner_chat_failed: {e}"},
            )

        raw = (result.get("content") or "").strip()
        plan = parse_plan(raw)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        if plan is None:
            if tel.enabled:
                tel.emit(
                    EVENT_PLAN_END,
                    task_id=task.id,
                    duration_ms=duration_ms,
                    ok=False,
                    error_type="invalid_plan",
                )
                tel.record_latency("plan", duration_ms)
            return dataclasses.replace(
                task,
                state="failed",
                result={
                    "error": "invalid_plan",
                    "raw": raw[:2000],
                },
            )

        if tel.enabled:
            tel.emit(
                EVENT_PLAN_END,
                task_id=task.id,
                duration_ms=duration_ms,
                ok=True,
                step_count=len(plan["steps"]),
            )
            tel.record_latency("plan", duration_ms)

        return dataclasses.replace(task, plan=plan, state="planned")


# ── System-prompt assembly ───────────────────────────────────────────────────


def _build_planner_system_prompt(brain: "BrainClient") -> str:
    """Compose the planner's system prompt: role + tool catalog + schema."""
    schemas: list[ToolSchema] = []
    for name in brain.tool_registry.list():
        if not brain.allows_tool(name):
            continue
        tool = brain.tool_registry.get(name)
        s = ToolSchema.from_tool(tool)
        if s is not None:
            schemas.append(s)

    if schemas:
        catalog = "\n".join(s.to_prompt_block() for s in schemas)
    else:
        catalog = "(no tools available — every step must be of type \"think\")"

    return (
        "You are a task planner inside a multi-agent runtime. "
        "Given a user goal, you output a structured JSON plan that another "
        "agent (the Executor) will run. You DO NOT execute anything yourself.\n\n"
        "## Available tools\n\n"
        f"{catalog}\n\n"
        "## Output format\n\n"
        "Output ONLY a single JSON object on its own (no prose, no code "
        "fences, no preamble). The object must match this shape exactly:\n\n"
        '    {"steps": [\n'
        '      {"type": "tool", "name": "TOOL_NAME", "input": { ... }},\n'
        '      {"type": "think", "content": "OPTIONAL_REASONING_INSTRUCTION"}\n'
        "    ]}\n\n"
        "## Step types\n"
        '- "tool": Run a registered tool with valid input matching its '
        "input_schema. The name must be one of the tools listed above.\n"
        '- "think": Reason about prior step outputs (no tool execution). '
        'Put the reasoning instruction in the "content" field.\n\n'
        "## Constraints\n"
        f"- Maximum {MAX_PLAN_STEPS} steps.\n"
        "- Tool inputs must match the tool's input_schema fields and types.\n"
        "- Keep plans tight; prefer fewer steps when possible.\n"
        "- The final step is usually a \"think\" that synthesises the answer."
    )


# ── Strict-but-lenient JSON-plan parser ──────────────────────────────────────


_FENCE_RE = re.compile(
    r"```(?:json)?\s*(?P<body>\{.*?\})\s*```", re.DOTALL | re.IGNORECASE
)


def parse_plan(content: str) -> Optional[dict]:
    """Parse a planner response. Returns the validated plan dict or ``None``.

    Accepted shapes (in order of precedence):
      1. The entire trimmed content parses as JSON.
      2. A ``json`` code fence contains JSON.
      3. The first balanced ``{...}`` substring contains JSON.

    The plan must be ``{"steps": [...]}`` with each step a dict whose
    ``type`` is ``"tool"`` or ``"think"``. Tool steps must have a non-empty
    string ``name`` and a dict ``input`` (defaulting to ``{}``). Steps
    beyond ``MAX_PLAN_STEPS`` are dropped at parse time so the executor
    never sees an oversized plan.

    Returns ``None`` for any malformed envelope. Never raises.
    """
    if not content or not content.strip():
        return None

    text = content.strip()

    candidate = _validate(_try_load(text))
    if candidate is not None:
        return candidate

    m = _FENCE_RE.search(text)
    if m:
        candidate = _validate(_try_load(m.group("body")))
        if candidate is not None:
            return candidate

    obj = _first_balanced_object(text)
    if obj is not None:
        candidate = _validate(_try_load(obj))
        if candidate is not None:
            return candidate

    return None


def _try_load(s: str) -> Optional[object]:
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _validate(obj: object) -> Optional[dict]:
    """Validate the plan envelope. Returns the cleaned plan or ``None``.

    The parser preserves the full step list verbatim — the executor enforces
    its own running cap (``max_steps``) and emits truncation metadata when
    it kicks in. Truncating here would silently swallow that signal.
    """
    if not isinstance(obj, dict):
        return None
    steps = obj.get("steps")
    if not isinstance(steps, list):
        return None

    cleaned: list[dict] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            return None
        t = raw_step.get("type")
        if t not in ALLOWED_STEP_TYPES:
            return None
        if t == "tool":
            name = raw_step.get("name")
            if not isinstance(name, str) or not name.strip():
                return None
            inp = raw_step.get("input", {})
            if inp is None:
                inp = {}
            if not isinstance(inp, dict):
                return None
            cleaned.append({"type": "tool", "name": name.strip(), "input": inp})
        else:  # think
            # Spec field is ``content``. We also accept legacy ``prompt`` so
            # any older planner output keeps parsing — both normalize to
            # ``content`` on the cleaned step.
            body = raw_step.get("content")
            if not isinstance(body, str) or not body.strip():
                body = raw_step.get("prompt")
            step: dict = {"type": "think"}
            if isinstance(body, str) and body.strip():
                step["content"] = body.strip()
            cleaned.append(step)

    if not cleaned:
        return None
    return {"steps": cleaned}


def _first_balanced_object(text: str) -> Optional[str]:
    """Return the first balanced ``{...}`` substring, ignoring braces inside strings."""
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


__all__ = ["PlannerAgent", "MAX_PLAN_STEPS", "ALLOWED_STEP_TYPES", "parse_plan"]
