"""Draft — generate content IN THE OPERATOR'S VOICE using the twin profile.

This is the 'draft as me' capability the operator chose. It produces a DRAFT
only — KAI never sends/posts it. The active twin profile is injected as voice/
context. Every draft is logged for review. Fail-soft.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.twin import composer, storage

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1500

_DRAFT_SYSTEM = (
    "You are drafting text AS the operator (your principal) — in their voice, "
    "tone, and values, per the profile below. Produce ONLY the draft itself: no "
    "preamble, no 'here is', no sign-off unless the task asks for one. This is a "
    "DRAFT for the operator to review and send themselves — you do NOT send or "
    "post anything.\n"
    "\n"
    "OPERATOR PROFILE:\n{profile}"
)


def draft_as_operator(*, router, user_id, task: str,
                      prefer_local: bool = False,
                      max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    """Draft content in the operator's voice for `task`. Logs + returns the
    draft. Returns {"draft": str, "cost_usd": float, "note": str}."""
    task = (task or "").strip()
    if not task:
        raise ValueError("task cannot be empty")
    active = storage.list_entries(status="active")
    profile = composer.compose_profile(active)
    if not profile:
        profile = "(no profile entries yet — write in a clear, direct, first-person voice)"
    system = _DRAFT_SYSTEM.replace("{profile}", profile)
    try:
        result = router.complete(
            user_id=user_id, messages=[{"role": "user", "content": task}],
            system=system, max_tokens=max_tokens, temperature=0.6, prefer_local=prefer_local,
        )
    except Exception as e:
        logger.warning("twin.draft: router.complete failed: %s", e)
        return {"draft": "", "cost_usd": 0.0, "note": f"draft unavailable: {e}"}
    content = (getattr(result, "content", "") or "").strip()
    cost = _result_cost(result)
    storage.add_draft(task, content, cost_usd=cost)
    return {"draft": content, "cost_usd": cost,
            "note": f"drafted from {len(active)} active profile entry(ies)"}


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
