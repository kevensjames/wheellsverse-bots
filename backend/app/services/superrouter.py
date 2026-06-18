"""Super-router — decompose a complex ask into a multi-step plan KAI proposes.

The "smarter" layer (roadmap P3): for a genuinely multi-step request, instead of
a single-shot answer KAI breaks it into a plan (reusing services/planning) and
PROPOSES it (a draft the operator approves → the existing executor runs it). This
is propose-then-approve, consistent with KAI's governance everywhere — the
super-router never auto-executes.

Two pieces:
  should_plan(message) — a FREE heuristic (no LLM): is this ask multi-step enough
    to warrant decomposition? Conservative on purpose (don't over-plan a question).
  propose_plan(...) — generate_plan via the router → a draft plan + step summary.

Activation: the audited admin endpoint (/admin/superrouter/propose) works now.
Auto-triggering inside chat is a later flip (KAI_SUPERROUTER_ENABLED), deferred
until a funded brain lets it be validated end-to-end.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Phrasing that signals a sequenced / multi-part task.
_MULTISTEP = (
    "and then", "after that", "then ", "once that", "followed by", "step 1",
    "first,", "next,", "finally", "afterwards", "subsequently",
)
# Verbs that imply a project (vs. a question).
_PROJECT = (
    "build", "create", "set up", "set-up", "launch", "migrate", "research",
    "design", "implement", "integrate", "automate", "organize", "refactor",
    "deploy", "plan ", "roll out",
)


def enabled() -> bool:
    """Auto-trigger-in-chat flag — OFF by default (deferred to post-P0)."""
    return (os.environ.get("KAI_SUPERROUTER_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on")


def should_plan(message: str) -> tuple[bool, str]:
    """Return (decompose?, reason). Conservative: needs >=2 signals so simple
    questions never get over-planned."""
    m = (message or "").lower().strip()
    if len(m) < 40:
        return False, "too short"
    signals = 0
    if any(k in m for k in _MULTISTEP):
        signals += 2
    # Distinct project verbs: 2+ => multiple sub-projects (strong), 1 (with a
    # conjunction/list) => mild.
    project_hits = sum(1 for k in _PROJECT if k in m)
    if project_hits >= 2:
        signals += 2
    elif project_hits == 1 and (" and " in m or "," in m):
        signals += 1
    if m.count("?") >= 2:
        signals += 1
    if any(f"{n}." in m for n in (1, 2, 3)):  # enumerated list
        signals += 2
    if len(m.split()) > 60:
        signals += 1
    return signals >= 2, f"signals={signals}"


def propose_plan(message: str, *, router, user_id, prefer_local: bool = False,
                 max_steps: int = 8) -> dict[str, Any] | None:
    """Decompose `message` into a DRAFT plan (operator approves to run). Returns
    the proposal, or None on failure (caller falls back to a normal answer)."""
    try:
        from app.services.planning import planner
        plan, cost = planner.generate_plan(
            message, router=router, user_id=user_id, prefer_local=prefer_local,
            max_steps=max_steps, meta={"source": "superrouter"},
        )
    except Exception as e:  # fail-open — never break the caller
        logger.warning("superrouter.propose_plan failed: %s", e)
        return None
    steps = getattr(plan, "steps", []) or []
    return {
        "plan_id": plan.id,
        "title": plan.title,
        "status": plan.status,
        "steps": [s.action for s in steps],
        "step_count": len(steps),
        "proposal_cost_usd": round(cost, 6),
        "note": (
            "Decomposed into a draft plan — approve it in the Plans tab "
            "(or POST /admin/planning/{id}/approve) to run."
        ),
    }
