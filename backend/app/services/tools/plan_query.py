"""Plan query tool — lets KAI (via the tool loop) inspect its long-term
plans from inside a chat turn. READ-ONLY: it never creates, edits, or
executes a plan (those go through the audited admin endpoints). This is the
"what's plan X up to / what's blocking plan Y" surface.

Three actions, one tool with an `action` parameter (same shape as kg_query):
  list   — list plans (optional status filter)
  get    — full plan: steps + recent run history
  status — quick state: next pending step, or what the plan is blocked on
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.planning import storage
from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)


class PlanQueryTool:
    name = "plan_query"
    description = (
        "Query KAI's long-term plans (multi-step goals KAI is working "
        "through). READ-ONLY — to create/approve/execute a plan, the "
        "operator uses the Plans dashboard. Pick one action:\n"
        "  list   — list plans, newest first (optional status filter: "
        "draft/approved/executing/blocked/done/abandoned).\n"
        "  get    — full detail of one plan: its steps and recent run "
        "history (needs plan_id).\n"
        "  status — quick state of one plan: the next step to run, or what "
        "it's blocked on (needs plan_id)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "status"],
                "description": "Which query to run.",
            },
            "plan_id": {
                "type": "integer",
                "description": "get/status only — which plan to inspect.",
            },
            "status": {
                "type": "string",
                "description": (
                    "list only — optional status filter "
                    "(draft/approved/executing/blocked/done/abandoned)."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "list only — max plans to return. Default 25.",
            },
        },
        "required": ["action"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        if not action:
            raise ToolError("action is required")

        if action == "list":
            limit = int(kwargs.get("limit") or 25)
            plans = storage.list_plans(status=kwargs.get("status"), limit=limit)
            return {
                "action": "list",
                "count": len(plans),
                "plans": [
                    {
                        "id": p.id,
                        "title": p.title,
                        "status": p.status,
                        "goal": p.goal,
                        "updated_at": p.updated_at,
                    }
                    for p in plans
                ],
            }

        plan_id = kwargs.get("plan_id")
        if plan_id is None:
            raise ToolError(f"plan_id is required for action={action!r}")
        plan = storage.get_plan(int(plan_id))
        if plan is None:
            raise ToolError(f"no plan with id {plan_id}")

        if action == "get":
            runs = storage.list_step_runs(plan.id, limit=20)
            return {
                "action": "get",
                "plan": plan.as_dict(),
                "recent_runs": [r.as_dict() for r in runs],
            }

        if action == "status":
            nxt = storage.next_pending_step(plan.id)
            blocked_on = None
            if plan.status == "blocked":
                failed = next(
                    (s for s in reversed(plan.steps) if s.status == "failed"), None
                )
                if failed is not None:
                    blocked_on = {
                        "seq": failed.seq,
                        "action": failed.action,
                        "detail": failed.result,
                    }
            return {
                "action": "status",
                "plan_id": plan.id,
                "title": plan.title,
                "status": plan.status,
                "next_step": (
                    {"seq": nxt.seq, "action": nxt.action} if nxt else None
                ),
                "blocked_on": blocked_on,
            }

        raise ToolError(f"unknown action {action!r}; use list|get|status")
