from __future__ import annotations


class OutreachSendAdapter:
    def __init__(self, generate=None):
        self._generate = generate

    def run(self, action) -> dict:
        return {
            "status": "would_send",
            "note": "gated send — wire cold_outreach.send_sequences(confirm=True, live=True) on approval",
            "verb": action.verb,
        }
