"""Lead enrichment adapter — finds a contact email for each lead, SiteBoost-style.

Reuses SiteBoost's own enricher (`core.email_enricher`): real Hunter.io
domain-search when `HUNTER_API_KEY` is set, otherwise a free deterministic
dry-run (mirrors Hunter's ~50% hit rate). Writes the discovered email back onto
each prospect in the business's leads artifact, so the outreach send finally has
real recipients. This is the missing link between "found a business" and
"can email it" — the same Stage-2 SiteBoost runs.
"""
from __future__ import annotations

import os

from core.portfolio import paths


class LeadsEnrichAdapter:
    def __init__(self, generate=None):
        self._generate = generate

    def run(self, action) -> dict:
        business = action.business
        leads_path = paths.business_dir(business) / "artifacts" / "leads" / "prospects.json"
        prospects = paths.load_json(leads_path, []) or []

        from core import email_enricher
        key = os.getenv("HUNTER_API_KEY", "").strip()
        dry = not key

        enriched = 0
        for p in prospects:
            if not isinstance(p, dict) or p.get("email") or not p.get("name"):
                continue
            hit = (email_enricher._dry_run_enrich(p) if dry
                   else email_enricher._hunter_domain_lookup(p.get("website", ""), key))
            if hit and hit.get("email"):
                p["email"] = hit["email"]
                if hit.get("first_name"):
                    p["contact_name"] = hit["first_name"]
                enriched += 1

        paths.save_json_atomic(leads_path, prospects)
        return {"status": "enriched", "verb": action.verb,
                "enriched": enriched, "total": len(prospects), "dry_run": dry,
                "note": ("dry-run (no HUNTER_API_KEY) — set the key for real Hunter.io lookups"
                         if dry else "live Hunter.io enrichment")}
