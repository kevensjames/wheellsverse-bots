"""Operator-approved execution gate (envelope B). Runs an adapter ONLY for an
approval whose status is exactly 'approved' — the operator's approval IS the
gate. This is a separate path from actions.dispatch (the autonomous chokepoint,
which still never auto-fires AMBER/auto_capped). Adapters are inert in Plan 4, so
this draws the rail without firing any real external action.
"""
from __future__ import annotations

from core.portfolio import adapters, state
from core.portfolio.actions import Action, ActionClass


def execute_approval(approval_id: str) -> dict:
    appr = next((a for a in state.list_approvals() if a.get("id") == approval_id), None)
    if appr is None:
        return {"status": "not_found"}
    if appr.get("status") != "approved":
        return {"status": "refused",
                "detail": f"approval status is {appr.get('status')!r}, not 'approved'"}

    action = Action(
        verb=appr["verb"],
        agent=appr.get("agent", ""),
        action_class=ActionClass(appr.get("action_class", "amber")),
        preconditions=list(appr.get("preconditions", [])),
        business=appr["business"],
        payload=appr.get("payload", {}),
    )
    # adapters.adapter_for(step) only needs `.verb`; the Action provides it.
    output = adapters.adapter_for(action).run(action)
    state.audit({
        "business": action.business,
        "verb": action.verb,
        "status": "executed_by_approval",
        "approval_id": approval_id,
    })
    state.mark_completed(action.business, action.verb)
    state.resolve_approval(approval_id, "executed")  # idempotent: blocks double-fire
    return {"status": "executed", "verb": action.verb, "output": output}
