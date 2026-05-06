"""CI-only self-healing debug layer for the Brain runtime.

Pure analysis. **No** runtime hooks, **no** monkey-patches, **no** mocks.
Importing this module is free; nothing it exports affects normal
execution. Tests reach for it only when they have already failed and
need to triage which layer broke.

The two primary entry points are:

  * :func:`analyze_ci_failure` — given a ``BrainTask`` (or ``None``), the
    flushed telemetry events, and an optional escaping exception, return
    a structured report identifying the broken layer + a recommendation.
  * :func:`build_debug_trace` — given the same inputs, build a replayable
    JSON-friendly trace dict that can be persisted as a CI artifact.

A small wrapper :func:`ci_wrap_run_task` calls ``BrainClient.run_task``
under a try/except so a test can capture either ``(result, None)`` or
``(None, exception)`` and feed the pair straight into
:func:`analyze_ci_failure`.

Stage taxonomy (the only values the report's ``stage`` field can take):

    planner, executor, tool, telemetry, router, unknown

The taxonomy is intentionally narrow — anything that doesn't fit cleanly
falls into ``unknown`` so engineers do not chase a misleading label.
"""
from __future__ import annotations

import sys
from typing import Any, Iterable, Optional


# ── Stage constants ─────────────────────────────────────────────────────────

STAGE_PLANNER: str = "planner"
STAGE_EXECUTOR: str = "executor"
STAGE_TOOL: str = "tool"
STAGE_TELEMETRY: str = "telemetry"
STAGE_ROUTER: str = "router"
STAGE_UNKNOWN: str = "unknown"


_KNOWN_STAGES = frozenset({
    STAGE_PLANNER, STAGE_EXECUTOR, STAGE_TOOL,
    STAGE_TELEMETRY, STAGE_ROUTER, STAGE_UNKNOWN,
})


# ── Defensive accessors (results may be BrainTask instances OR dicts) ──────


def _state_of(run_result: Any) -> Optional[str]:
    if run_result is None:
        return None
    return getattr(run_result, "state", None) or _safe_get(run_result, "state")


def _result_of(run_result: Any) -> Optional[dict]:
    if run_result is None:
        return None
    res = getattr(run_result, "result", None)
    if res is None:
        res = _safe_get(run_result, "result")
    return res if isinstance(res, dict) else None


def _plan_of(run_result: Any) -> Optional[dict]:
    if run_result is None:
        return None
    plan = getattr(run_result, "plan", None)
    if plan is None:
        plan = _safe_get(run_result, "plan")
    return plan if isinstance(plan, dict) else None


def _input_of(run_result: Any) -> Optional[str]:
    if run_result is None:
        return None
    inp = getattr(run_result, "input", None)
    if inp is None:
        inp = _safe_get(run_result, "input")
    return inp if isinstance(inp, str) else None


def _safe_get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return None


# ── Event-list helpers ──────────────────────────────────────────────────────


def _types(events: Iterable[dict]) -> list[str]:
    out: list[str] = []
    for e in events or []:
        if isinstance(e, dict):
            t = e.get("event_type")
            if isinstance(t, str):
                out.append(t)
    return out


def _has(events: Iterable[dict], event_type: str) -> bool:
    return event_type in _types(events)


def _count(events: Iterable[dict], event_type: str) -> int:
    return sum(1 for t in _types(events) if t == event_type)


def _events_by_prefix(events: Iterable[dict], prefix: str) -> list[dict]:
    return [e for e in (events or []) if isinstance(e, dict)
            and isinstance(e.get("event_type"), str)
            and e["event_type"].startswith(prefix)]


def _condense_events(events: Iterable[dict]) -> list[dict]:
    """Compact event dump for inclusion in reports — keeps just what
    a human triaging a failure actually needs to see."""
    out: list[dict] = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        meta = e.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        out.append({
            "type": e.get("event_type"),
            "ts": e.get("timestamp"),
            "tool": meta.get("tool"),
            "duration_ms": meta.get("duration_ms"),
            "outcome": meta.get("outcome"),
            "error": meta.get("error"),
            "iteration": meta.get("iteration") or meta.get("index"),
        })
    return out


# ── Telemetry-integrity check ───────────────────────────────────────────────


