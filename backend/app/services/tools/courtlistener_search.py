"""courtlistener_search — search U.S. court opinions (case law) via CourtListener
(Free Law Project) REST API v4. Free anonymous access; set COURTLISTENER_API_KEY
for higher rate limits. Returns citable cases — name, court, date, reporter
citation, docket, link.

External-knowledge connector (same shape as pubmed_search). Whitelisted to the
legal RESEARCH agent (never advice). Cite as [<case name>, <citation>].
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from app.services.tools.base import ToolContext, ToolError

_SEARCH = "https://www.courtlistener.com/api/rest/v4/search/"
_UA = "KAI research assistant (admin@wheellsverse.com)"


class CourtListenerSearchTool:
    name = "courtlistener_search"
    description = (
        "Search U.S. court opinions (case law) via CourtListener. Returns "
        "citable cases: case name, court, date filed, reporter citation, docket "
        "number, and link. Use to surface relevant case law for legal RESEARCH "
        "(never advice); cite as [<case name>, <citation>]."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms — issue, party, or doctrine."},
            "max_results": {"type": "integer", "description": "Default 6, max 15."},
        },
        "required": ["query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("query is required")
        n = max(1, min(int(kwargs.get("max_results") or 6), 15))
        url = f"{_SEARCH}?{urllib.parse.urlencode({'q': query, 'type': 'o', 'order_by': 'score desc'})}"
        headers = {"User-Agent": _UA, "Accept": "application/json"}
        key = os.environ.get("COURTLISTENER_API_KEY")
        if key:
            headers["Authorization"] = f"Token {key}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            raise ToolError(f"CourtListener query failed: {e}")

        results: list[dict[str, Any]] = []
        for c in (data.get("results") or [])[:n]:
            cites = c.get("citation") or []
            results.append({
                "case": c.get("caseName") or c.get("caseNameFull") or "",
                "court": c.get("court") or c.get("court_citation_string") or "",
                "date": c.get("dateFiled") or "",
                "citation": (cites[0] if isinstance(cites, list) and cites else ""),
                "docket": c.get("docketNumber") or "",
                "url": ("https://www.courtlistener.com" + c["absolute_url"]) if c.get("absolute_url") else "",
            })
        return {
            "query": query, "count": len(results), "results": results,
            "note": ("Cite as [<case name>, <citation>]. Research only — not legal advice."
                     if results else "No opinions matched — try different terms."),
        }
