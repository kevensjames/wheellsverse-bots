"""Integration scout — turn a capability gap into PROPOSED (draft) integration
plans, backed by real GitHub candidates.

The *action* half of KAI's self-improvement loop. `github_scout` DISCOVERS repos
that could extend KAI; this picks the safely-adoptable ones and drafts a plan to
integrate the *capability* into KAI's architecture (as a new adapter / tool /
preset / service), using the repo as a REFERENCE DESIGN — never by cloning or
running its code.

Safe by construction (mirrors remediation.py):
  - Discovery is read-only (github_scout makes a GitHub search call, nothing else).
  - avoid-tier candidates (no license / archived) are dropped, never proposed.
  - Every plan lands 'draft' (inert). A draft executes nothing — the operator
    must separately APPROVE it (planning.approve, destructive=True) before any
    step runs, and even an approved plan's steps are KAI's normal audited
    chat/tool actions, NOT "run arbitrary downloaded code".
So proposing is non-destructive and autonomous self-integration stays impossible.
Fail-soft throughout: a scout/network error degrades to "no candidates", never
raises.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.planning.planner import generate_plan

logger = logging.getLogger(__name__)

DEFAULT_MAX_PLANS = 1
_MAX_CANDIDATES_SCAN = 8


def propose_integrations(
    capability: str,
    *,
    router,
    user_id,
    session,
    max_plans: int = DEFAULT_MAX_PLANS,
    min_stars: int = 100,
    language: str | None = None,
    prefer_local: bool = False,
) -> dict[str, Any]:
    """Scout GitHub for `capability`, draft an integration plan for the top
    safely-adoptable candidate(s). Returns {"capability", "candidates_found",
    "proposed_plans", "candidates", "cost_usd", "note"}."""
    capability = (capability or "").strip()
    if not capability:
        raise ValueError("capability is required")

    # 1. Discover candidates (read-only; fail-soft → []).
    candidates = _scout(
        capability, user_id=user_id, session=session,
        min_stars=min_stars, language=language,
    )
    # 2. Drop avoid-tier (legal blocker / archived). github_scout already
    #    safety-ranks the survivors, so we keep its order.
    adoptable = [c for c in candidates if c.get("recommendation") != "avoid"]
    if not adoptable:
        note = (
            f"found {len(candidates)} repo(s) for '{capability}' but none are "
            f"safely adoptable (all flagged 'avoid' — no usable license or "
            f"archived). No plan drafted."
            if candidates else
            f"no GitHub repos matched '{capability}' — try broader terms or a "
            f"lower min_stars."
        )
        return {
            "capability": capability, "candidates_found": len(candidates),
            "proposed_plans": [], "candidates": candidates,
            "cost_usd": 0.0, "note": note,
        }

    # 3. Draft an inert plan per top candidate.
    total_cost = 0.0
    plans: list[dict[str, Any]] = []
    for cand in adoptable[:max_plans]:
        goal = _goal_for(capability, cand)
        try:
            plan, cost = generate_plan(
                goal, router=router, user_id=user_id,
                title=f"Integrate: {capability} (ref: {cand['repo']})",
                prefer_local=prefer_local,
                meta={
                    "integration": True,
                    "capability": capability,
                    "candidate_repo": cand.get("repo"),
                    "candidate_url": cand.get("url"),
                    "license": cand.get("license"),
                    "stars": cand.get("stars"),
                    "recommendation": cand.get("recommendation"),
                },
            )
        except Exception as e:
            logger.warning(
                "integration: generate_plan failed for %s: %s",
                cand.get("repo"), e,
            )
            continue
        total_cost += cost
        plans.append({
            "plan_id": plan.id, "title": plan.title, "goal": plan.goal,
            "status": plan.status, "candidate_repo": cand.get("repo"),
            "candidate_url": cand.get("url"),
            "recommendation": cand.get("recommendation"),
        })

    note = (
        f"proposed {len(plans)} draft integration plan(s) for '{capability}' "
        f"from {len(candidates)} candidate(s) — review + approve on the Plans "
        f"tab. Nothing is installed or run; approval only authorizes KAI's "
        f"normal audited steps (no external code is executed)."
    )
    return {
        "capability": capability, "candidates_found": len(candidates),
        "proposed_plans": plans, "candidates": candidates,
        "cost_usd": total_cost, "note": note,
    }


def _scout(
    capability: str, *, user_id, session, min_stars: int, language: str | None,
) -> list[dict[str, Any]]:
    """Run github_scout fail-soft → list of candidate dicts (possibly empty)."""
    try:
        from app.services.tools.base import ToolContext
        from app.services.tools.github_scout import GithubScoutTool
        ctx = ToolContext(user_id=user_id, session=session)
        kwargs: dict[str, Any] = {
            "query": capability, "min_stars": min_stars,
            "max_results": _MAX_CANDIDATES_SCAN,
        }
        if language:
            kwargs["language"] = language
        out = GithubScoutTool().execute(ctx, **kwargs)
        return out.get("results", []) or []
    except Exception as e:
        logger.warning("integration: github_scout failed for '%s': %s", capability, e)
        return []


def _goal_for(capability: str, cand: dict[str, Any]) -> str:
    return (
        f"Integrate the capability '{capability}' into KAI, using "
        f"{cand.get('repo')} ({cand.get('url')}, {cand.get('stars')}★, "
        f"{cand.get('license')}) as a REFERENCE DESIGN — NOT by cloning or "
        f"running its code. Study its approach, then design how this capability "
        f"slots into KAI's existing architecture (LLM router/adapters, tools "
        f"registry, presets, RAG/pgvector, planning, learning, twin, governance) "
        f"as a new adapter, tool, preset, or service. Produce concrete steps: "
        f"which KAI files to read, what to build, how to test it, and what "
        f"license/attribution to honor. Do NOT download or execute external "
        f"code as part of this plan."
    )
