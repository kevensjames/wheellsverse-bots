"""CI auto-fix: maps a failure analysis to a minimal, diff-style suggestion.

This is a *suggestion engine*. It NEVER applies changes; it does NEVER
import the modules it talks about; it has NEVER side effects. Importing
the module costs nothing and changes nothing about the brain runtime.

The single public function :func:`suggest_fix` takes the dict produced
by :func:`infra.brain.debug.ci_self_healing.analyze_ci_failure` and
returns a *fix proposal* dict the developer can read and apply by hand.

Architectural rules baked into every entry of the fix table:

  * Patches target the smallest possible change set.
  * Patches preserve the public surface of ``BrainClient``.
  * Patches preserve the planner ⊕ executor separation:
      - the planner never gains tool-execution capability,
      - the executor remains the single tool caller.
  * Patches never disable telemetry or remove a safety guard.

If a confident, minimal fix cannot be derived, the system says so by
returning a low-confidence advisory rather than fabricating a diff.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Optional


# ── Fix-type vocabulary ─────────────────────────────────────────────────────
#
# Stable strings. Match the categories listed in the spec. Anything else
# is normalised to "logic" — the most generic category — at output time.

FIX_TYPE_SCHEMA: str = "schema"
FIX_TYPE_LOGIC: str = "logic"
FIX_TYPE_ORDERING: str = "ordering"
FIX_TYPE_MISSING_EVENT: str = "missing_event"
FIX_TYPE_CRASH: str = "crash"
FIX_TYPE_CONFIG: str = "config"

_VALID_FIX_TYPES = frozenset({
    FIX_TYPE_SCHEMA, FIX_TYPE_LOGIC, FIX_TYPE_ORDERING,
    FIX_TYPE_MISSING_EVENT, FIX_TYPE_CRASH, FIX_TYPE_CONFIG,
})


# Risk levels — also stable strings.
RISK_LOW: str = "low"
RISK_MEDIUM: str = "medium"
RISK_HIGH: str = "high"

_VALID_RISK_LEVELS = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH})


# ── Fix templates ───────────────────────────────────────────────────────────
#
# Every template is a closed form (no placeholders). Confidence reflects
# how well the (stage, reason) tuple uniquely identifies the offending
# location: high when the diagnostic message points at one place, low
# when several modules could be the culprit.


def _planner_invalid_plan_from_llm() -> dict:
    return {
        "root_cause": (
            "Planner ran but the LLM response could not be parsed into "
            "{'steps': [...]}. The router boundary returned text the "
            "validator rejected."
        ),
        "fix_type": FIX_TYPE_SCHEMA,
        "patch": (
            "--- a/infra/brain/agents/planner.py\n"
            "+++ b/infra/brain/agents/planner.py\n"
            "@@ async def plan(self, task: BrainTask) -> BrainTask:\n"
            "         raw = (result.get(\"content\") or \"\").strip()\n"
            "         plan = parse_plan(raw)\n"
            "+        # Single retry with a stricter system prompt — LLMs\n"
            "+        # occasionally wrap JSON in prose on the first try.\n"
            "+        if plan is None:\n"
            "+            stricter = system_prompt + \"\\n\\nIMPORTANT: \"\n"
            "+                       \"respond with the JSON object only. \"\n"
            "+                       \"No prose, no code fences.\"\n"
            "+            retry = await self.brain.chat(\n"
            "+                task.input, system=stricter,\n"
            "+                max_tool_iterations=0,\n"
            "+                use_memory=False, use_rag=False,\n"
            "+            )\n"
            "+            plan = parse_plan((retry.get(\"content\") or \"\").strip())\n"
            "         duration_ms = (time.perf_counter() - t0) * 1000.0\n"
        ),
        "confidence": 0.7,
        "risk_level": RISK_LOW,
        "explanation": (
            "Adds one bounded retry with a stricter prompt. The retry path "
            "still uses max_tool_iterations=0, so the planner safety "
            "invariant (no tool execution) is preserved. Failing the second "
            "attempt still falls through to the existing invalid_plan branch."
        ),
    }


def _planner_did_not_start() -> dict:
    return {
        "root_cause": (
            "PlannerAgent.plan() returned without firing plan_start. The "
            "agent constructor or the run_task wiring is broken."
        ),
        "fix_type": FIX_TYPE_MISSING_EVENT,
        "patch": (
            "--- a/infra/brain/agents/planner.py\n"
            "+++ b/infra/brain/agents/planner.py\n"
            "@@ async def plan(self, task: BrainTask) -> BrainTask:\n"
            "         tel = self.brain.telemetry\n"
            "         t0 = time.perf_counter()\n"
            "-        if tel.enabled:\n"
            "-            tel.emit(EVENT_PLAN_START, task_id=task.id, ...)\n"
            "+        # plan_start MUST fire unconditionally before any\n"
            "+        # work that could raise — observability contract.\n"
            "+        if tel and tel.enabled:\n"
            "+            tel.emit(\n"
            "+                EVENT_PLAN_START,\n"
            "+                task_id=task.id,\n"
            "+                input_len=len(task.input or \"\"),\n"
            "+            )\n"
        ),
        "confidence": 0.55,
        "risk_level": RISK_LOW,
        "explanation": (
            "Hardens the plan_start emit to defend against a None-valued "
            "or non-enabled collector. Does NOT change the contract — "
            "still a no-op when telemetry is disabled."
        ),
    }


def _planner_no_or_empty_plan(reason: str) -> dict:
    return {
        "root_cause": (
            f"Executor refused to run because the planner produced "
            f"{reason!r}. The validator accepted an empty/missing steps list."
        ),
        "fix_type": FIX_TYPE_SCHEMA,
        "patch": (
            "--- a/infra/brain/agents/planner.py\n"
            "+++ b/infra/brain/agents/planner.py\n"
            "@@ def _validate(obj):\n"
            "     if not isinstance(obj, dict):\n"
            "         return None\n"
            "     steps = obj.get(\"steps\")\n"
            "-    if not isinstance(steps, list):\n"
            "+    if not isinstance(steps, list) or len(steps) == 0:\n"
            "         return None\n"
        ),
        "confidence": 0.85,
        "risk_level": RISK_LOW,
        "explanation": (
            "Rejects empty plans at parse time so the executor's "
            "fail-state path never has to deal with them. No change to "
            "the public schema — the planner already advertises a minimum "
            "of 1 step in its system prompt."
        ),
    }


def _planner_tool_leakage() -> dict:
    """A variant of invalid_plan_from_llm where the LLM emitted a bare
    tool-call envelope. The validator must reject it."""
    return {
        "root_cause": (
            "LLM emitted a bare tool-call envelope ({'tool': ..., "
            "'input': ...}) instead of a plan. The validator must reject "
            "any structure missing the 'steps' key."
        ),
        "fix_type": FIX_TYPE_SCHEMA,
        "patch": (
            "--- a/infra/brain/agents/planner.py\n"
            "+++ b/infra/brain/agents/planner.py\n"
            "@@ def _validate(obj):\n"
            "     if not isinstance(obj, dict):\n"
            "         return None\n"
            "+    # Reject tool-call envelopes outright — the planner must\n"
            "+    # never accept anything that looks like a tool invocation.\n"
            "+    if \"tool\" in obj and \"steps\" not in obj:\n"
            "+        return None\n"
            "     steps = obj.get(\"steps\")\n"
        ),
        "confidence": 0.9,
        "risk_level": RISK_LOW,
        "explanation": (
            "Defends the planner-cannot-trigger-tools invariant at parse "
            "time. Even if max_tool_iterations=0 ever regressed, the "
            "validator would still reject the envelope."
        ),
    }


def _executor_never_ran_steps() -> dict:
    return {
        "root_cause": (
            "A valid plan was attached but no step_* events fired. The "
            "executor was not invoked, or its dispatch loop is broken."
        ),
        "fix_type": FIX_TYPE_LOGIC,
        "patch": (
            "--- a/infra/brain/interface.py\n"
            "+++ b/infra/brain/interface.py\n"
            "@@ async def run_task(self, input: str, *, max_steps=None):\n"
            "                 task = await PlannerAgent(self).plan(task)\n"
            "                 if task.state == \"failed\":\n"
            "                     ...\n"
            "                     return task\n"
            "-                task = await ExecutorAgent(self, max_steps=steps_cap).run(task)\n"
            "+                executor = ExecutorAgent(self, max_steps=steps_cap)\n"
            "+                task = await executor.run(task)\n"
            "+                # Defensive: if the executor returned without\n"
            "+                # populating result.steps, surface as failure.\n"
            "+                if task.result is None or not task.result.get(\"steps\"):\n"
            "+                    task = _dc.replace(\n"
            "+                        task, state=\"failed\",\n"
            "+                        result={\"error\": \"executor_produced_no_steps\"},\n"
            "+                    )\n"
        ),
        "confidence": 0.6,
        "risk_level": RISK_MEDIUM,
        "explanation": (
            "Adds a post-condition check that the executor produced step "
            "records. Catches a silent loop-skip without changing the "
            "public return shape (state still ∈ {done, failed})."
        ),
    }


def _executor_step_crash_isolation() -> dict:
    """Used for unhandled_* exceptions that escape run_task."""
    return {
        "root_cause": (
            "An exception escaped run_task. The executor's per-step "
            "isolation block did not match the raised exception type."
        ),
        "fix_type": FIX_TYPE_CRASH,
        "patch": (
            "--- a/infra/brain/agents/executor.py\n"
            "+++ b/infra/brain/agents/executor.py\n"
            "@@ async def _run_step(self, task, index, step, prior):\n"
            "         try:\n"
            "             ...\n"
            "         except (ToolPermissionError, ToolNotFoundError) as e:\n"
            "             ...\n"
            "-        except Exception as e:\n"
            "+        except Exception as e:  # final per-step catch-all\n"
            "             record.update({\n"
            "                 \"name\": step.get(\"name\") if kind == \"tool\" else None,\n"
            "                 \"ok\": False,\n"
            "                 \"error_type\": type(e).__name__,\n"
            "                 \"error\": str(e),\n"
            "             })\n"
            "+            # Do NOT add `except BaseException`; KeyboardInterrupt\n"
            "+            # and SystemExit must still propagate. If a non-Exception\n"
            "+            # subclass leaks through, fix the call site, not here.\n"
        ),
        "confidence": 0.5,
        "risk_level": RISK_MEDIUM,
        "explanation": (
            "Documents the catch-all boundary. The actual leak is more "
            "likely caused by an `await` outside the try block or by an "
            "exception raised in the telemetry emit path itself — inspect "
            "the stack of the escaping exception."
        ),
    }


def _executor_max_steps_overflow() -> dict:
    return {
        "root_cause": (
            "Executor ran more than HARD_MAX_STEPS (10) steps. The "
            "max_steps clamp regressed."
        ),
        "fix_type": FIX_TYPE_LOGIC,
        "patch": (
            "--- a/infra/brain/agents/executor.py\n"
            "+++ b/infra/brain/agents/executor.py\n"
            "@@ class ExecutorAgent:\n"
            "     def __init__(self, brain, *, max_steps=DEFAULT_MAX_STEPS):\n"
            "         self.brain = brain\n"
            "-        self.max_steps = min(max(int(max_steps), 1), HARD_MAX_STEPS)\n"
            "+        # Two-sided clamp: ≥ 1 (must run something) AND\n"
            "+        # ≤ HARD_MAX_STEPS (cannot exceed the cap, ever).\n"
            "+        clamped = max(int(max_steps), 1)\n"
            "+        self.max_steps = min(clamped, HARD_MAX_STEPS)\n"
        ),
        "confidence": 0.95,
        "risk_level": RISK_LOW,
        "explanation": (
            "Identical semantics to the original one-liner, written as "
            "two steps so a future refactor can't accidentally drop the "
            "upper bound. Hard cap is the safety contract."
        ),
    }


def _tool_permission_denied() -> dict:
    return {
        "root_cause": (
            "A planned tool was rejected by the policy gate. The active "
            "BrainPolicy.allowed_tools tuple does not include the tool name."
        ),
        "fix_type": FIX_TYPE_CONFIG,
        "patch": (
            "--- a/infra/brain/policy.py\n"
            "+++ b/infra/brain/policy.py\n"
            "@@ SAFE_TOOLS: tuple[str, ...] = (\n"
            "     \"web_search\",\n"
            "     \"read_file\",\n"
            "     \"recall_memory\",\n"
            "     \"query_rag\",\n"
            "+    # Add the missing tool name here, ONLY if it is read-only\n"
            "+    # and side-effect-free. NEVER add a destructive tool to\n"
            "+    # SAFE_TOOLS — that's reserved for NarAI's unrestricted\n"
            "+    # policy (allowed_tools=None).\n"
            "+    # \"<tool_name>\",\n"
            " )\n"
        ),
        "confidence": 0.6,
        "risk_level": RISK_MEDIUM,
        "explanation": (
            "Allowing a tool under NAI's policy is a security decision: it "
            "MUST stay read-only and side-effect-free. If the tool is for "
            "NarAI use only, register it normally — NarAI's "
            "allowed_tools=None already authorises every registered tool."
        ),
    }


def _tool_not_found() -> dict:
    return {
        "root_cause": (
            "A planned tool name is missing from the registry the "
            "BrainClient was constructed with."
        ),
        "fix_type": FIX_TYPE_CONFIG,
        "patch": (
            "--- a/infra/brain/tools/builtin.py\n"
            "+++ b/infra/brain/tools/builtin.py\n"
            "@@ def register_demo_tools() -> None:\n"
            "     reg = default_registry()\n"
            "     reg.replace(WEB_SEARCH_TOOL)\n"
            "+    # Register additional tools whose names the planner emits.\n"
            "+    # Use replace() so the call is idempotent across reloads.\n"
            "+    # reg.replace(<YOUR_TOOL>)\n"
        ),
        "confidence": 0.7,
        "risk_level": RISK_LOW,
        "explanation": (
            "If the tool exists elsewhere, prefer registering it via "
            "register_tool() at module import time so every BrainClient "
            "sees it. Avoid per-test registration unless the registry is "
            "being snapshotted (the conftest already does this)."
        ),
    }


def _tool_runtime_error() -> dict:
    return {
        "root_cause": (
            "A registered tool's run() body raised. The executor isolated "
            "the failure (state remained 'done'), but the tool itself is "
            "broken or its inputs are malformed."
        ),
        "fix_type": FIX_TYPE_CRASH,
        "patch": (
            "--- a/<your_tool_module>.py\n"
            "+++ b/<your_tool_module>.py\n"
            "@@ async def _run(input: dict) -> dict:\n"
            "     query = str(input.get(\"query\", \"\")).strip()\n"
            "-    if not query:\n"
            "-        raise ValueError(\"web_search requires a non-empty 'query'\")\n"
            "+    # Validate inputs explicitly and raise a typed error\n"
            "+    # — the executor logs this as step.error_type=ValueError.\n"
            "+    if not query:\n"
            "+        raise ValueError(\"missing required 'query'\")\n"
            "     # ... rest of tool body wrapped so transient failures\n"
            "     # surface a clean, structured error to the executor.\n"
        ),
        "confidence": 0.4,
        "risk_level": RISK_LOW,
        "explanation": (
            "Without the actual tool code we cannot suggest a precise "
            "fix. The pattern shown is the typical shape: validate inputs "
            "first, raise typed exceptions for the executor to record, "
            "and let the brain's per-step isolation do its job."
        ),
    }


def _telemetry_no_events() -> dict:
    return {
        "root_cause": (
            "Brain returned a result but the telemetry collector recorded "
            "zero events. Either telemetry was disabled at construction "
            "or the ContextVar bridge is broken."
        ),
        "fix_type": FIX_TYPE_MISSING_EVENT,
        "patch": (
            "--- a/<your_test_or_setup>.py\n"
            "+++ b/<your_test_or_setup>.py\n"
            "@@ # Constructing the BrainClient\n"
            "-client = BrainClient(\n"
            "-    user_id=\"x\", mode=\"narai\", telemetry_enabled=False,\n"
            "-)\n"
            "+client = BrainClient(\n"
            "+    user_id=\"x\", mode=\"narai\",\n"
            "+    # Telemetry must be ON for CI runs — the diagnostic\n"
            "+    # layer relies on the event stream.\n"
            "+    telemetry_enabled=True,\n"
            "+)\n"
        ),
        "confidence": 0.6,
        "risk_level": RISK_LOW,
        "explanation": (
            "Most common cause is an explicit telemetry_enabled=False. If "
            "telemetry was meant to be on, also confirm self.telemetry."
            "activate() is called inside chat() / run_task() before any "
            "downstream emit() runs."
        ),
    }


def _telemetry_ordering(reason: str) -> dict:
    nice = {
        "task_start_not_first": "task_start fired after another task_* event",
        "task_end_not_last":    "task_end fired before another task_* event",
        "duplicate_task_brackets": "task_start/task_end fired more than once",
        "step_event_before_plan_event":
            "a step_* event fired before any plan_* event",
    }.get(reason, reason)
    return {
        "root_cause": f"Telemetry ordering invariant violated: {nice}.",
        "fix_type": FIX_TYPE_ORDERING,
        "patch": (
            "--- a/infra/brain/interface.py\n"
            "+++ b/infra/brain/interface.py\n"
            "@@ async def run_task(self, input: str, *, max_steps=None):\n"
            "         with self.telemetry.activate():\n"
            "             t0 = _time.perf_counter()\n"
            "             task = create_task(input)\n"
            "+            # task_start MUST be the first event of the activate()\n"
            "+            # block. No other emit() call may precede it.\n"
            "             self.telemetry.emit(\n"
            "                 EVENT_TASK_START,\n"
            "                 task_id=task.id,\n"
            "                 input_len=len(input or \"\"),\n"
            "                 max_steps=steps_cap,\n"
            "             )\n"
            "             try:\n"
            "                 ...\n"
            "             finally:\n"
            "+                # task_end MUST be the last event before exiting\n"
            "+                # the activate() block — across success AND failure.\n"
            "                 self.telemetry.emit(EVENT_TASK_END, ...)\n"
        ),
        "confidence": 0.65,
        "risk_level": RISK_MEDIUM,
        "explanation": (
            "Codifies the bracket invariant in the run_task body. The diff "
            "shown is illustrative — the actual fix may be moving an "
            "emit() call out of a sub-function back into run_task itself."
        ),
    }


def _router_unhandled_llm_error() -> dict:
    return {
        "root_cause": (
            "The router/LLM boundary raised. Either the litellm patch in "
            "your CI fixtures is missing, or the real provider returned a "
            "transport-level error."
        ),
        "fix_type": FIX_TYPE_CRASH,
        "patch": (
            "--- a/infra/brain/router.py\n"
            "+++ b/infra/brain/router.py\n"
            "@@ async def call(prompt, *, tier=\"fast\", system=None,\n"
            "                 history=None, **kwargs):\n"
            "     models = _models_for(tier)\n"
            "     last_exc = None\n"
            "     for model in models:\n"
            "         try:\n"
            "             ...\n"
            "         except Exception as exc:\n"
            "             last_exc = exc\n"
            "             continue\n"
            "-    raise RuntimeError(f\"All models failed: {last_exc}\")\n"
            "+    # All providers exhausted — surface the last seen error\n"
            "+    # with provider context so the diagnostic layer can\n"
            "+    # classify it as a router-stage failure.\n"
            "+    raise RuntimeError(\n"
            "+        f\"All models failed (last={type(last_exc).__name__}): \"\n"
            "+        f\"{last_exc}\"\n"
            "+    ) from last_exc\n"
        ),
        "confidence": 0.5,
        "risk_level": RISK_MEDIUM,
        "explanation": (
            "Preserves the chain via `from last_exc` so a developer can "
            "see the underlying cause. If this is hitting in a unit test, "
            "the fixture is probably missing the litellm.acompletion patch."
        ),
    }


# ── Lookup table ────────────────────────────────────────────────────────────


_EXACT_FIXES: dict[tuple[str, str], Any] = {
    # planner
    ("planner", "planner_did_not_start"): _planner_did_not_start,
    ("planner", "no_plan"):                _planner_no_or_empty_plan,
    ("planner", "empty_plan"):             _planner_no_or_empty_plan,
    # router
    ("router", "invalid_plan_from_llm"):   _planner_invalid_plan_from_llm,
    # tool
    ("tool",   "tool_permission_denied"):  _tool_permission_denied,
    ("tool",   "tool_not_found"):          _tool_not_found,
    ("tool",   "tool_runtime_error"):      _tool_runtime_error,
    # executor
    ("executor", "executor_never_ran_steps"): _executor_never_ran_steps,
    # telemetry
    ("telemetry", "no_events_recorded"):           _telemetry_no_events,
    ("telemetry", "task_start_not_first"):         _telemetry_ordering,
    ("telemetry", "task_end_not_last"):            _telemetry_ordering,
    ("telemetry", "duplicate_task_brackets"):      _telemetry_ordering,
    ("telemetry", "step_event_before_plan_event"): _telemetry_ordering,
}


def _stage_fallback(stage: str, reason: str) -> dict:
    """Coarse fallback when no exact (stage, reason) entry matches."""
    if stage == "executor":
        return _executor_step_crash_isolation()
    if stage == "router":
        return _router_unhandled_llm_error()
    if stage == "planner":
        # Most planner failures are schema-shaped — point at the validator.
        return _planner_tool_leakage()
    if stage == "tool":
        return _tool_runtime_error()
    if stage == "telemetry":
        return _telemetry_no_events()
    return {
        "root_cause": (
            f"Unable to derive a confident root cause from "
            f"stage={stage!r}, reason={reason!r}."
        ),
        "fix_type": FIX_TYPE_LOGIC,
        "patch": "",
        "confidence": 0.1,
        "risk_level": RISK_LOW,
        "explanation": (
            "The diagnostic layer could not classify the failure. Inspect "
            "the test's failing assertion against the event timeline + "
            "task.result manually."
        ),
    }


# ── Public API ──────────────────────────────────────────────────────────────


def suggest_fix(
    failure_analysis: dict,
    *,
    context: Optional[Any] = None,
) -> dict:
    """Map a failure analysis dict to a structured fix proposal.

    Parameters
    ----------
    failure_analysis:
        The dict returned by
        :func:`infra.brain.debug.ci_self_healing.analyze_ci_failure`.
    context:
        Optional :class:`infra.brain.debug.repair_generator.FailureContext`.
        When supplied, the file-aware generator is consulted FIRST. If it
        produces a clean (placeholder-free, real-file) patch above its
        confidence floor, that wins. Otherwise the existing template
        path runs unchanged. Backwards-compatible: every existing caller
        that passes only a positional dict keeps the original behavior.

    Returns
    -------
    dict with keys:
        ``stage``          — copied from the input analysis
        ``root_cause``     — concrete reason narrative
        ``fix_type``       — one of: schema, logic, ordering, missing_event,
                              crash, config (template path) OR one of
                              parser_fix, executor_fix, tool_fix, safety_fix,
                              ci_fix (generator path)
        ``patch``          — unified-diff-style suggestion (str)
        ``confidence``     — 0.0 to 1.0 (float)
        ``risk_level``     — low | medium | high
        ``explanation``    — additional context for the developer
    """
    if not isinstance(failure_analysis, dict):
        return _malformed_input("failure_analysis must be a dict")

    stage = failure_analysis.get("stage") or "unknown"
    reason = failure_analysis.get("reason") or ""

    # ── Generator-first path (preferred, when context supplied) ──────
    # Caller-supplied real files mean we can produce a real diff. If the
    # generator declines (returns None), drop into the template path.
    if context is not None:
        try:
            from infra.brain.debug.repair_generator import (
                FailureContext, RepairGenerator,
            )
            # Accept either a FailureContext or a plain dict (defensive).
            if not isinstance(context, FailureContext):
                if isinstance(context, dict):
                    context = FailureContext(
                        test_name=str(context.get("test_name") or ""),
                        error_message=str(context.get("error_message") or ""),
                        traceback=str(context.get("traceback") or ""),
                        files=dict(context.get("files") or {}),
                        recent_history=list(context.get("recent_history") or []),
                        analysis=context.get("analysis") or failure_analysis,
                    )
                else:
                    context = None
            if context is not None:
                # If the caller forgot to attach the analysis, splice it in
                # so the generator's dispatch can route on stage/reason.
                if context.analysis is None:
                    context = dataclasses.replace(context, analysis=failure_analysis)
                fix = RepairGenerator().generate_patch(context)
                if fix is not None:
                    return _finalise_generator(stage, fix)
        except Exception:
            # The generator must NEVER take down suggest_fix. Fall through
            # to the deterministic template path on any failure.
            pass

    # 1) Exception-driven reasons (e.g. "unhandled_RuntimeError")
    if reason.startswith("unhandled_"):
        proposal = _executor_step_crash_isolation()
        return _finalise(stage, proposal)

    # 2) Exact (stage, reason) match
    handler = _EXACT_FIXES.get((stage, reason))
    if handler is not None:
        try:
            proposal = handler(reason) if _accepts_one_arg(handler) else handler()
        except TypeError:
            proposal = handler()
        return _finalise(stage, proposal)

    # 3) Special case: tool leakage from the planner
    if stage == "planner" and "tool" in reason:
        return _finalise(stage, _planner_tool_leakage())

    # 4) Stage-level fallback
    return _finalise(stage, _stage_fallback(stage, reason))


# ── Helpers ─────────────────────────────────────────────────────────────────


def _accepts_one_arg(fn) -> bool:
    """True if ``fn`` is one of the arity-1 templates (e.g. takes the
    reason string). Cheap inspection that avoids importing inspect just
    for this."""
    try:
        return fn.__code__.co_argcount == 1
    except Exception:
        return False


def _finalise(stage: str, proposal: dict) -> dict:
    """Normalise output: coerce field types, clamp confidence, and ensure
    the schema the spec promises is always returned."""
    if not isinstance(proposal, dict):
        return _malformed_input("internal: handler returned non-dict")

    fix_type = proposal.get("fix_type") or FIX_TYPE_LOGIC
    if fix_type not in _VALID_FIX_TYPES:
        fix_type = FIX_TYPE_LOGIC

    risk = proposal.get("risk_level") or RISK_MEDIUM
    if risk not in _VALID_RISK_LEVELS:
        risk = RISK_MEDIUM

    try:
        confidence = float(proposal.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "stage":         stage,
        "root_cause":    str(proposal.get("root_cause") or ""),
        "fix_type":      fix_type,
        "patch":         str(proposal.get("patch") or ""),
        "confidence":    confidence,
        "risk_level":    risk,
        "explanation":   str(proposal.get("explanation") or ""),
    }


def _finalise_generator(stage: str, fix: dict) -> dict:
    """Normalise the dict returned by :class:`RepairGenerator`.

    Parallel to :func:`_finalise` but accepts the generator's broader
    fix-type vocabulary (``parser_fix``, ``executor_fix`` …). Keeps the
    output schema callers expect from :func:`suggest_fix` (``stage``,
    ``root_cause``, ``fix_type``, ``patch``, ``confidence``, ``risk_level``,
    ``explanation``) plus generator-only diagnostic keys
    (``files_modified``, ``reasoning``, ``lines_changed``)."""
    if not isinstance(fix, dict):
        return _malformed_input("internal: generator returned non-dict")

    fix_type = str(fix.get("fix_type") or "").strip()
    # Allow generator types AND template types — superset.
    if fix_type not in {
        "parser_fix", "executor_fix", "tool_fix", "safety_fix", "ci_fix",
        FIX_TYPE_SCHEMA, FIX_TYPE_LOGIC, FIX_TYPE_ORDERING,
        FIX_TYPE_MISSING_EVENT, FIX_TYPE_CRASH, FIX_TYPE_CONFIG,
    }:
        fix_type = FIX_TYPE_LOGIC

    risk = fix.get("risk_level") or RISK_MEDIUM
    if risk not in _VALID_RISK_LEVELS:
        risk = RISK_MEDIUM

    try:
        confidence = float(fix.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    # Defense in depth: if the generator somehow leaked a placeholder,
    # downgrade the patch to empty so the caller sees an advisory rather
    # than something validate_patch will reject downstream.
    patch = str(fix.get("patch") or "")
    import re as _re
    if _re.search(r"<[A-Za-z0-9_./\- ]+>", patch):
        patch = ""
        confidence = min(confidence, 0.1)

    return {
        "stage":          str(fix.get("stage") or stage or "unknown"),
        "root_cause":     str(fix.get("root_cause") or fix.get("reasoning") or ""),
        "fix_type":       fix_type,
        "patch":          patch,
        "confidence":     confidence,
        "risk_level":     risk,
        "explanation":    str(fix.get("explanation") or fix.get("reasoning") or ""),
        # Generator-only diagnostics (omitted by template path).
        "files_modified": list(fix.get("files_modified") or []),
        "reasoning":      str(fix.get("reasoning") or ""),
        "lines_changed":  int(fix.get("lines_changed") or 0),
        "source":         "generator",
    }


def _malformed_input(msg: str) -> dict:
    return {
        "stage": "unknown",
        "root_cause": msg,
        "fix_type": FIX_TYPE_LOGIC,
        "patch": "",
        "confidence": 0.0,
        "risk_level": RISK_LOW,
        "explanation": (
            "suggest_fix() received malformed input. Pass the dict "
            "returned by analyze_ci_failure() unchanged."
        ),
    }


# ── Multi-fix generation (autonomous-engineer extension) ───────────────────
#
# The single-fix path above remains the source of the targeted, stage-
# specific suggestion. The functions below let callers consider 2-3
# *alternative* fix strategies in parallel and pick the safest one
# according to their RepairMemory's score. Backwards compatible:
# ``suggest_fix`` is unchanged; consumers that don't care about
# alternatives keep using it directly.


def _generic_validation_fallback(stage: str) -> dict:
    """Universal validation-style alternative — adds an isinstance/raise
    guard. Intended as a *type* of fix the system can fall back to when
    the primary suggestion looks risky."""
    return {
        "stage": stage,
        "root_cause": "generic alternative: validate input shape before use",
        "fix_type": FIX_TYPE_SCHEMA,
        "type": "validation_fix",
        "patch": (
            "--- a/<target_module>.py\n"
            "+++ b/<target_module>.py\n"
            "@@ def <fn>(input):\n"
            "+    if not isinstance(input, dict):\n"
            "+        raise ValueError(f\"expected dict, got {type(input).__name__}\")\n"
        ),
        "confidence": 0.55,
        "risk_level": RISK_LOW,
        "explanation": (
            "Conservative validation guard. Patch is illustrative — apply "
            "only when the failure category is validation-shaped."
        ),
    }


def _generic_guardrail_fallback(stage: str) -> dict:
    """Universal try/except guardrail alternative."""
    return {
        "stage": stage,
        "root_cause": "generic alternative: catch and log instead of crashing",
        "fix_type": FIX_TYPE_CRASH,
        "type": "guardrail_fix",
        "patch": (
            "--- a/<target_module>.py\n"
            "+++ b/<target_module>.py\n"
            "@@ def <fn>(...):\n"
            "+    try:\n"
            "+        return <existing_body>\n"
            "+    except Exception as e:\n"
            "+        # diagnostic must not crash the caller\n"
            "+        return None\n"
        ),
        "confidence": 0.50,
        "risk_level": RISK_MEDIUM,
        "explanation": (
            "Catch-all guardrail. Useful when the failure stage is "
            "executor-shaped and the primary fix has low confidence."
        ),
    }


def suggest_multiple_fixes(failure_analysis: dict) -> list[dict]:
    """Return a ranked-eligible list of candidate fixes for one failure.

    The first element is the primary, stage-tailored fix from
    :func:`suggest_fix`. The second and third are generic, type-tagged
    alternatives (a validation-style fallback and a guardrail fallback)
    so the autonomous engineer has more than one option to consider.

    Each entry carries a ``"type"`` field matching the
    :mod:`infra.brain.learning` fix-pattern taxonomy
    (``validation_fix``, ``guardrail_fix``, etc.) so the ranker can
    consult per-pattern reputation.
    """
    primary = suggest_fix(failure_analysis)
    # Tag the primary with its inferred fix-pattern type; map fix_type
    # values to the learning-layer taxonomy so the ranker sees a
    # consistent vocabulary.
    primary_type = _infer_pattern_for_primary(primary)
    primary_with_type = dict(primary)
    primary_with_type.setdefault("type", primary_type)

    stage = (failure_analysis or {}).get("stage") or "unknown"
    fallbacks = [
        _generic_validation_fallback(stage),
        _generic_guardrail_fallback(stage),
    ]
    # Drop fallbacks whose type matches the primary so we don't return
    # near-duplicates.
    fallbacks = [f for f in fallbacks if f.get("type") != primary_with_type.get("type")]

    return [primary_with_type, *fallbacks]


def _infer_pattern_for_primary(primary: dict) -> str:
    """Map ``suggest_fix``'s ``fix_type`` to the learning-layer fix-pattern
    name. Conservative — falls back to ``unclassified_fix`` rather than
    pretending to know."""
    ftype = (primary or {}).get("fix_type") or ""
    return {
        FIX_TYPE_SCHEMA:        "validation_fix",
        FIX_TYPE_CRASH:         "guardrail_fix",
        FIX_TYPE_LOGIC:         "guardrail_fix",
        FIX_TYPE_ORDERING:      "guardrail_fix",
        FIX_TYPE_MISSING_EVENT: "guardrail_fix",
        FIX_TYPE_CONFIG:        "validation_fix",
    }.get(ftype, "unclassified_fix")


def rank_fixes(
    fixes: list[dict],
    *,
    repair_memory=None,
    failure_signature: str = "",
    failure_category: str = "",
) -> list[dict]:
    """Rank candidate fixes by adaptive safety score, best first.

    Each input fix is scored using :meth:`RepairMemory.compute_final_score`
    when memory is provided; without memory, fixes are scored by their
    declared ``confidence`` alone. The returned list is a NEW list (input
    is not mutated) and each entry has a ``rank_score`` field attached
    so callers can audit the order.
    """
    if not fixes:
        return []

    scored: list[tuple[float, dict]] = []
    for fix in fixes:
        patch = str((fix or {}).get("patch") or "")
        fix_type = (fix or {}).get("type") or _infer_pattern_for_primary(fix)
        confidence = float((fix or {}).get("confidence") or 0.0)

        if repair_memory is not None and hasattr(
            repair_memory, "compute_final_score"
        ):
            try:
                breakdown = repair_memory.compute_final_score(
                    failure_signature, patch,
                    failure_category=failure_category or None,
                    fix_pattern=fix_type,
                    fix_confidence=confidence,
                )
                rank_score = float(breakdown.get("final_score", 0.0))
            except Exception:
                rank_score = confidence
        else:
            rank_score = confidence

        decorated = dict(fix)
        decorated["rank_score"] = round(rank_score, 4)
        scored.append((rank_score, decorated))

    # Stable sort, best first. Ties broken by input order so the primary
    # wins when the memory has nothing useful to say.
    scored.sort(key=lambda kv: -kv[0])
    return [item for _, item in scored]


def select_best_fix(
    fixes: list[dict],
    *,
    repair_memory=None,
    failure_signature: str = "",
    failure_category: str = "",
) -> Optional[dict]:
    """Return the highest-ranked fix, or ``None`` when the list is empty."""
    ranked = rank_fixes(
        fixes,
        repair_memory=repair_memory,
        failure_signature=failure_signature,
        failure_category=failure_category,
    )
    return ranked[0] if ranked else None


__all__ = [
    "suggest_fix",
    "suggest_multiple_fixes",
    "rank_fixes",
    "select_best_fix",
    # taxonomy constants — useful for tests that assert on the schema
    "FIX_TYPE_SCHEMA", "FIX_TYPE_LOGIC", "FIX_TYPE_ORDERING",
    "FIX_TYPE_MISSING_EVENT", "FIX_TYPE_CRASH", "FIX_TYPE_CONFIG",
    "RISK_LOW", "RISK_MEDIUM", "RISK_HIGH",
]