def _telemetry_integrity_issue(
    events: list[dict], state: Optional[str]
) -> Optional[dict]:
    """Return a telemetry-stage report if the event stream itself is broken.

    "Broken" here means the observability contract was violated — not
    that the system underneath failed (downstream stages catch that).
    """
    types = _types(events)

    # No events at all but the runtime claims to have a state → telemetry
    # is silently dropping events.
    if not types and state is not None:
        return _report(
            stage=STAGE_TELEMETRY,
            reason="no_events_recorded",
            summary=(
                "Brain returned a result but the telemetry collector recorded "
                "zero events. The collector or the ContextVar bridge is broken."
            ),
            event_trace=_condense_events(events),
            recommendation=(
                "Check TelemetryCollector.activate() and the chat/run_task "
                "instrumentation. Was BrainClient(telemetry_enabled=False) "
                "passed unintentionally?"
            ),
        )

    # task_start MUST be the first task_* event; task_end MUST be the last.
    task_events = [t for t in types if t.startswith("task_")]
    if task_events:
        if task_events[0] != "task_start":
            return _report(
                stage=STAGE_TELEMETRY,
                reason="task_start_not_first",
                summary=(
                    f"First task_* event is {task_events[0]!r} — expected "
                    f"'task_start'. Pipeline brackets are inverted."
                ),
                event_trace=_condense_events(events),
                recommendation=(
                    "Telemetry event ordering broken. Check "
                    "BrainClient.run_task — task_start must fire before any "
                    "downstream emit()."
                ),
            )
        if task_events[-1] != "task_end":
            return _report(
                stage=STAGE_TELEMETRY,
                reason="task_end_not_last",
                summary=(
                    f"Last task_* event is {task_events[-1]!r} — expected "
                    f"'task_end'. The closing bracket is missing or out of order."
                ),
                event_trace=_condense_events(events),
                recommendation=(
                    "Telemetry event ordering broken. Check that run_task "
                    "always reaches its task_end emit, including on exception."
                ),
            )
        if _count(events, "task_start") > 1 or _count(events, "task_end") > 1:
            return _report(
                stage=STAGE_TELEMETRY,
                reason="duplicate_task_brackets",
                summary=(
                    f"Saw {_count(events, 'task_start')} task_start / "
                    f"{_count(events, 'task_end')} task_end events for one run."
                ),
                event_trace=_condense_events(events),
                recommendation=(
                    "A task lifecycle event is double-emitted. Check for "
                    "nested run_task calls or duplicate activate() blocks."
                ),
            )

    # Strong ordering: any step_* must come AFTER any plan_* event.
    first_plan = next((i for i, t in enumerate(types) if t.startswith("plan_")), -1)
    first_step = next((i for i, t in enumerate(types) if t.startswith("step_")), -1)
    if first_step >= 0 and first_plan >= 0 and first_step < first_plan:
        return _report(
            stage=STAGE_TELEMETRY,
            reason="step_event_before_plan_event",
            summary=(
                f"step_* event at index {first_step} precedes the first "
                f"plan_* event at index {first_plan}. The pipeline order is "
                f"violated by the telemetry layer."
            ),
            event_trace=_condense_events(events),
            recommendation=(
                "Telemetry event ordering broken. The executor must not emit "
                "before the planner has emitted plan_end."
            ),
        )

    return None


# ── Step-record helpers (tool-error detection) ──────────────────────────────


def _step_records(result_dict: Optional[dict]) -> list[dict]:
    if not result_dict:
        return []
    steps = result_dict.get("steps")
    return list(steps) if isinstance(steps, list) else []


def _failed_step_records(result_dict: Optional[dict]) -> list[dict]:
    return [s for s in _step_records(result_dict)
            if isinstance(s, dict) and s.get("ok") is False]


# ── Exception classification ────────────────────────────────────────────────


