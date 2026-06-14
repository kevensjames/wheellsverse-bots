"""clinicaltrials_search — search ClinicalTrials.gov (NIH/NLM) v2 API for
registered clinical trials. Official, keyless. Returns citable trials: NCT id,
title, status, phase, and URL.

External-knowledge connector (same shape as pubmed_search). The "trials" source
for the medical agent — distinct from pubmed_search (published literature). Cite
as [NCT<id>]. Registry metadata, not trial results/conclusions.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from app.services.tools.base import ToolContext, ToolError

_API = "https://clinicaltrials.gov/api/v2/studies"
_UA = "KAI research assistant (admin@wheellsverse.com)"


class ClinicalTrialsSearchTool:
    name = "clinicaltrials_search"
    description = (
        "Search ClinicalTrials.gov for registered clinical trials matching a "
        "query. Returns NCT id, title, recruitment status, phase, and URL. Use "
        "for trial evidence in medical research; cite as [NCT<id>]. This is "
        "registry metadata (what's being studied + status) — not trial results."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Condition, intervention, or topic."},
            "max_results": {"type": "integer", "description": "Default 6, max 15."},
        },
        "required": ["query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("query is required")
        n = max(1, min(int(kwargs.get("max_results") or 6), 15))
        url = f"{_API}?{urllib.parse.urlencode({'query.term': query, 'pageSize': n, 'format': 'json'})}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            raise ToolError(f"ClinicalTrials.gov query failed: {e}")

        results: list[dict[str, Any]] = []
        for s in (data.get("studies") or [])[:n]:
            ps = s.get("protocolSection") or {}
            idm = ps.get("identificationModule") or {}
            nct = idm.get("nctId") or ""
            phases = (ps.get("designModule") or {}).get("phases") or []
            results.append({
                "nct": nct,
                "title": idm.get("briefTitle") or "",
                "status": (ps.get("statusModule") or {}).get("overallStatus") or "",
                "phase": "/".join(phases) if phases else "",
                "url": f"https://clinicaltrials.gov/study/{nct}" if nct else "",
            })
        return {
            "query": query, "count": len(results), "results": results,
            "note": ("Cite as [NCT<id>]. Registry metadata — check the trial page for results."
                     if results else "No trials matched — try different terms."),
        }
