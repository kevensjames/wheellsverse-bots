"""sec_edgar_search — SEC EDGAR full-text search for company filings (10-K, 10-Q,
8-K, etc.). Official US-government API (efts.sec.gov); filings are public domain.
Keyless, but EDGAR's fair-access policy requires an identifying User-Agent.

External-knowledge connector (same shape as pubmed_search). Whitelisted to the
finance + accounting agents to ground answers in primary regulatory filings.
Returns citable hits — company, form, filing date, accession, link. Cite as
[SEC: <company> <form> <date>].
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from app.services.tools.base import ToolContext, ToolError

_FTS = "https://efts.sec.gov/LATEST/search-index"
_UA = "KAI research assistant (admin@wheellsverse.com)"


class SecEdgarSearchTool:
    name = "sec_edgar_search"
    description = (
        "Full-text search SEC EDGAR for company filings (10-K, 10-Q, 8-K, etc.). "
        "Returns citable results: company, form type, filing date, accession "
        "number, and a link to the filing. Use to ground finance/accounting "
        "answers in primary regulatory filings; cite as [SEC: <company> <form> "
        "<date>]. US public filings only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search terms — company, topic, or phrase."},
            "forms": {"type": "string", "description": "Optional form filter, e.g. '10-K' or '10-K,10-Q'."},
            "max_results": {"type": "integer", "description": "Default 6, max 15."},
        },
        "required": ["query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("query is required")
        n = max(1, min(int(kwargs.get("max_results") or 6), 15))
        params = {"q": query}
        forms = (kwargs.get("forms") or "").strip()
        if forms:
            params["forms"] = forms
        url = f"{_FTS}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            raise ToolError(f"EDGAR query failed: {e}")

        hits = (((data.get("hits") or {}).get("hits")) or [])[:n]
        results: list[dict[str, Any]] = []
        for h in hits:
            src = h.get("_source") or {}
            adsh = src.get("adsh") or ""
            ciks = src.get("ciks") or []
            cik = str(int(ciks[0])) if ciks and str(ciks[0]).isdigit() else (ciks[0] if ciks else "")
            _id = h.get("_id") or ""
            filename = _id.split(":", 1)[1] if ":" in _id else ""
            doc_url = ""
            if cik and adsh and filename:
                doc_url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                           f"{adsh.replace('-', '')}/{filename}")
            results.append({
                "company": (src.get("display_names") or [""])[0],
                "form": src.get("form") or "",
                "date": src.get("file_date") or "",
                "accession": adsh,
                "url": doc_url,
            })
        return {
            "query": query, "count": len(results), "results": results,
            "note": ("Cite as [SEC: <company> <form> <date>]." if results
                     else "No EDGAR filings matched — try different terms."),
        }
