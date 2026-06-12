"""Reviser — given (original prompt, draft, verdict), produces a revised draft.

Uses the SAME adapter the original chat used (not the cheap critic
adapter), because revision is generation — same quality bar as the
first draft. The critique + suggestions are injected as a system-level
note so the reviser knows what to fix without re-reading the whole
conversation.
"""
from __future__ import annotations

import logging

from app.services.self_correction.critic import Verdict

logger = logging.getLogger(__name__)


_REVISER_PREAMBLE = (
    "Your previous draft response was reviewed by a critic. Use the "
    "critique below to produce a REVISED reply that addresses the "
    "issues. Do not apologize, do not mention the revision — just "
    "produce the corrected reply."
)


def revise(
    *,
    user_message: str,
    draft_response: str,
    verdict: Verdict,
    router,            # type: app.services.router.router.Router
    original_adapter,  # the adapter that produced the draft
    max_tokens: int = 2048,
    temperature: float = 0.5,
) -> tuple[str, float]:
    """One revision pass. Returns (revised_text, cost).

    On failure: returns the original draft + 0 cost (fail-open, same
    posture as the critic — never block a user response on a self-
    correction infra problem).
    """
    if original_adapter is None:
        adapters = getattr(router, "adapters", {}) or {}
        original_adapter = next(iter(adapters.values()), None)
    if original_adapter is None:
        logger.warning("self_correction: reviser has no adapter")
        return draft_response, 0.0

    msgs = [
        {
            "role": "user",
            "content": (
                f"USER MESSAGE:\n{user_message.strip()}\n\n"
                f"YOUR DRAFT REPLY:\n{draft_response.strip()}\n\n"
                f"CRITIC SAID:\n{verdict.critique}\n\n"
                f"SUGGESTIONS:\n" + "\n".join(f"  - {s}" for s in verdict.suggestions)
                + "\n\nNow produce the revised reply."
            ),
        }
    ]
    # Use the critic's compat-aware caller (Ollama adapter doesn't take
    # `tools` kwarg). On any failure, fall back to the original draft.
    from app.services.self_correction.critic import _call_adapter_complete
    result = _call_adapter_complete(
        original_adapter,
        msgs,
        max_tokens=max_tokens,
        temperature=temperature,
        system=_REVISER_PREAMBLE,
    )
    if result is None:
        logger.warning("self_correction: reviser unavailable — keeping draft")
        return draft_response, 0.0

    cost = 0.0
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            cost = float(v)
            break

    revised = (result.content or "").strip()
    # Defensive: empty revision = fall back to draft. We'd rather show
    # the imperfect-but-real reply than nothing.
    if not revised:
        return draft_response, cost
    return revised, cost
