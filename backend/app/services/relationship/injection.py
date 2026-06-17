"""Injection — the KAI↔operator bond as continuity in the system prompt.

relationship_preamble() gives KAI a sense of shared history ("you've worked
together N days across M conversations; recent wins: …") so it picks up where it
left off and references the relationship naturally. Gated by
KAI_SCOPE_RELATIONSHIP, fail-open.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MILESTONES_IN_PROMPT = 5


def _trust_label(score: int) -> str:
    if score >= 75:
        return "deep, well-earned trust"
    if score >= 50:
        return "solid trust"
    return "still building trust"


def relationship_preamble() -> str:
    try:
        from app.services.governance import is_scope_enabled
        if not is_scope_enabled("relationship"):
            return ""
        from app.services.relationship import storage
        state = storage.get_state()
        milestones = storage.list_milestones(limit=_MILESTONES_IN_PROMPT)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("relationship.injection: skipped (%s)", e)
        return ""

    if state["interaction_count"] <= 0 and not milestones:
        return ""  # nothing earned yet — stay quiet rather than fake it

    lines = ["YOUR RELATIONSHIP WITH THE OPERATOR (reference your shared history "
             "naturally; don't recite these stats):"]
    lines.append(
        f"- You've worked together ~{state['days_known']} day(s) across "
        f"{state['interaction_count']} conversations — {_trust_label(state['trust_score'])}."
    )
    if milestones:
        lines.append("- Recent shared milestones:")
        for m in milestones:
            lines.append(f"  • ({m.kind}) {m.text}")
    return "\n".join(lines)
