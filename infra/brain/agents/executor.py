"""infra.brain.agents.executor — runs a planned :class:`BrainTask`.

The executor is the *only* code path inside the agent runtime that
invokes :meth:`BrainClient.use_tool`. Per-step:

  * ``"tool"``  → dispatch to the registry-bound executor (policy still
                  applies, since :meth:`use_tool` itself goes through the
                  :class:`ToolExecutor` permission gate).
  * ``"think"`` → call :meth:`BrainClient.chat` with
                  ``max_tool_iterations=0`` so the think step cannot side-
                  step the executor and trigger tools by itself.

Per-step exceptions are caught, recorded into the step's record, and
do not abort the run — the executor finishes the plan and the task ends
in ``state="done"``. The task ends in ``state="failed"`` only when there
is no plan to run.

Hard limits:
  * ``max_steps = 10`` — caller-overridable, but never above
    :data:`HARD_MAX_STEPS`. Steps beyond the cap are dropped before the run.
"""
from __future__ import annotations

import dataclasses
import time
from typing import TYPE_CHECKING, Any, Optional

from ..telemetry import (
    EVENT_STEP_ERROR,
    EVENT_STEP_START,
    EVENT_STEP_SUCCESS,
)
from ..tools.executor import ToolNotFoundError, ToolPermissionError
from .task import BrainTask

if TYPE_CHECKING:
    from ..interface import BrainClient


# ── Limits ───────────────────────────────────────────────────────────────────

DEFAULT_MAX_STEPS: int = 10
HARD_MAX_STEPS: int = 10


# ── Public agent ─────────────────────────────────────────────────────────────


class ExecutorAgent:
    """Walks a :class:`BrainTask`'s plan and produces a step-by-step result.

    The executor never speaks to the LLM directly except through the
    :class:`BrainClient` (via ``brain.chat`` for think steps and
    ``brain.use_tool`` for tool steps). It reads no global state.
    """

    def __init__(
        self,
        brain: "BrainClient",
        *,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self.brain = brain
        self.max_steps = min(max(int(max_steps), 1), HARD_MAX_STEPS)

    async def run(self, task: BrainTask) -> BrainTask:
        """Execute the plan attached to ``task``. Returns a new task."""
        if task.plan is None or not isinstance(task.plan, dict):
            return dataclasses.replace(
                task,
                state="failed",
                result={"error": "no_plan", "steps": []},
            )

        steps = task.plan.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return dataclasses.replace(
                task,
                state="failed",
                result={"error": "empty_plan", "steps": []},
            )

        # Move task into the running state for any caller / observer that
        # snapshots between planner.plan and executor.run.
        running = dataclasses.replace(task, state="running")

        # Hard cap — even if the planner produced more.
        plan_to_run = steps[: self.max_steps]
        truncated = len(steps) > self.max_steps

        records: list[dict] = []
        last_ok_output: Any = None

        for index, step in enumerate(plan_to_run):
            record = await self._run_step(running, index, step, records)
            records.append(record)
            if record.get("ok"):
                last_ok_output = record.get("output")

        result = {
            "steps": records,
            "final": last_ok_output,
        }
        if truncated:
            result["truncated"] = True
            result["original_step_count"] = len(steps)
            result["max_steps"] = self.max_steps

        return dataclasses.replace(running, state="done", result=result)

    # ── Step dispatch ────────────────────────────────────────────────────

    async def _run_step(
        self,
        task: BrainTask,
        index: int,
        step: dict,
        prior: list[dict],
    ) -> dict:
        """Run one step. Always returns a dict — never raises."""
        tel = self.brain.telemetry
        kind = step.get("type")
        record: dict = {
            "index": index,
            "type": kind,
            "ok": False,
        }

        if tel.enabled:
            tel.emit(
                EVENT_STEP_START,
                task_id=task.id,
                index=index,
                type=kind,
                tool=step.get("name") if kind == "tool" else None,
            )

        t0 = time.perf_counter()
        try:
            if kind == "tool":
                output = await self._run_tool_step(step)
                record.update({"name": step.get("name"), "ok": True, "output": output})
            elif kind == "think":
                output = await self._run_think_step(step, prior)
                record.update({"ok": True, "output": output})
            else:
                # Unknown step type — record as error but continue.
                raise ValueError(f"unknown step type: {kind!r}")
        except (ToolPermissionError, ToolNotFoundError) as e:
            record.update({
                "name": step.get("name"),
                "ok": False,
                "error_type": "permission" if isinstance(e, ToolPermissionError) else "not_found",
                "error": str(e),
            })
        except Exception as e:
            record.update({
                "name": step.get("name") if kind == "tool" else None,
                "ok": False,
                "error_type": type(e).__name__,
                "error": str(e),
            })

        duration_ms = (time.perf_counter() - t0) * 1000.0
        record["duration_ms"] = round(duration_ms, 3)

        if tel.enabled:
            tel.record_latency("step", duration_ms)
            if record["ok"]:
                tel.emit(
                    EVENT_STEP_SUCCESS,
                    task_id=task.id,
                    index=index,
                    type=kind,
                    tool=record.get("name"),
                    duration_ms=duration_ms,
                )
            else:
                tel.emit(
                    EVENT_STEP_ERROR,
                    task_id=task.id,
                    index=index,
                    type=kind,
                    tool=record.get("name"),
                    duration_ms=duration_ms,
                    error_type=record.get("error_type"),
                    error=record.get("error"),
                )

        return record

    async def _run_tool_step(self, step: dict) -> Any:
        name = step.get("name") or ""
        inp = step.get("input") or {}
        if not isinstance(inp, dict):
            raise ValueError(
                f"tool step {name!r} has non-dict input: {type(inp).__name__}"
            )
        # use_tool already enforces policy + registry lookup + telemetry.
        return await self.brain.use_tool(name, inp)

    async def _run_think_step(self, step: dict, prior: list[dict]) -> str:
        # Spec field is ``content``; ``prompt`` accepted as legacy alias.
        prompt = (
            step.get("content")
            or step.get("prompt")
            or "Continue with the next reasoning step."
        )
        context = _format_prior_steps(prior)
        full_prompt = f"{prompt}\n\n## Prior step outputs\n{context}" if context else prompt

        # max_tool_iterations=0 → think CANNOT side-step the executor.
        # use_memory/use_rag default to policy; executor doesn't override.
        result = await self.brain.chat(
            full_prompt,
            max_tool_iterations=0,
        )
        return (result.get("content") or "").strip()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _format_prior_steps(prior: list[dict]) -> str:
    """Render prior step records into a compact context block for ``think``.

    Truncates each step's body to keep the context bounded; the full record
    is still in ``task.result["steps"]``.
    """
    if not prior:
        return ""
    lines: list[str] = []
    for r in prior:
        idx = r.get("index", "?")
        kind = r.get("type", "?")
        if r.get("ok"):
            body = r.get("output")
            if not isinstance(body, str):
                try:
                    import json
                    body = json.dumps(body, default=str, ensure_ascii=False)
                except Exception:
                    body = repr(body)
            if len(body) > 1500:
                body = body[:1500] + " …[truncated]"
            tool_part = f" tool={r.get('name')}" if kind == "tool" else ""
            lines.append(f"[step {idx}{tool_part} ok] {body}")
        else:
            lines.append(
                f"[step {idx} {kind} error] "
                f"{r.get('error_type', '?')}: {r.get('error', '')}"
            )
    return "\n".join(lines)


__all__ = ["ExecutorAgent", "DEFAULT_MAX_STEPS", "HARD_MAX_STEPS"]
