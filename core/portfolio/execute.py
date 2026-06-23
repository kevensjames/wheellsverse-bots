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

    # Reconstruct defensively — a corrupt action_class must refuse, not crash.
    try:
        action = Action(
            verb=appr["verb"],
            agent=appr.get("agent", ""),
            action_class=ActionClass(appr.get("action_class", "amber")),
            preconditions=list(appr.get("preconditions", [])),
            business=appr["business"],
            payload=appr.get("payload", {}),
        )
    except (KeyError, ValueError):
        return {"status": "refused", "detail": "malformed approval record"}

    if action.verb not in adapters.ADAPTERS:
        return {"status": "refused", "detail": f"no adapter registered for verb {action.verb!r}"}

    # Atomically CLAIM the item: only an 'approved' row transitions to 'executing'.
    # Blocks concurrent double-fire AND prevents a crash mid-run from re-arming it.
    if not state.compare_and_set_approval(approval_id, "approved", "executing"):
        return {"status": "refused",
                "detail": f"approval status is {appr.get('status')!r}, not 'approved'"}

    try:
        output = adapters.adapter_for(action).run(action)
    except Exception as e:
        state.resolve_approval(approval_id, "failed")
        state.audit({"business": action.business, "verb": action.verb,
                     "status": "execute_failed", "approval_id": approval_id, "error": str(e)})
        return {"status": "failed", "verb": action.verb, "detail": str(e)}

    state.audit({"business": action.business, "verb": action.verb,
                 "status": "executed_by_approval", "approval_id": approval_id, "output": output})
    state.mark_completed(action.business, action.verb)
    state.resolve_approval(approval_id, "executed")
    return {"status": "executed", "verb": action.verb, "output": output}
