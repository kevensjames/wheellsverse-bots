from __future__ import annotations

from core.portfolio import state


class ResearchAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        content = self._generate(
            "Research a profitable automation-agency niche for the n8n business "
            + action.business
            + ". List target sub-industry, 3 painful manual workflows, ICP, and a one-line wedge."
        )
        path = state.record_artifact(action.business, "research", "niche.md", content)
        return {"artifact": str(path), "verb": action.verb}
