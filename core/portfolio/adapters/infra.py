from __future__ import annotations

import json

from core.portfolio import state


class InfraAdapter:
    def __init__(self, generate=None):
        self._generate = generate

    def run(self, action) -> dict:
        content = json.dumps({"business": action.business, "target": "TBD", "teardown": None})
        path = state.record_artifact(action.business, "infra", "deploy-manifest.json", content)
        return {
            "status": "draft",
            "note": "deploy capability greenfield — operator wires Railway/Coolify",
            "artifact": str(path),
            "verb": action.verb,
        }
