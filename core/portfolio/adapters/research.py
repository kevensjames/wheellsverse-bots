"""Research adapter — serves the business's GTM-kit Market Brief (per business),
falling back to generation from the registry definition if no kit exists."""
from __future__ import annotations

from core.portfolio import loop_context, state


class ResearchAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        slug = action.business
        content = loop_context.kit_section(slug, "Market Brief")
        source = "gtm_kit"
        if not content:
            b = loop_context.business_ctx(slug)
            source = "generated"
            content = self._generate(
                f"Market brief for {b.get('name', slug)} selling {b.get('offer', '')} to "
                f"{b.get('icp', '')} in {b.get('lead_niche', '')} ({b.get('lead_geo', '')}): "
                f"top 3 pains, 2 alternatives, the sharpest wedge, 3 objections."
            )
        path = state.record_artifact(slug, "research", "niche.md", content or "")
        return {"artifact": str(path), "verb": action.verb, "source": source, "bytes": len(content or "")}
