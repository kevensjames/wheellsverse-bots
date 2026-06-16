"""Self-correction — KAI judges its own work and iterates before reply.

The loop:
  1. Brain produces a draft response to the user message
  2. Critic reads (user prompt, draft) → verdict {ok, severity, critique, suggestions}
  3. If verdict.ok and severity ∈ {none, minor}: reply with draft (cheap path)
  4. Else: Reviser produces revised draft using the critique
  5. (Optional) goto 2 until max_iterations or ok-enough

What this enables:
  - Catches obviously broken outputs before the operator sees them
    (e.g. KAI promised to call a tool but didn't, or hallucinated a fact)
  - Routes critic calls through the CHEAP adapter (Cloudflare) so the
    cost of one self-correction pass is ~$0.0001, not $0.01

What this is NOT (deferred):
  - Multi-judge majority vote (one critic for MVP)
  - Tool-call replay (critic only judges TEXT for now)
  - Constitutional rewrites (no "refuse if X" rules in the critic prompt;
    the operator's existing system prompt handles values)

Public API:
    from app.services.self_correction import (
        critique, revise, run_correction_loop, Verdict,
    )

Usage from admin_chat:
    if req.self_correct:
        result = run_correction_loop(
            brain=brain,
            user_id=...,
            user_message=req.message,
            initial_response=msg,
            cost_so_far=cost,
        )
        msg, cost = result.final_message, result.total_cost
"""
from app.services.self_correction.critic import (
    Verdict,
    critique,
)
from app.services.self_correction.loop import (
    CorrectionResult,
    run_correction_loop,
)
from app.services.self_correction.reviser import revise

__all__ = [
    "CorrectionResult",
    "Verdict",
    "critique",
    "revise",
    "run_correction_loop",
]