_LLM_HINT_TOKENS = (
    "litellm", "openai", "anthropic", "rate", "timeout", "connection",
    "ssl", "completion", "401", "429", "503",
)


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Return ``(stage, recommendation)`` for an exception that escaped
    ``run_task``. ``run_task`` is contractually supposed to absorb every
    exception, so any escape implies the executor's catch-all is broken
    — hence the default stage is ``executor``."""
    name = type(exc).__name__
    text = f"{name}: {exc}".lower()

    # Tool-permission errors are subclasses of PermissionError; tool-not-found
    # is a subclass of KeyError. They should be caught by the executor — if
    # they reach the test, the executor's per-step isolation is broken.
    if "toolpermission" in text or "permissionerror" in name.lower():
        return (STAGE_TOOL,
                "ToolPermissionError escaped run_task. Executor per-step "
                "isolation is broken — verify ExecutorAgent._run_step "
                "catches ToolPermissionError.")
    if "toolnotfound" in text or "no such tool" in text:
        return (STAGE_TOOL,
                "ToolNotFoundError escaped run_task. Tool registry "
                "dispatch is broken — verify ExecutorAgent._run_step "
                "catches ToolNotFoundError.")

    # LLM transport hints — usually means the router boundary failed.
    if any(token in text for token in _LLM_HINT_TOKENS):
        return (STAGE_ROUTER,
                "Router/LLM boundary raised. Check litellm patches in CI "
                "fixtures and the planner/executor system prompts.")

    # Default — run_task is supposed to absorb. Anything else is executor.
    return (STAGE_EXECUTOR,
            "An exception escaped run_task — the executor's catch-all is "
            "broken. Add the missing except branch in ExecutorAgent.run "
            "or BrainClient.run_task.")


# ── Report builder ──────────────────────────────────────────────────────────


def _report(
    *,
    stage: str,
    reason: str,
    summary: str,
    event_trace: list[dict],
    recommendation: str,
) -> dict:
    if stage not in _KNOWN_STAGES:
        stage = STAGE_UNKNOWN
    return {
        "stage": stage,
        "reason": reason,
        "summary": summary,
        "event_trace": event_trace,
        "recommendation": recommendation,
    }


# ── Public: stage detection ─────────────────────────────────────────────────


def analyze_ci_failure(
    run_result: Any,
    events: Optional[Iterable[dict]] = None,
    exception: Optional[BaseException] = None,
) -> dict:
    """Identify which Brain stage broke and produce an actionable report.

    Parameters
    ----------
    run_result:
        The :class:`BrainTask` returned by ``BrainClient.run_task``, or
        ``None`` if an exception escaped.
    events:
        The flushed telemetry events (``client.telemetry.flush()`` output,
        i.e. a list of dicts). May be empty.
    exception:
        Any exception that escaped ``run_task``. The contract is that
        ``run_task`` never raises — so any non-None value here is itself
        a finding.

    Returns
    -------
    dict
        Shape: ``{stage, reason, summary, event_trace, recommendation}``.
    """
    events_list: list[dict] = list(events or [])

    # 1) An exception escaped run_task → break out of the contract.
    if exception is not None:
        stage, rec = _classify_exception(exception)
        return _report(
            stage=stage,
            reason=f"unhandled_{type(exception).__name__}",
            summary=(
                f"run_task() raised {type(exception).__name__}: {exception}. "
                f"The contract guarantees run_task absorbs every exception."
            ),
            event_trace=_condense_events(events_list),
            recommendation=rec,
        )

    state = _state_of(run_result)
    result_dict = _result_of(run_result)
    plan = _plan_of(run_result)

    # 2) Telemetry integrity wins next — a broken event stream invalidates
    #    every downstream signal.
    tel_issue = _telemetry_integrity_issue(events_list, state)
    if tel_issue is not None:
        return tel_issue

    # 3) Planner-stage failures.
    if state == "failed" and isinstance(result_dict, dict):
        err = (result_dict.get("error") or "")
        if "invalid_plan" in err:
            # Distinguish planner-vs-router: did the planner LLM call run
            # at all? plan_start should have fired if so.
            if not _has(events_list, "plan_start"):
                return _report(
                    stage=STAGE_PLANNER,
                    reason="planner_did_not_start",
                    summary=(
                        "State is 'failed' with invalid_plan, but plan_start "
                        "never fired — the planner agent did not run."
                    ),
                    event_trace=_condense_events(events_list),
                    recommendation=(
                        "PlannerAgent constructor or instrumentation is "
                        "broken. Check BrainClient.run_task → PlannerAgent("
                        "self).plan() wiring."
                    ),
                )
            # plan_start fired → the LLM produced an unparseable response
            return _report(
                stage=STAGE_ROUTER,
                reason="invalid_plan_from_llm",
                summary=(
                    "Planner ran but the LLM response did not parse to a "
                    "valid plan. Most likely the router/LLM boundary "
                    "returned malformed JSON."
                ),
                event_trace=_condense_events(events_list),
                recommendation=(
                    "Router/LLM boundary failed. Check the litellm response "
                    "shape in your test fixture or the planner system prompt "
                    "(content schema must use 'content' field)."
                ),
            )

        if err in ("no_plan", "empty_plan"):
            return _report(
                stage=STAGE_PLANNER,
                reason=err,
                summary=(
                    f"Executor refused to run because the plan was {err!r}."
                ),
                event_trace=_condense_events(events_list),
                recommendation=(
                    "Planner did not attach a non-empty plan to the task. "
                    "Check parse_plan validation and PlannerAgent.plan."
                ),
            )

        # state=failed but no specific reason recognised → executor area
        return _report(
            stage=STAGE_EXECUTOR,
            reason=err or "task_failed_without_reason",
            summary=(
                f"Task ended with state='failed' and no recognised error "
                f"taxonomy. Raw error: {err!r}"
            ),
            event_trace=_condense_events(events_list),
            recommendation=(
                "Executor or BrainClient.run_task hit a failure path that "
                "does not match the planner-validation taxonomy. Inspect "
                "task.result['error'] and the surrounding events."
            ),
        )

    # 4) Step-level tool failures (state may be "done" with isolated errors).
    failed_steps = _failed_step_records(result_dict)
    if failed_steps:
        permission_failures = [s for s in failed_steps
                               if s.get("error_type") == "permission"]
        not_found_failures = [s for s in failed_steps
                              if s.get("error_type") == "not_found"]
        if permission_failures:
            return _report(
                stage=STAGE_TOOL,
                reason="tool_permission_denied",
                summary=(
                    f"{len(permission_failures)} step(s) blocked by the "
                    f"policy gate (tool permission denied)."
                ),
                event_trace=_condense_events(events_list),
                recommendation=(
                    "Tool registry / permission mapping mismatch. Check "
                    "BrainPolicy.allowed_tools and the SAFE_TOOLS list."
                ),
            )
        if not_found_failures:
            return _report(
                stage=STAGE_TOOL,
                reason="tool_not_found",
                summary=(
                    f"{len(not_found_failures)} step(s) referenced an "
                    f"unregistered tool name."
                ),
                event_trace=_condense_events(events_list),
                recommendation=(
                    "Tool registry missing an expected tool. Check the "
                    "tool's register_tool() call or planner output."
                ),
            )
        # Generic tool exception
        return _report(
            stage=STAGE_TOOL,
            reason="tool_runtime_error",
            summary=(
                f"{len(failed_steps)} step(s) failed inside the tool's "
                f"run() body."
            ),
            event_trace=_condense_events(events_list),
            recommendation=(
                "Tool runtime exception. Inspect step.error_type and "
                "step.error in task.result['steps']."
            ),
        )

    # 5) Plan exists but executor never ran any steps → executor failure.
    if plan and isinstance(plan, dict) and plan.get("steps"):
        if not _events_by_prefix(events_list, "step_"):
            return _report(
                stage=STAGE_EXECUTOR,
                reason="executor_never_ran_steps",
                summary=(
                    "A valid plan was attached but no step_* events fired. "
                    "The executor was not invoked."
                ),
                event_trace=_condense_events(events_list),
                recommendation=(
                    "Executor wiring is broken. Check BrainClient.run_task → "
                    "ExecutorAgent(self, max_steps).run(task) call site."
                ),
            )

    # 6) State="done" with no detectable issue. The CI test must have
    #    checked something specific the heuristics here cannot recover.
    if state == "done":
        return _report(
            stage=STAGE_UNKNOWN,
            reason="test_failure_with_done_state",
            summary=(
                "Brain reached state='done' and produced step records, but "
                "the CI test still failed. The diagnostic layer cannot "
                "infer which assertion broke from the runtime alone."
            ),
            event_trace=_condense_events(events_list),
            recommendation=(
                "Inspect the failing test's assertion. Compare expected vs "
                "actual telemetry events and step outputs in task.result."
            ),
        )

    # 7) Default fallback — be honest.
    return _report(
        stage=STAGE_UNKNOWN,
        reason="unclassified_failure",
        summary=(
            f"Could not classify the failure from the available signals. "
            f"state={state!r}, has_plan={plan is not None}, "
            f"event_count={len(events_list)}."
        ),
        event_trace=_condense_events(events_list),
        recommendation=(
            "Examine the raw event timeline + result.result for clues. "
            "If this happens repeatedly, extend analyze_ci_failure with "
            "the new failure signature."
        ),
    )


# ── Public: replayable trace ────────────────────────────────────────────────


def build_debug_trace(
    events: Optional[Iterable[dict]],
    input: Optional[str],
    result: Any,
) -> dict:
    """Build a JSON-friendly trace that lets a developer replay the run.

    Returns a dict with:
      * ``input``           — the user's request
      * ``final_state``     — the BrainTask's terminal state
      * ``task_id``         — the BrainTask's stable id
      * ``events``          — the verbatim flushed event stream
      * ``step_timeline``   — per-step entries with timing + outcome
      * ``planner_output``  — the validated plan dict, if available
      * ``executor_steps``  — the per-step records from task.result
    """
    events_list: list[dict] = list(events or [])
    state = _state_of(result)
    plan = _plan_of(result)
    result_dict = _result_of(result)

    return {
        "input": input if input is not None else _input_of(result),
        "final_state": state,
        "task_id": getattr(result, "id", None) if result is not None else None,
        "events": events_list,
        "step_timeline": _build_step_timeline(events_list),
        "planner_output": plan,
        "executor_steps": _step_records(result_dict),
    }


def _build_step_timeline(events: list[dict]) -> list[dict]:
    """Walk paired step_start / step_(success|error) events and return a
    timeline of step lifecycles. Robust to missing pairs."""
    timeline: list[dict] = []
    pending: Optional[dict] = None
    for e in events:
        if not isinstance(e, dict):
            continue
        et = e.get("event_type")
        meta = e.get("metadata") or {}
        if et == "step_start":
            if pending is not None:
                timeline.append({**pending, "outcome": "unterminated"})
            pending = {
                "index": meta.get("index"),
                "type": meta.get("type"),
                "tool": meta.get("tool"),
                "started_at": e.get("timestamp"),
            }
        elif et in ("step_success", "step_error") and pending is not None:
            timeline.append({
                **pending,
                "outcome": "success" if et == "step_success" else "error",
                "duration_ms": meta.get("duration_ms"),
                "error_type": meta.get("error_type"),
                "error": meta.get("error"),
                "ended_at": e.get("timestamp"),
            })
            pending = None
    if pending is not None:
        timeline.append({**pending, "outcome": "unterminated"})
    return timeline


# ── Public: CI run wrapper ──────────────────────────────────────────────────


async def ci_wrap_run_task(client: Any, input: str):
    """Run ``client.run_task(input)`` capturing exceptions.

    Returns ``(result, exception)``: exactly one is non-None. Use this
    in CI tests to feed both the success and the failure signals into
    :func:`analyze_ci_failure` without polluting the test body with
    try/except.

    Example::

        result, exc = await ci_wrap_run_task(client, "do thing")
        events = client.telemetry.flush()
        report = analyze_ci_failure(result, events, exc)
        if report["stage"] != "unknown":
            print_report(report)
        assert exc is None and result is not None
    """
    try:
        result = await client.run_task(input)
        return result, None
    except BaseException as e:  # noqa: BLE001 — diagnostic layer captures all
        return None, e


# ── Rendering / printing ────────────────────────────────────────────────────


def format_report(report: dict) -> str:
    """Render a report dict as a human-readable, CI-log-friendly string."""
    if not isinstance(report, dict):
        return f"<invalid report: {report!r}>"
    stage = report.get("stage", STAGE_UNKNOWN)
    reason = report.get("reason", "?")
    summary = report.get("summary", "")
    rec = report.get("recommendation", "")
    trace = report.get("event_trace") or []

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"  BRAIN CI DIAGNOSTIC — stage: {stage.upper()}  (reason: {reason})")
    lines.append("=" * 72)
    if summary:
        lines.append("")
        lines.append("Summary:")
        for s in summary.splitlines():
            lines.append(f"  {s}")
    if rec:
        lines.append("")
        lines.append("Recommendation:")
        for s in rec.splitlines():
            lines.append(f"  {s}")
    lines.append("")
    lines.append(f"Event trace ({len(trace)} events):")
    if trace:
        for i, ev in enumerate(trace):
            t = ev.get("type", "?")
            extras = []
            for k in ("tool", "iteration", "outcome", "duration_ms", "error"):
                v = ev.get(k)
                if v not in (None, "", []):
                    extras.append(f"{k}={v}")
            extras_str = "  " + " ".join(extras) if extras else ""
            lines.append(f"  [{i:>3}] {t}{extras_str}")
    else:
        lines.append("  (no events recorded)")
    lines.append("=" * 72)
    return "\n".join(lines)


def print_report(report: dict, file=None) -> None:
    """Print the formatted report to stderr (or a chosen stream)."""
    print(format_report(report), file=file or sys.stderr, flush=True)


__all__ = [
    "analyze_ci_failure",
    "build_debug_trace",
    "ci_wrap_run_task",
    "format_report",
    "print_report",
    "STAGE_PLANNER",
    "STAGE_EXECUTOR",
    "STAGE_TOOL",
    "STAGE_TELEMETRY",
    "STAGE_ROUTER",
    "STAGE_UNKNOWN",
]
