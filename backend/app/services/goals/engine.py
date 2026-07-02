"""Goal engine — assess + advance active goals. NON-DESTRUCTIVE + human-gated.

`advance_active_goals` is the persistent-goal-loop heartbeat: for each active
goal it asks the model to assess progress and name the single next step, then
records that step as a PROPOSAL on the goal. It NEVER executes anything — real
actions (especially money/irreversible) go through the existing planning +
@audited governance approval path. This is deliberate: long-horizon autonomy is
kept inside the safety envelope (reliability decays over long horizons, so a
human ratifies each real step).
"""
from __future__ import annotations

import json
import logging

from app.services.goals import store

logger = logging.getLogger(__name__)

_ASSESS_SYSTEM = """You assess progress on a long-term GOAL given recent context.
Return ONLY JSON:
{"is_done": bool, "progress": "one-line status", "next_action": "the single next
concrete step, or empty if done/blocked", "blocked": bool, "blocked_reason":
"why, if blocked"}.
Be honest and conservative: set is_done=true ONLY if the goal's 'done when'
criteria are clearly met. Propose ONE next step, not a plan."""


def _parse(text: str) -> dict:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("\n") + 1:] if "\n" in s else s
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        obj = json.loads(s[start:end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def assess_goal(goal: store.Goal, context: str, *, router, prefer_local: bool = True) -> dict:
    """Ask the model to assess a goal. Fail-soft → {}."""
    prompt = (
        f"GOAL: {goal.title}\n"
        f"DONE WHEN: {goal.done_when or '(not specified)'}\n"
        f"CURRENT STATUS NOTE: {goal.progress or '(none)'}\n"
        f"RECENT CONTEXT:\n{(context or '(none)')[:6000]}"
    )
    try:
        result = router.complete(
            user_id=None,
            messages=[{"role": "user", "content": prompt}],
            system=_ASSESS_SYSTEM,
            max_tokens=300,
            prefer_local=prefer_local,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("goal assess: LLM failed for %s: %s", goal.id, e)
        return {}
    return _parse(getattr(result, "content", "") or "")


def advance_active_goals(*, router, context: str = "", prefer_local: bool = True) -> list[dict]:
    """Assess every active goal and update it NON-DESTRUCTIVELY:
      - is_done  → status='done'
      - blocked  → status='blocked' + reason
      - else     → record the PROPOSED next_action (NOT executed)
    Returns a per-goal summary. Any real action on `next_action` requires the
    operator to approve it through planning/governance — this loop never acts.
    """
    out: list[dict] = []
    for g in store.list_goals(status="active"):
        a = assess_goal(g, context, router=router, prefer_local=prefer_local)
        if not a:
            out.append({"goal_id": g.id, "assessed": False})
            continue
        fields: dict = {"progress": str(a.get("progress", ""))[:500]}
        if a.get("is_done") is True:
            fields["status"] = "done"
            fields["next_action"] = ""
        elif a.get("blocked") is True:
            fields["status"] = "blocked"
            fields["blocked_reason"] = str(a.get("blocked_reason", ""))[:500]
        else:
            # Proposal only — the operator approves before anything runs.
            fields["next_action"] = str(a.get("next_action", ""))[:500]
        store.update_goal(g.id, **fields)
        out.append({
            "goal_id": g.id,
            "status": fields.get("status", g.status),
            "proposed_next": fields.get("next_action", ""),
            "assessed": True,
        })
    return out
