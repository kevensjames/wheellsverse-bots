from __future__ import annotations

from core.portfolio import state


class SiteAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        content = self._generate(
            "Generate a single-file landing page (inline CSS) for the n8n automation service of "
            + action.business + "."
        )
        path = state.record_artifact(action.business, "sites", "landing.html", content)
        return {"artifact": str(path), "verb": action.verb}
