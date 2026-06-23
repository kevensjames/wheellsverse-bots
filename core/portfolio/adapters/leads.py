from __future__ import annotations

import json

from core.portfolio import state


class LeadsAdapter:
    def __init__(self, generate=None):
        self._generate = generate

    def run(self, action) -> dict:
        from core import places_scanner
        prospects = places_scanner.scan(
            location=action.payload.get("location", "Boston, MA"),
            dry_run=True,
            limit=action.payload.get("limit", 25),
        )
        content = json.dumps([getattr(p, "__dict__", p) for p in prospects], default=str, indent=2)
        path = state.record_artifact(action.business, "leads", "prospects.json", content)
        return {"artifact": str(path), "verb": action.verb, "count": len(prospects)}
