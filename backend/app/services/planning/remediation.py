"""Remediation — turn KAI's own detected issues into PROPOSED (draft) plans.

The proactive loop's *action* half. The digest + audit TELL the operator what's
wrong; this PROPOSES what to do about it. It scans cross-subsystem state
(audit issues, recurring tool/LLM failures, underperforming learning lessons,
blocked plans), ranks the issues, and uses the planner to draft a plan per
top issue.

Safe by construction: every plan lands 'draft' (inert). A draft executes nothing
— the operator must separately APPROVE it (draft→approved, which IS a destructive
audited action) before any step runs. So proposing is non-destructive, and the
dangerous step stays gated. Gathering each signal is fail-soft (a subsystem read
error degrades to "no issues from that source", never raises).
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from app.services.planning.planner import generate_plan

logger = logging.getLogger(__name__)

DEFAULT_MAX_PLANS = 2
_MAX_ISSUES = 8


def propose_remediations(
    *, router, user_id, max_plans: int = DEFAULT_MAX_PLANS, prefer_local: bool = False,
) -> dict[str, Any]:
    """Detect issues, draft a plan for the top `max_plans`. Returns
    {"proposed_plans": [...], "issues_found": int, "cost_usd": float, "note": str}.
    Fail-soft throughout."""
    issues = _gather_issues()
    if not issues:
        return {"proposed_plans": [], "issues_found": 0, "cost_usd": 0.0,
                "note": "no actionable issues detected — KAI is healthy, nothing to remediate"}

    total_cost = 0.0
    plans: list[dict[str, Any]] = []
    for issue in issues[:max_plans]:
        goal = _goal_for(issue)
        try:
            plan, cost = generate_plan(
                goal, router=router, user_id=user_id,
                meta={"remediation": True, "issue_kind": issue["kind"],
                      "issue": issue["detail"][:300]},
            )
        except Exception as e:
            logger.warning("remediation: generate_plan failed for %s: %s", issue["kind"], e)
            continue
        total_cost += cost
        plans.append({
            "plan_id": plan.id, "title": plan.title, "goal": plan.goal,
            "status": plan.status, "issue_kind": issue["kind"], "issue": issue["detail"],
        })

    note = (f"proposed {len(plans)} draft plan(s) from {len(issues)} detected issue(s) "
            f"— review + approve on the Plans tab before anything runs")
    return {"proposed_plans": plans, "issues_found": len(issues),
            "cost_usd": total_cost, "note": note}


# ─── issue gathering (each source fail-soft) ─────────────────────────


def _gather_issues(max_issues: int = _MAX_ISSUES) -> list[dict[str, Any]]:
    """Cross-subsystem issues, weighted (higher = more worth a plan), newest/
    strongest first. Defensive: any source that throws contributes nothing."""
    issues: list[dict[str, Any]] = []

    # Underperforming learning lessons (the learning loop flagged these).
    try:
        from app.services.learning import evaluate_lessons
        ev = evaluate_lessons()
        by_id = {r["id"]: r for r in ev.get("evaluated", [])}
        for lid in ev.get("recommend_retire", []):
            row = by_id.get(lid)
            if row:
                issues.append({"kind": "lesson", "weight": 3,
                               "detail": f"lesson #{lid} underperforming ({row['verdict']}): {row['text']}"})
    except Exception as e:
        logger.warning("remediation: gather lessons failed: %s", e)

    # Recurring tool/LLM failures (signature = category+tool/adapter).
    try:
        from app.services import failure_memory
        recent = failure_memory.list_recent(limit=50)
        sig = Counter()
        detail_by_sig: dict[tuple, str] = {}
        for f in recent:
            key = (f.category, f.tool_name or f.adapter or "")
            sig[key] += 1
            detail_by_sig.setdefault(key, f.detail)
        for (cat, tool), n in sig.most_common(5):
            label = f"{cat}{' [' + tool + ']' if tool else ''}"
            issues.append({"kind": "failure", "weight": 3 if n >= 2 else 2, "count": n,
                           "detail": f"{label} ×{n}: {detail_by_sig[(cat, tool)]}"})
    except Exception as e:
        logger.warning("remediation: gather failures failed: %s", e)

    # System audit issues.
    try:
        from app.services.audit import run_audit
        for msg in run_audit().get("issues", []):
            issues.append({"kind": "audit", "weight": 2, "detail": str(msg)})
    except Exception as e:
        logger.warning("remediation: gather audit failed: %s", e)

    # Blocked plans (stalled work needing a path forward).
    try:
        from app.services import planning
        for p in planning.list_plans(status="blocked", limit=10):
            issues.append({"kind": "blocked_plan", "weight": 2,
                           "detail": f"plan #{p.id} blocked: {p.title}"})
    except Exception as e:
        logger.warning("remediation: gather blocked plans failed: %s", e)

    issues.sort(key=lambda x: x.get("weight", 1), reverse=True)
    return issues[:max_issues]


def _goal_for(issue: dict[str, Any]) -> str:
    kind, detail = issue["kind"], issue["detail"]
    if kind == "failure":
        return f"Diagnose and prevent this recurring failure, then verify the fix: {detail}"
    if kind == "audit":
        return f"Resolve this system audit issue: {detail}"
    if kind == "lesson":
        return f"Improve or replace this underperforming learning lesson: {detail}"
    if kind == "blocked_plan":
        return f"Diagnose why this plan is blocked and propose a path to unblock it: {detail}"
    return f"Address this issue: {detail}"
