"""who_search — search WHO Global Health Observatory (GHO) health INDICATORS by
keyword via the official OData API (ghoapi.azureedge.net). Keyless. Returns the
indicator code + name + a data link.

External-knowledge connector (same shape as pubmed_search). Whitelisted to the
medical agent for authoritative WHO statistics (prevalence, mortality, coverage,
risk factors). These are indicators/statistics — NOT clinical guidance text;
for guidance use web_fetch on who.int. Cite as [WHO GHO: <name> (<code>)].
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from app.services.tools.base import ToolContext, ToolError

_GHO = "https://ghoapi.azureedge.net/api/Indicator"
_UA = "KAI research assistant (admin@wheellsverse.com)"


class WhoSearchTool:
    name = "who_search"
    description = (
        "Search WHO Global Health Observatory (GHO) health INDICATORS by keyword "
        "(prevalence, mortality, coverage, risk factors, etc.). Returns indicator "
        "code + name + data link. Use for authoritative WHO health statistics; "
        "cite as [WHO GHO: <name> (<code>)]. Statistics/indicators — not clinical "
        "guidance text (use web_fetch on who.int for guidance documents)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword — condition, risk factor, or topic."},
            "max_results": {"type": "integer", "description": "Default 8, max 20."},
        },
        "required": ["query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("query is required")
        n = max(1, min(int(kwargs.get("max_results") or 8), 20))
        # OData: escape single quotes (double them), then URL-encode the $filter.
        odata = f"contains(IndicatorName,'{query.replace(chr(39), chr(39) * 2)}')"
        url = f"{_GHO}?{urllib.parse.urlencode({'$filter': odata})}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            raise ToolError(f"WHO GHO query failed: {e}")

        results: list[dict[str, Any]] = []
        for v in (data.get("value") or [])[:n]:
            code = v.get("IndicatorCode") or ""
            results.append({
                "code": code,
                "name": v.get("IndicatorName") or "",
                "url": f"https://ghoapi.azureedge.net/api/{code}" if code else "",
            })
        return {
            "query": query, "count": len(results), "results": results,
            "note": ("Cite as [WHO GHO: <name> (<code>)]; the URL returns the indicator's data."
                     if results else "No WHO indicators matched — try a broader keyword."),
        }
