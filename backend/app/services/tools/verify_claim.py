"""verify_claim — check whether a factual claim is supported by the user's
indexed documents, with a confidence level + supporting citations.

Phase 2 of the professional-knowledge layer. Domain agents call this BEFORE
asserting an important factual claim, so an answer is either cited + verified or
honestly flagged as unverified. Reuses services/grounding (retrieve → LLM
fact-check → blended confidence). Builds its own router from the session, the
same way the audited admin endpoints do.
"""
from __future__ import annotations

from typing import Any

from app.services.tools.base import ToolContext, ToolError


class VerifyClaimTool:
    name = "verify_claim"
    description = (
        "Verify whether a single factual CLAIM is supported by the user's "
        "indexed documents. Returns a verdict (supported / partial / "
        "unsupported / contradicted / no_sources), a confidence level "
        "(high/medium/low), and the supporting passages (filename + position). "
        "Use this BEFORE asserting an important factual claim so you can cite "
        "it — and if it comes back unsupported or contradicted, say the sources "
        "don't support it instead of guessing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "claim": {
                "type": "string",
                "description": "One specific factual claim to verify (not a question).",
            },
            "k": {
                "type": "integer",
                "description": "How many source passages to check. Default 5, max 12.",
            },
        },
        "required": ["claim"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        claim = (kwargs.get("claim") or "").strip()
        if not claim:
            raise ToolError("claim is required")
        k = max(1, min(int(kwargs.get("k") or 5), 12))
        if getattr(ctx, "session", None) is None or getattr(ctx, "user_id", None) is None:
            raise ToolError("verify_claim needs an authenticated user session")
        try:
            from app.services import grounding
            from app.services.router import build_default_router
            rt = build_default_router(ctx.session)
            out = grounding.verify_statement(
                db=ctx.session, router=rt, user_id=ctx.user_id, statement=claim, k=k
            )
        except Exception as e:
            raise ToolError(f"verify failed: {e}")
        return {
            "claim": claim,
            "verdict": out["verdict"],
            "supported": out["supported"],
            "confidence": out["confidence"],
            "support": out["support"],
            "reason": out.get("reason", ""),
        }
