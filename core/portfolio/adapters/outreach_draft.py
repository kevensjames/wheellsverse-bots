"""Outreach-draft adapter — serves the business's GTM-kit Outreach Sequence."""
from __future__ import annotations

from core.portfolio import loop_context, state


class OutreachDraftAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        slug = action.business
        content = loop_context.kit_section(slug, "Outreach")
        source = "gtm_kit"
        if not content:
            b = loop_context.business_ctx(slug)
            source = "generated"
            content = self._generate(
                f"3-touch cold-email sequence (Day 0/3/7, subject+body, opt-out) for {b.get('icp', '')} "
                f"opening from: {b.get('outreach_hook', '')}. Offer: {b.get('offer', '')}."
            )
        path = state.record_artifact(slug, "outreach", "sequence.md", content or "")
        return {"artifact": str(path), "verb": action.verb, "source": source, "bytes": len(content or "")}
