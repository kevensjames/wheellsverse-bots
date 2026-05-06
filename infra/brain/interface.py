"""infra.brain.interface — single access layer for all brain consumers.

External modules (products, services, integrations) MUST import only
``BrainClient`` from this module. Direct imports of ``infra.brain.router``,
``infra.brain.memory``, ``infra.brain.rag``, ``infra.brain.tiers``, or
``infra.brain.skills`` are forbidden by convention.

Boundary rationale:
  * swap brain internals without touching consumers
  * meter / observe / authorize all brain access in one place
  * partition data by (user_id, mode) so NAI and NarAI never collide

Behavior:
  Every behavior decision (tone, memory recall, RAG injection, tool
  authorization) is read from a frozen :class:`BrainPolicy` resolved at
  construction time. Mode strings are *not* branched on after init —
  ``self.policy`` is the single source of truth.

Design:
  * ``chat`` and ``execute`` are the high-level entry points
  * ``memory`` / ``rag`` / ``skills`` / ``tiers`` / ``router`` are exposed as
    *read-only module proxies*, so existing call patterns
    (``client.memory.aremember(...)``, ``client.rag.aquery(...)``) keep
    working without forcing every consumer to rewrite its loop. The only
    rule consumers must follow is: the import is ``BrainClient`` — never
    the underlying modules.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Literal, Optional

_agent_logger = logging.getLogger("infra.brain.agent")

# Internal-only imports. NEVER add another import to this file beyond the
# brain modules + policy below — that's the architectural contract.
from . import memory as _memory
from . import rag as _rag
from . import router as _router
from . import skills as _skills
from . import tiers as _tiers
from .policy import (
    BrainPolicy,
    NAI_POLICY,
    NARAI_POLICY,
    SAFE_TOOLS,
    available_modes,
    get_policy,
)
from .tools import (
    Tool,
    ToolRegistry,
    ToolSchema,
    ToolExecutor,
    ToolPermissionError,
    ToolNotFoundError,
    default_registry,
    register as register_tool,
)
from .tools.agent_loop import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    build_tool_use_prompt,
    emit_iteration_end,
    emit_iteration_start,
    emit_loop_finished,
    emit_loop_max_iterations,
    format_tool_result,
    parse_tool_call,
)
from .telemetry import (
    EVENT_CHAT_END,
    EVENT_CHAT_START,
    EVENT_TASK_END,
    EVENT_TASK_START,
    TelemetryCollector,
    get_current_telemetry,
)
# Agents package — top-level import so the re-exports in ``__all__`` actually
# resolve. The agents subpackage only imports BrainClient via TYPE_CHECKING,
# so there's no cycle.
from .agents import (
    AgentMessage,
    BrainTask,
    DEFAULT_MAX_STEPS,
    ExecutorAgent,
    HARD_MAX_STEPS,
    PlannerAgent,
    TaskState,
    create_task,
    format_plan_message,
    format_tool_message,
)


Mode = Literal["nai", "narai"]


class BrainClient:
    """Single entry point for all brain capabilities.

    Required surface:
        client = BrainClient(user_id="owner", mode="narai")
        await client.chat("hi")
        await client.execute({"prompt": "...", "tier": "deep"})

    All behavior is governed by ``self.policy`` (a frozen :class:`BrainPolicy`
    resolved from the mode at init time). Mode strings are not branched on
    after construction.

    Module proxies (for legacy call patterns and admin operations):
        client.memory   →  memory module
        client.rag      →  rag module
        client.skills   →  skills module
        client.tiers    →  tiers module
        client.router   →  router module (low-level)
    """

    __slots__ = (
        "user_id", "policy", "tool_registry", "tool_executor", "telemetry",
    )

    def __init__(
        self,
        user_id: str,
        mode: Mode = "narai",
        *,
        policy: Optional[BrainPolicy] = None,
        tool_registry: Optional[ToolRegistry] = None,
        telemetry_enabled: bool = True,
        telemetry: Optional[TelemetryCollector] = None,
    ) -> None:
        """Create a brain client.

        ``mode`` resolves to a registered :class:`BrainPolicy`. Pass
        ``policy=`` to override with a custom policy (the policy's own
        ``mode`` field becomes authoritative in that case).

        Pass ``tool_registry=`` for tests or per-request scopes; otherwise
        the process-wide :func:`default_registry` is used so any tool
        registered with :func:`register_tool` is visible here.

        Telemetry is on by default; pass ``telemetry_enabled=False`` (or
        a pre-built ``telemetry=`` collector) to disable or replace it. A
        disabled collector still exposes ``record/flush/get_stats`` — those
        methods are no-ops.
        """
        self.user_id = user_id
        self.policy = policy if policy is not None else get_policy(mode)
        self.tool_registry = (
            tool_registry if tool_registry is not None else default_registry()
        )
        self.tool_executor = ToolExecutor(self)
        if telemetry is not None:
            self.telemetry = telemetry
        else:
            self.telemetry = TelemetryCollector(
                user_id=user_id,
                mode=self.policy.mode,
                enabled=telemetry_enabled,
            )

    # ── Compatibility shim for the previous ``mode`` attribute ───────────

    @property
    def mode(self) -> str:
        """The active policy's mode identifier. Kept for back-compat —
        prefer reading ``self.policy`` directly."""
        return self.policy.mode

    # ── Module proxies ───────────────────────────────────────────────────

    @property
    def memory(self):
        """Memory module: facts (SQLite), episodes (Chroma), patterns."""
        return _memory

    @property
    def rag(self):
        """RAG module: ingest + query over Chroma documents."""
        return _rag

    @property
    def skills(self):
        """Skill-pack loader."""
        return _skills

    @property
    def tiers(self):
        """Tier classifier."""
        return _tiers

    @property
    def router(self):
        """Multi-model router (litellm). Use ``chat``/``execute`` for the
        common case; reach for ``router`` only when you need full control
        over the system prompt / message history."""
        return _router

    # ── Authorization ────────────────────────────────────────────────────

    def allows_tool(self, tool_name: str) -> bool:
        """Whether the current policy permits running ``tool_name``.

        Forwards to :meth:`BrainPolicy.allows_tool`. The
        :class:`ToolExecutor` consults this before running anything.
        """
        return self.policy.allows_tool(tool_name)

    async def use_tool(self, name: str, input: dict) -> Any:
        """Authorize and run a registered tool.

        Equivalent to ``await self.tool_executor.execute(name, input)``.

        Raises
        ------
        ToolPermissionError
            Active policy does not authorize ``name``.
        ToolNotFoundError
            Tool is allowed but not registered in :attr:`tool_registry`.
        """
        return await self.tool_executor.execute(name, input)

    def available_tools(self) -> list[str]:
        """Return the names of tools that are both *registered* and *authorized*
        for the active policy. Useful for surfacing a tool catalog to the
        LLM or to the operator UI."""
        return [
            n for n in self.tool_registry.list() if self.allows_tool(n)
        ]

    # ── Primary API ──────────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        *,
        system: Optional[str] = None,
        tier: Optional[str] = None,
        history: Optional[list[dict]] = None,
        skill: Optional[str] = None,
        use_memory: Optional[bool] = None,
        use_rag: Optional[bool] = None,
        max_tool_iterations: Optional[int] = None,
    ) -> dict:
        """Run a chat turn end-to-end, with automatic LLM tool-calling.

        When at least one *planner-visible* tool (``Tool.schema is not None``)
        is registered AND authorized by the policy, ``chat`` runs an agent
        loop:

          1. Send the message to the LLM with the tool catalog in the system prompt.
          2. If the response is a ``{"tool": ..., "input": ...}`` envelope,
             authorize via policy, execute via :class:`ToolExecutor`, append
             the labeled result to the history.
          3. Repeat up to ``max_tool_iterations`` times.
          4. Return the first non-tool response, or — if the cap is hit — a
             best-effort final answer constructed from the last assistant
             reply.

        When no planner-visible tool is authorized, ``chat`` degrades to a
        single ``router.call`` — identical to the pre-loop behavior, so all
        existing call sites continue to work unchanged.

        Parameters
        ----------
        message, system, tier, history, skill, use_memory, use_rag:
            Same semantics as before.
        max_tool_iterations:
            Hard cap on tool round-trips. Defaults to
            :data:`DEFAULT_MAX_TOOL_ITERATIONS` (3). Pass ``0`` to disable
            the loop entirely (forces a single LLM call with no tool prompt).

        Returns
        -------
        dict
            ``{"content": str, "model": str, "tokens": int, "tier": str,
              "tool_calls": list[dict], "iterations": int}``

            ``tool_calls`` and ``iterations`` are always present (empty/zero
            when the loop didn't fire) so consumers can introspect what the
            brain did.
        """
        # Activate the per-turn telemetry context so memory.recall + rag.query
        # emit into this client's collector. Disabled collectors short-circuit
        # in their record/emit/record_latency methods, so this `with` is
        # effectively free when telemetry is off.
        import time as _time
        _t0 = _time.perf_counter()
        with self.telemetry.activate():
            self.telemetry.emit(
                EVENT_CHAT_START,
                tier=tier,
                has_history=bool(history),
                skill=skill,
                use_memory=use_memory,
                use_rag=use_rag,
                max_tool_iterations=max_tool_iterations,
                message_len=len(message or ""),
            )
            try:
                result = await self._chat_body(
                    message=message,
                    system=system,
                    tier=tier,
                    history=history,
                    skill=skill,
                    use_memory=use_memory,
                    use_rag=use_rag,
                    max_tool_iterations=max_tool_iterations,
                )
                _ms = (_time.perf_counter() - _t0) * 1000.0
                self.telemetry.emit(
                    EVENT_CHAT_END,
                    duration_ms=_ms,
                    tier=result.get("tier"),
                    model=result.get("model"),
                    tokens=result.get("tokens"),
                    iterations=result.get("iterations", 0),
                    tool_calls=len(result.get("tool_calls") or []),
                    max_iterations_reached=bool(result.get("max_iterations_reached")),
                )
                self.telemetry.record_latency("chat", _ms)
                return result
            except Exception as e:
                _ms = (_time.perf_counter() - _t0) * 1000.0
                self.telemetry.emit(
                    EVENT_CHAT_END,
                    duration_ms=_ms,
                    error=True,
                    error_type=type(e).__name__,
                    error_message=str(e),
                )
                self.telemetry.record_latency("chat", _ms)
                raise

    async def _chat_body(
        self,
        *,
        message: str,
        system: Optional[str],
        tier: Optional[str],
        history: Optional[list[dict]],
        skill: Optional[str],
        use_memory: Optional[bool],
        use_rag: Optional[bool],
        max_tool_iterations: Optional[int],
    ) -> dict:
        """The original chat() body — kept as a private method so the public
        ``chat`` method owns the telemetry envelope (start/end events,
        contextvar activation, latency)."""
        chosen_tier = tier or _tiers.classify(message)

        # ── Memory + RAG context (policy-gated) ──────────────────────────
        mem_enabled = (
            self.policy.memory_enabled if use_memory is None else use_memory
        )
        mem_ctx: Optional[str] = None
        if mem_enabled:
            try:
                hits = await _memory.arecall(message, n=4)
                mem_ctx = _memory.format_recall(hits) if hits else None
            except Exception:
                mem_ctx = None

        rag_enabled = (
            self.policy.rag_enabled if use_rag is None else use_rag
        )
        rag_ctx: Optional[str] = None
        if rag_enabled:
            try:
                hits = await _rag.aquery(message, n=3)
                rag_ctx = _rag.format_query(hits) if hits else None
            except Exception:
                rag_ctx = None

        # ── Build the tool catalog visible to the planner ────────────────
        max_iters = (
            DEFAULT_MAX_TOOL_ITERATIONS
            if max_tool_iterations is None
            else max(0, int(max_tool_iterations))
        )
        schemas: list[ToolSchema] = []
        if max_iters > 0:
            for name in self.tool_registry.list():
                if not self.allows_tool(name):
                    continue
                tool = self.tool_registry.get(name)
                schema = ToolSchema.from_tool(tool)
                if schema is not None:
                    schemas.append(schema)

        # ── Compose the system prompt ────────────────────────────────────
        base_system = (
            system if system is not None else self.policy.system_prompt
        )
        tool_prompt = build_tool_use_prompt(schemas) if schemas else ""
        if tool_prompt:
            base_system = base_system + "\n\n" + tool_prompt
        full_system = _skills.build_system_prompt(
            base=base_system,
            skill=skill,
            memory_context=mem_ctx,
            rag_context=rag_ctx,
        )

        # ── No tools → fast path: single call (identical to legacy) ──────
        if not schemas:
            result = await _router.call(
                message,
                tier=chosen_tier,
                system=full_system,
                history=history,
            )
            result["tier"] = chosen_tier
            result.setdefault("tool_calls", [])
            result.setdefault("iterations", 0)
            return result

        # ── Tool loop ────────────────────────────────────────────────────
        return await self._run_tool_loop(
            message=message,
            system=full_system,
            tier=chosen_tier,
            history=list(history) if history else [],
            max_iters=max_iters,
        )

    async def _run_tool_loop(
        self,
        *,
        message: str,
        system: str,
        tier: str,
        history: list[dict],
        max_iters: int,
    ) -> dict:
        """LLM-driven tool-calling loop. See :meth:`chat` for semantics."""
        import time as _time

        tel = self.telemetry
        tool_calls: list[dict] = []
        last_result: Optional[dict] = None

        # Per-iteration state. ``current_message`` is what we send each turn:
        # the original message on iteration 0, then the labeled tool result
        # on subsequent iterations.
        current_message = message
        local_history = history

        for iteration in range(1, max_iters + 1):
            iter_t0 = _time.perf_counter()
            emit_iteration_start(
                tel, iteration=iteration, message_preview=current_message
            )

            result = await _router.call(
                current_message,
                tier=tier,
                system=system,
                history=local_history,
            )
            last_result = result
            content = (result.get("content") or "").strip()

            call = parse_tool_call(content)
            if call is None:
                # Final natural-language answer.
                _agent_logger.info(
                    "tool loop finished",
                    extra={
                        "user": self.user_id,
                        "mode": self.policy.mode,
                        "iterations": iteration - 1,
                        "outcome": "final_answer",
                    },
                )
                emit_iteration_end(
                    tel,
                    iteration=iteration,
                    outcome="final_answer",
                    duration_ms=(_time.perf_counter() - iter_t0) * 1000.0,
                )
                emit_loop_finished(tel, iterations=iteration - 1, outcome="final_answer")
                result["tier"] = tier
                result["tool_calls"] = tool_calls
                result["iterations"] = iteration - 1
                return result

            # The model wants a tool. Append both turns to history so the
            # next call sees the conversation as it really happened.
            local_history = local_history + [
                {"role": "user", "content": current_message},
                {"role": "assistant", "content": content},
            ]

            tool_step: dict = {
                "iteration": iteration,
                "tool": call.name,
                "input": call.input,
            }
            iter_outcome = "tool_ok"
            try:
                tool_result = await self.tool_executor.execute(call.name, call.input)
                tool_step["ok"] = True
                tool_step["result"] = tool_result
                next_message = format_tool_result(call.name, tool_result)
                _agent_logger.info(
                    "tool loop step",
                    extra={
                        "user": self.user_id,
                        "mode": self.policy.mode,
                        "iteration": iteration,
                        "tool": call.name,
                        "outcome": "ok",
                    },
                )
            except ToolPermissionError as e:
                tool_step["ok"] = False
                tool_step["error"] = str(e)
                tool_step["error_type"] = "permission"
                iter_outcome = "tool_denied"
                next_message = format_tool_result(call.name, None, error=str(e))
                _agent_logger.warning(
                    "tool loop denied",
                    extra={
                        "user": self.user_id,
                        "mode": self.policy.mode,
                        "iteration": iteration,
                        "tool": call.name,
                        "outcome": "denied",
                    },
                )
            except ToolNotFoundError as e:
                tool_step["ok"] = False
                tool_step["error"] = str(e)
                tool_step["error_type"] = "not_found"
                iter_outcome = "tool_not_found"
                next_message = format_tool_result(call.name, None, error=str(e))
                _agent_logger.warning(
                    "tool loop missing",
                    extra={
                        "user": self.user_id,
                        "mode": self.policy.mode,
                        "iteration": iteration,
                        "tool": call.name,
                        "outcome": "missing",
                    },
                )
            except Exception as e:
                tool_step["ok"] = False
                tool_step["error"] = f"{type(e).__name__}: {e}"
                tool_step["error_type"] = "tool_exception"
                iter_outcome = "tool_error"
                next_message = format_tool_result(call.name, None, error=str(e))
                _agent_logger.error(
                    "tool loop error: %s",
                    e,
                    extra={
                        "user": self.user_id,
                        "mode": self.policy.mode,
                        "iteration": iteration,
                        "tool": call.name,
                        "outcome": "error",
                    },
                )

            tool_calls.append(tool_step)
            emit_iteration_end(
                tel,
                iteration=iteration,
                outcome=iter_outcome,
                tool=call.name,
                duration_ms=(_time.perf_counter() - iter_t0) * 1000.0,
            )
            current_message = next_message

        # Cap reached without a final natural-language answer. Return the
        # last router response with a clear hint that the loop terminated
        # on the iteration cap rather than on a final answer.
        _agent_logger.warning(
            "tool loop hit iteration cap",
            extra={
                "user": self.user_id,
                "mode": self.policy.mode,
                "iterations": max_iters,
                "outcome": "max_iterations",
            },
        )
        emit_loop_max_iterations(tel, max_iters=max_iters)
        emit_loop_finished(tel, iterations=max_iters, outcome="max_iterations")
        if last_result is None:
            # Should be unreachable (max_iters > 0 is enforced upstream),
            # but kept for safety.
            last_result = {"content": "", "model": "", "tokens": 0}
        last_result["tier"] = tier
        last_result["tool_calls"] = tool_calls
        last_result["iterations"] = max_iters
        last_result["max_iterations_reached"] = True
        return last_result

    async def execute(self, task: dict) -> dict:
        """Run a structured task.

        ``task`` is a dict with any of:
            prompt | message       — the user prompt (required)
            system                 — system prompt override
            tier                   — "fast" | "deep"
            history                — list[dict]
            skill                  — activate skill for this turn
            use_memory             — per-call gate override (defaults to policy)
            use_rag                — per-call gate override (defaults to policy)
            max_tool_iterations    — agent-loop cap override (default 3)

        Returns the same shape as :meth:`chat`.
        """
        prompt = task.get("prompt") or task.get("message")
        if not prompt:
            raise ValueError("task must include 'prompt' or 'message'")
        return await self.chat(
            prompt,
            system=task.get("system"),
            tier=task.get("tier"),
            history=task.get("history"),
            skill=task.get("skill"),
            max_tool_iterations=task.get("max_tool_iterations"),
            use_memory=task.get("use_memory"),
            use_rag=task.get("use_rag"),
        )

    # ── Multi-agent runtime entry point ──────────────────────────────────

    async def run_task(
        self,
        input: str,
        *,
        max_steps: Optional[int] = None,
    ):
        """Plan + execute a multi-step task.

        Pipeline:
          1. ``create_task(input)``                       → ``state="created"``
          2. ``PlannerAgent(self).plan(task)``            → ``state="planned"``
              (sets ``task.plan``; or ``"failed"`` on parse error)
          3. ``ExecutorAgent(self, max_steps).run(task)`` → ``state="done"``
              (sets ``task.result``; per-step errors recorded inline)

        This is additive — :meth:`chat`, :meth:`execute`, and
        :meth:`use_tool` are untouched. Callers can still drive the brain
        directly without going through the agent runtime.

        Returns the final :class:`BrainTask` (frozen) with the full plan +
        result attached.
        """
        import dataclasses as _dc
        import time as _time

        steps_cap = (
            DEFAULT_MAX_STEPS if max_steps is None else max(1, int(max_steps))
        )

        with self.telemetry.activate():
            t0 = _time.perf_counter()
            task = create_task(input)
            self.telemetry.emit(
                EVENT_TASK_START,
                task_id=task.id,
                input_len=len(input or ""),
                max_steps=steps_cap,
            )

            try:
                # Plan (no tool execution possible inside).
                task = await PlannerAgent(self).plan(task)
                if task.state == "failed":
                    duration_ms = (_time.perf_counter() - t0) * 1000.0
                    self.telemetry.emit(
                        EVENT_TASK_END,
                        task_id=task.id,
                        state=task.state,
                        duration_ms=duration_ms,
                        reason="planning_failed",
                    )
                    self.telemetry.record_latency("task", duration_ms)
                    return task

                # Execute (the only agent that may touch tools).
                task = await ExecutorAgent(self, max_steps=steps_cap).run(task)
                duration_ms = (_time.perf_counter() - t0) * 1000.0
                self.telemetry.emit(
                    EVENT_TASK_END,
                    task_id=task.id,
                    state=task.state,
                    duration_ms=duration_ms,
                    step_count=len((task.result or {}).get("steps") or []),
                    truncated=bool((task.result or {}).get("truncated")),
                )
                self.telemetry.record_latency("task", duration_ms)
                return task
            except Exception as e:
                duration_ms = (_time.perf_counter() - t0) * 1000.0
                self.telemetry.emit(
                    EVENT_TASK_END,
                    task_id=task.id,
                    state="failed",
                    duration_ms=duration_ms,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                self.telemetry.record_latency("task", duration_ms)
                # Return a failed snapshot — never raise out of run_task.
                return _dc.replace(
                    task,
                    state="failed",
                    result={"error": f"{type(e).__name__}: {e}"},
                )

    # ── Streaming (used by the chat/stream SSE endpoint) ─────────────────

    async def stream(
        self,
        message: str,
        *,
        system: Optional[str] = None,
        tier: Optional[str] = None,
        history: Optional[list[dict]] = None,
    ) -> AsyncIterator[str]:
        """Token-stream a chat turn. Yields content chunks as they arrive."""
        chosen_tier = tier or _tiers.classify(message)
        base_system = (
            system if system is not None else self.policy.system_prompt
        )
        async for chunk in _router.stream(
            message,
            tier=chosen_tier,
            system=base_system,
            history=history,
        ):
            yield chunk


# Re-export the MemoryStore class as a type-only public symbol so consumers
# can type-annotate (``store: MemoryStore``) without piercing the boundary.
# Runtime construction must still go through ``BrainClient.memory.MemoryStore``.
MemoryStore = _memory.MemoryStore


__all__ = [
    "BrainClient",
    "Mode",
    "MemoryStore",
    # Policy surface, re-exported so consumers never need to import
    # ``infra.brain.policy`` directly:
    "BrainPolicy",
    "NAI_POLICY",
    "NARAI_POLICY",
    "SAFE_TOOLS",
    "get_policy",
    "available_modes",
    # Tools surface, re-exported so consumers never need to import
    # ``infra.brain.tools`` directly:
    "Tool",
    "ToolRegistry",
    "ToolSchema",
    "ToolExecutor",
    "ToolPermissionError",
    "ToolNotFoundError",
    "default_registry",
    "register_tool",
    "DEFAULT_MAX_TOOL_ITERATIONS",
    # Telemetry surface, re-exported so consumers never need to import
    # ``infra.brain.telemetry`` directly:
    "TelemetryCollector",
    "get_current_telemetry",
    # Agent runtime surface, re-exported so consumers never need to import
    # ``infra.brain.agents`` directly:
    "BrainTask",
    "TaskState",
    "create_task",
    "PlannerAgent",
    "ExecutorAgent",
    "AgentMessage",
    "format_plan_message",
    "format_tool_message",
    "DEFAULT_MAX_STEPS",
    "HARD_MAX_STEPS",
]
