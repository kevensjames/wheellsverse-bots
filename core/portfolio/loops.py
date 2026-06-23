"""W-MOS supervisor-loop tick engine.

A business's loop.json lists ordered steps. One tick selects the first step not
yet completed or pending, builds an Action, and dispatches it through the envelope.
Loop order IS priority (deterministic). Preconditions are enforced at dispatch,
not at selection: an auto_capped step with unmet preconditions is QUEUED (moved to
pending), never silently skipped, so progress is visible and never lost.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.portfolio import paths, state
from core.portfolio.actions import Action, ActionClass, DispatchResult, dispatch


@dataclass
class LoopStep:
    verb: str
    agent: str
    action_class: ActionClass
    preconditions: list[str]


def load_loop(slug: str) -> list[LoopStep]:
    cfg = paths.load_json(paths.business_dir(slug) / "loop.json", {})
    out: list[LoopStep] = []
    for raw in (cfg or {}).get("steps", []):
        out.append(LoopStep(
            verb=raw["verb"],
            agent=raw.get("agent", ""),
            action_class=ActionClass(raw.get("class", "green")),
            preconditions=list(raw.get("preconditions", [])),
        ))
    return out


def select_next_step(steps: list[LoopStep], state_dict: dict):
    done = set(state_dict.get("completed_verbs", []))
    pending = set(state_dict.get("pending_verbs", []))
    for step in steps:
        if step.verb not in done and step.verb not in pending:
            return step
    return None


def tick(slug: str, adapter_for, ctx_for) -> DispatchResult | None:
    steps = load_loop(slug)
    st = state.load_state(slug)
    step = select_next_step(steps, st)
    if step is None:
        return None

    action = Action(
        verb=step.verb,
        agent=step.agent,
        action_class=step.action_class,
        preconditions=step.preconditions,
        business=slug,
        payload={},
    )
    result = dispatch(
        action,
        adapter_for(step),
        ctx_for(step),
        on_queue=state.queue_approval,
        on_audit=state.audit,
    )

    if result.status == "executed":
        state.mark_completed(slug, step.verb)
    else:
        # queued (AMBER / unmet auto_capped) OR refused (RED): park in pending so
        # the loop advances to the next step instead of re-selecting this one.
        state.mark_pending(slug, step.verb)
    return result
