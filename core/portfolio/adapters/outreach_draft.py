from __future__ import annotations

from core.portfolio import state


class OutreachDraftAdapter:
    def __init__(self, generate=None):
        self._generate = generate or (lambda p: "")

    def run(self, action) -> dict:
        content = self._generate(
            "Write a 3-touch cold-email sequence (Day 0/3/7, subject+body, CAN-SPAM footer) offering "
            "n8n automation setup to a prospect in the niche of " + action.business + "."
        )
        path = state.record_artifact(action.business, "outreach", "sequence.md", content)
        return {"artifact": str(path), "verb": action.verb}
