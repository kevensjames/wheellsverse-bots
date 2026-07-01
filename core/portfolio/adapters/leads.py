"""Lead-gen adapter — scans EACH business's own niche + geo (not a hardcoded city).

Live (GOOGLE_PLACES_API_KEY set): real Places searchText for `<niche> in <geo>`,
chains excluded. Otherwise dry-run fixtures scoped to the geo. Writes prospects.json.
"""
from __future__ import annotations

import json
import os

from core.portfolio import loop_context, state


class LeadsAdapter:
    def __init__(self, generate=None):
        self._generate = generate

    def run(self, action) -> dict:
        b = loop_context.business_ctx(action.business)
        niche, geo = b.get("lead_niche", ""), b.get("lead_geo", "")
        limit = action.payload.get("limit", 25)
        key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

        if key and niche and geo:
            from core import places_scanner
            from core.portfolio.leadgen import _parse_place, _places_text_search
            raw = _places_text_search(f"{niche} in {geo}", key, limit)
            leads = [_parse_place(p) for p in raw]
            leads = [L for L in leads if L.get("name") and not places_scanner._is_chain(L["name"])][:limit]
            mode = "live"
        else:
            from core import places_scanner
            prospects = places_scanner.scan(location=geo or "Boston, MA", dry_run=True, limit=limit)
            leads = [getattr(p, "__dict__", p) for p in prospects]
            mode = "dry_run"

        content = json.dumps(leads, default=str, indent=2)
        path = state.record_artifact(action.business, "leads", "prospects.json", content)
        return {"artifact": str(path), "verb": action.verb, "count": len(leads),
                "mode": mode, "niche": niche, "geo": geo}
