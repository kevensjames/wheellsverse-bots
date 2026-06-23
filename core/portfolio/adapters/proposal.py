from __future__ import annotations

from core.portfolio import state


class ProposalAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        content = self._generate(
            "Draft a 1-page proposal + SOW + price for an n8n automation retainer for a prospect of "
            + action.business + "."
        )
        path = state.record_artifact(action.business, "proposals", "proposal.md", content)
        return {"artifact": str(path), "verb": action.verb}
