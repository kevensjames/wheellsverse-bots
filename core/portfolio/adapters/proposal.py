"""Proposal adapter — serves the business's GTM-kit Proposal Template (per business)."""
from __future__ import annotations

from core.portfolio import loop_context, state


class ProposalAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        slug = action.business
        content = loop_context.kit_section(slug, "Proposal")
        source = "gtm_kit"
        if not content:
            b = loop_context.business_ctx(slug)
            source = "generated"
            content = self._generate(
                f"One-page proposal for {b.get('offer', '')} at {b.get('price', '')} to {b.get('icp', '')}: "
                f"outcome, scope, timeline, investment, risk-reversal, next step."
            )
        path = state.record_artifact(slug, "proposals", "proposal.md", content or "")
        return {"artifact": str(path), "verb": action.verb, "source": source, "bytes": len(content or "")}
