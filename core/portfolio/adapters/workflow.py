from __future__ import annotations

from core.portfolio import state


class WorkflowPackAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        content = self._generate(
            "Draft 3 n8n workflow blueprints (trigger -> nodes -> outcome) that solve a niche's "
            "painful manual workflows for " + action.business + "."
        )
        path = state.record_artifact(action.business, "workflows", "pack.md", content)
        return {"artifact": str(path), "verb": action.verb}
