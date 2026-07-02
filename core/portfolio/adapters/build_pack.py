"""Generic build-pack adapter — handles EVERY business's `build_*` step.

The old WorkflowPackAdapter was n8n-only, so the other 9 businesses' build steps
fell through to a no-op. This one reads the business's GTM-kit "Service Pack" section
(already generated per business) and records it as the pack artifact; if the kit is
missing it falls back to generating from the registry definition.
"""
from __future__ import annotations

from core.portfolio import loop_context, state


class BuildPackAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        slug = action.business
        pack = loop_context.kit_section(slug, "Service Pack")
        source = "gtm_kit"
        if not pack:
            b = loop_context.business_ctx(slug)
            source = "generated"
            pack = self._generate(
                f"Spec the '{b.get('build_step', 'build_pack')}' productized-service pack for "
                f"{b.get('name', slug)}: {b.get('offer', '')}. List components, what the client "
                f"receives, and reused-across-clients vs customized-per-client."
            )
        path = state.record_artifact(slug, "pack", "pack.md", pack or "")
        return {"artifact": str(path), "verb": action.verb, "source": source, "bytes": len(pack or "")}
