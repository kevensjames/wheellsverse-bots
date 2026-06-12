"""Executor — runs ONE step of a plan per call, records the run, and moves
the plan's state forward, following the optional branch directives.

Design: the state machine (which step is next, what success/failure does to
the plan) is separated from the LLM call via an injected ``runner``. A
runner is any callable ``(Step) -> RunOutcome``. This keeps every branch
transition deterministically testable with a fake runner, and lets the
real LLM-backed runner be a thin factory on top (see ``make_llm_runner``).

Branch grammar (one directive per step, stored as a string):
  on_done:  "goto:N"            jump FORWARD to step N (skip the steps between)
            null                advance to the next step
  on_fail:  "goto:N"            jump to step N (the "if A fails, do C" branch)
            "stop"              halt — plan → blocked (no revision suggested)
            "revise" | null     plan → blocked + operator should propose a revision

Execution is manual: the operator clicks "execute next step" once per step.
There is no auto-run loop — that's deliberate (see the design doc). A v1
``runner`` "executes" a chat step by asking the LLM to carry it out and
report the result; real-world side-effecting automation (browser/computer
control) is a separate, higher-risk feature and explicitly out of scope.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.planning import storage

logger = logging.getLogger(__name__)

# Cap the result text we persist on the step row so a chatty model can't
# bloat the db. Full output still lives in the step_run row.
_RESULT_PREVIEW_CHARS = 4000

_EXEC_SYSTEM = (
    "You are KAI executing ONE step of a larger plan. You are given the "
    "step's action. Carry it out as far as you can and report the concrete "
    "result or output. Be specific. If you genuinely cannot complete the "
    "step, say so plainly and explain what is blocking it."
)


@dataclass(slots=True)
class RunOutcome:
    """What a runner reports back for a single step execution."""
    success: bool
    output: str = ""
    cost_usd: float = 0.0
    error: str | None = None


@dataclass(slots=True)
class ExecResult:
    """Summary of one execute_next() call, for the API/dashboard."""
    plan_id: int
    ran: bool                       # did a step actually execute this call?
    plan_status: str                # plan status AFTER this call
    step_id: int | None = None
    step_seq: int | None = None
    step_action: str | None = None
    outcome: str | None = None      # "done" | "failed" | None
    cost_usd: float = 0.0
    next_seq: int | None = None      # seq of the next pending step, if any
    note: str = ""
    branch: str | None = None        # directive that fired, if any

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "ran": self.ran,
            "plan_status": self.plan_status,
            "step_id": self.step_id,
            "step_seq": self.step_seq,
            "step_action": self.step_action,
            "outcome": self.outcome,
            "cost_usd": self.cost_usd,
            "next_seq": self.next_seq,
            "note": self.note,
            "branch": self.branch,
        }


def parse_directive(d: str | None) -> tuple[str, int | None] | None:
    """Parse a branch directive string. Returns (kind, target) or None.

    kind ∈ {"goto", "stop", "revise"}; target is the step seq for goto, else None.
    Unknown / malformed directives return None (treated as "no directive").
    """
    if not d:
        return None
    s = d.strip().lower()
    if s == "stop":
        return ("stop", None)
    if s == "revise":
        return ("revise", None)
    if s.startswith("goto:"):
        try:
            return ("goto", int(s.split(":", 1)[1]))
        except (ValueError, IndexError):
            logger.warning("planning: malformed goto directive %r", d)
            return None
    return None


def execute_next(plan_id: int, *, runner: Callable[[storage.Step], RunOutcome]) -> ExecResult:
    """Run the next pending step of a plan and advance its state.

    Only plans in 'approved' or 'executing' status run. A plan with no
    pending steps is marked 'done'. On step success the plan follows the
    step's on_done directive (forward goto) or advances. On step failure it
    follows on_fail (goto to branch, or block).
    """
    plan = storage.get_plan(plan_id)
    if plan is None:
        raise ValueError(f"no plan with id {plan_id}")

    if plan.status not in ("approved", "executing"):
        return ExecResult(
            plan_id=plan_id, ran=False, plan_status=plan.status,
            note=f"plan is '{plan.status}'; only approved/executing plans run "
                 f"(approve it, or propose a revision if blocked)",
        )

    step = storage.next_pending_step(plan_id)
    if step is None:
        # Nothing left to do → the plan is complete.
        if plan.status != "done":
            storage.update_plan_status(plan_id, "done")
        return ExecResult(
            plan_id=plan_id, ran=False, plan_status="done",
            note="no pending steps — plan complete",
        )

    # Move the plan into 'executing' on the first run.
    if plan.status == "approved":
        storage.update_plan_status(plan_id, "executing")

    storage.set_step_status(step.id, "running")
    started_at = storage._now()
    outcome = _safe_run(runner, step)
    finished_at = storage._now()

    if outcome.success:
        return _on_success(plan_id, step, outcome, started_at, finished_at)
    return _on_failure(plan_id, step, outcome, started_at, finished_at)


# ─── success / failure handling ──────────────────────────────────────


def _on_success(
    plan_id: int, step: storage.Step, outcome: RunOutcome,
    started_at: str, finished_at: str,
) -> ExecResult:
    storage.set_step_status(step.id, "done", result=outcome.output[:_RESULT_PREVIEW_CHARS])
    storage.add_step_run(
        step.id, plan_id, step.seq, status="done", output=outcome.output,
        cost_usd=outcome.cost_usd, started_at=started_at, finished_at=finished_at,
    )

    branch: str | None = None
    directive = parse_directive(step.on_done)
    if directive and directive[0] == "goto" and directive[1] is not None:
        target = directive[1]
        if target > step.seq:
            skipped = _skip_pending_between(plan_id, step.seq, target)
            branch = f"goto:{target} (skipped {skipped} step(s))"
        else:
            # Backward jumps via on_done aren't supported in v1; on_fail
            # owns retry/loop semantics. Just advance normally.
            logger.info(
                "planning: ignoring backward on_done goto:%d on step %d",
                target, step.seq,
            )

    nxt = storage.next_pending_step(plan_id)
    if nxt is None:
        storage.update_plan_status(plan_id, "done")
        return ExecResult(
            plan_id=plan_id, ran=True, plan_status="done", step_id=step.id,
            step_seq=step.seq, step_action=step.action, outcome="done",
            cost_usd=outcome.cost_usd, next_seq=None, branch=branch,
            note="step done — plan complete",
        )
    return ExecResult(
        plan_id=plan_id, ran=True, plan_status="executing", step_id=step.id,
        step_seq=step.seq, step_action=step.action, outcome="done",
        cost_usd=outcome.cost_usd, next_seq=nxt.seq, branch=branch,
        note="step done",
    )


def _on_failure(
    plan_id: int, step: storage.Step, outcome: RunOutcome,
    started_at: str, finished_at: str,
) -> ExecResult:
    err = outcome.error or "step execution failed"
    storage.set_step_status(step.id, "failed", result=err[:_RESULT_PREVIEW_CHARS])
    storage.add_step_run(
        step.id, plan_id, step.seq, status="failed", output=outcome.output,
        cost_usd=outcome.cost_usd, error=err, started_at=started_at,
        finished_at=finished_at,
    )

    directive = parse_directive(step.on_fail)
    if directive and directive[0] == "goto" and directive[1] is not None:
        target = directive[1]
        if storage.get_step_by_seq(plan_id, target) is not None:
            # The "if A fails, do C" path. Forward goto skips the steps in
            # between (we don't want B if A failed); backward goto re-arms the
            # segment target..failed for a retry loop. Plan keeps executing.
            _apply_failure_goto(plan_id, step.seq, target)
            nxt = storage.next_pending_step(plan_id)
            return ExecResult(
                plan_id=plan_id, ran=True, plan_status="executing", step_id=step.id,
                step_seq=step.seq, step_action=step.action, outcome="failed",
                cost_usd=outcome.cost_usd, next_seq=nxt.seq if nxt else None,
                branch=f"goto:{target}", note=f"step failed — branching to step {target}",
            )
        logger.warning(
            "planning: on_fail goto:%d but no step %d exists; blocking", target, target,
        )

    # Default (null / revise / stop / dangling goto) → block the plan.
    storage.update_plan_status(plan_id, "blocked")
    kind = directive[0] if directive else "revise"
    note = (
        "step failed — plan blocked (stopped per directive)"
        if kind == "stop"
        else "step failed — plan blocked; propose a revision"
    )
    return ExecResult(
        plan_id=plan_id, ran=True, plan_status="blocked", step_id=step.id,
        step_seq=step.seq, step_action=step.action, outcome="failed",
        cost_usd=outcome.cost_usd, next_seq=None, branch=kind, note=note,
    )


# ─── runner factory (LLM-backed) ─────────────────────────────────────


def make_llm_runner(
    router,
    user_id,
    *,
    registry=None,
    tool_context=None,
    prefer_local: bool = False,
    max_tokens: int = 1024,
) -> Callable[[storage.Step], RunOutcome]:
    """Build the default runner that executes a step via the LLM.

    chat steps → router.complete(). tool steps (when a registry + context are
    provided) → router.chat() so the model can invoke the named tool through
    the normal tool loop. Any exception → RunOutcome(success=False).
    """
    def _run(step: storage.Step) -> RunOutcome:
        msgs = [{"role": "user", "content": _exec_prompt(step)}]
        try:
            if step.kind == "tool" and registry is not None and tool_context is not None:
                result = router.chat(
                    user_id=user_id, messages=msgs, tool_registry=registry,
                    tool_context=tool_context, system=_EXEC_SYSTEM,
                    max_tokens=max_tokens, prefer_local=prefer_local,
                )
            else:
                result = router.complete(
                    user_id=user_id, messages=msgs, system=_EXEC_SYSTEM,
                    max_tokens=max_tokens, prefer_local=prefer_local,
                )
            output = (getattr(result, "content", "") or "").strip()
            return RunOutcome(success=True, output=output, cost_usd=_result_cost(result))
        except Exception as e:
            logger.warning("planning: step %d run failed: %s", step.seq, e)
            return RunOutcome(success=False, error=str(e))

    return _run


# ─── internals ──────────────────────────────────────────────────────


def _safe_run(runner: Callable[[storage.Step], RunOutcome], step: storage.Step) -> RunOutcome:
    """Never let a misbehaving runner raise out of execute_next — a crash
    becomes a failed outcome so the plan blocks cleanly instead of 500ing."""
    try:
        out = runner(step)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("planning: runner raised for step %d: %s", step.seq, e)
        return RunOutcome(success=False, error=f"runner crashed: {e}")
    if not isinstance(out, RunOutcome):
        return RunOutcome(success=False, error="runner returned a non-RunOutcome")
    return out


def _apply_failure_goto(plan_id: int, failed_seq: int, target: int) -> None:
    """Re-route after a failed step's on_fail goto:N.

    Forward (target > failed): skip the pending steps between the failed
    step and the target, then arm the target. Backward (target <= failed):
    re-arm every step from target..failed (inclusive) as pending — a retry
    loop that re-runs the segment, including the step that just failed.
    """
    plan = storage.get_plan(plan_id)
    if plan is None:
        return
    if target > failed_seq:
        for s in plan.steps:
            if failed_seq < s.seq < target and s.status == "pending":
                storage.set_step_status(s.id, "skipped")
        target_step = next((s for s in plan.steps if s.seq == target), None)
        if target_step is not None:
            storage.set_step_status(target_step.id, "pending")
    else:
        for s in plan.steps:
            if target <= s.seq <= failed_seq:
                storage.set_step_status(s.id, "pending")


def _skip_pending_between(plan_id: int, from_seq: int, target_seq: int) -> int:
    """Mark pending steps with from_seq < seq < target_seq as skipped.
    Returns how many were skipped."""
    plan = storage.get_plan(plan_id)
    if plan is None:
        return 0
    n = 0
    for s in plan.steps:
        if from_seq < s.seq < target_seq and s.status == "pending":
            storage.set_step_status(s.id, "skipped")
            n += 1
    return n


def _exec_prompt(step: storage.Step) -> str:
    extra = ""
    if step.kind == "tool" and step.tool_name:
        extra = f"\n(Use the '{step.tool_name}' tool if helpful.)"
    return f"STEP TO EXECUTE:\n{step.action}{extra}\n\nCarry it out and report the result."


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
