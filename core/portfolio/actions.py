"""The W-MOS action envelope — the single chokepoint every dispatched action passes.

Traffic-light classes:
  green       -> run immediately (reversible, no external side effects)
  auto_capped -> run ONLY if every precondition is truthy in ctx; else queue for approval
  amber       -> always queue for one-click approval; the engine never auto-fires it
  red         -> never dispatched by the engine, under any circumstance

`dispatch` is pure w.r.t. side effects: it calls the injected `adapter.run`,
`on_queue`, and `on_audit` — it never imports state/IO itself, which keeps the
safety logic trivially testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol


class ActionClass(str, Enum):
    GREEN = "green"
    AUTO_CAPPED = "auto_capped"
    AMBER = "amber"
    RED = "red"


@dataclass
class Action:
    verb: str
    agent: str
    action_class: ActionClass
    preconditions: list[str]
    business: str
    payload: dict


class AgentAdapter(Protocol):
    def run(self, action: Action) -> dict: ...


@dataclass
class DispatchResult:
    status: str                       # "executed" | "queued" | "refused"
    detail: str
    output: dict | None = None
    failed_preconditions: list[str] = field(default_factory=list)


def check_preconditions(action: Action, ctx: dict) -> tuple[bool, list[str]]:
    failed = [name for name in action.preconditions if not ctx.get(name)]
    return (len(failed) == 0, failed)


def _audit_record(action: Action, status: str, detail: str) -> dict:
    return {
        "business": action.business,
        "verb": action.verb,
        "agent": action.agent,
        "action_class": action.action_class.value,
        "status": status,
        "detail": detail,
    }


def dispatch(
    action: Action,
    adapter: AgentAdapter,
    ctx: dict,
    *,
    on_queue: Callable[[Action], None],
    on_audit: Callable[[dict], None],
) -> DispatchResult:
    # RED — refuse outright. The adapter is never touched.
    if action.action_class is ActionClass.RED:
        res = DispatchResult("refused", "RED actions are never dispatched by the engine")
        on_audit(_audit_record(action, res.status, res.detail))
        return res

    # AMBER — always queue; never auto-fire.
    if action.action_class is ActionClass.AMBER:
        on_queue(action)
        res = DispatchResult("queued", "AMBER action queued for one-click approval")
        on_audit(_audit_record(action, res.status, res.detail))
        return res

    # AUTO_CAPPED — fire only if every precondition is truthy; otherwise queue.
    if action.action_class is ActionClass.AUTO_CAPPED:
        ok, failed = check_preconditions(action, ctx)
        if not ok:
            on_queue(action)
            res = DispatchResult("queued", f"preconditions failed: {failed}",
                                 failed_preconditions=failed)
            on_audit(_audit_record(action, res.status, res.detail))
            return res
        # fall through to execution

    # GREEN (or AUTO_CAPPED with all preconditions met) — execute.
    # The execute path is the only one with a real external side effect, so an
    # adapter failure MUST still be audited (spec: everything is audited) — never
    # let an attempted action vanish without a record. dispatch never raises.
    try:
        output = adapter.run(action)
    except Exception as e:
        res = DispatchResult("failed", f"adapter raised: {e}")
        on_audit(_audit_record(action, res.status, res.detail))
        return res
    res = DispatchResult("executed", "executed", output=output)
    on_audit(_audit_record(action, res.status, res.detail))
    return res
