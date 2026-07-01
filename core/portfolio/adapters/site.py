"""Site adapter — serves the business's GTM-kit Landing Copy (per business).
Records the landing copy artifact; actual publish is a gated operational step."""
from __future__ import annotations

from core.portfolio import loop_context, state


class SiteAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        slug = action.business
        content = loop_context.kit_section(slug, "Landing")
        source = "gtm_kit"
        if not content:
            b = loop_context.business_ctx(slug)
            source = "generated"
            content = self._generate(
                f"Landing page copy for {b.get('name', slug)}, H1 '{b.get('landing_headline', '')}': "
                f"hero, problem, offer ({b.get('offer', '')}), pricing ({b.get('price', '')}), FAQ, CTA."
            )
        path = state.record_artifact(slug, "sites", "landing.md", content or "")
        return {"artifact": str(path), "verb": action.verb, "source": source, "bytes": len(content or "")}
