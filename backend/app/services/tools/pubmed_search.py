"""pubmed_search — query PubMed (NCBI E-utilities) for peer-reviewed biomedical
literature and return CITABLE results: PMID, title, authors, journal, year, URL.

This is the reference external-knowledge connector (Phase 3). Deliberately a LIVE
official-API query rather than bulk-scraping a copyrighted database into the
vector store: ToS-clean (NCBI's public E-utilities), always current, and cheap.
No key required (set NCBI_API_KEY for higher rate limits). EDGAR / CourtListener
/ etc. follow this same shape, each pending its own per-source ToS review.

The Medical Researcher agent uses it to ground answers in primary sources and
cite them as [PMID <id>]. Returns metadata + where to read — not full text.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from app.services.tools.base import ToolContext, ToolError

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_UA = "KAI/1.0 (research assistant; +https://kai.wheellsverse.com)"


class PubMedSearchTool:
    name = "pubmed_search"
    description = (
        "Search PubMed (peer-reviewed biomedical literature) and return citable "
        "results: PMID, title, authors, journal, year, and URL. Use to ground "
        "medical/biomedical answers in primary sources and cite them as "
        "[PMID <id>]. Returns article metadata + where to read more (not full "
        "text). Prefer recent reviews/guidelines for clinical questions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search terms — condition, drug, intervention, etc.",
            },
            "max_results": {
                "type": "integer",
                "description": "How many articles to return. Default 6, max 20.",
            },
        },
        "required": ["query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("query is required")
        n = max(1, min(int(kwargs.get("max_results") or 6), 20))
        try:
            ids = self._esearch(query, n)
            results = self._esummary(ids) if ids else []
        except Exception as e:
            raise ToolError(f"PubMed query failed: {e}")
        return {
            "query": query,
            "count": len(results),
            "results": results,
            "note": (
                "Cite as [PMID <id>]. Metadata only — open the URL for the "
                "abstract/full text (you can web_fetch it)."
                if results
                else "No PubMed results — try different/broader terms."
            ),
        }

    # ── NCBI E-utilities ──────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        key = os.environ.get("NCBI_API_KEY")
        if key:
            params["api_key"] = key
        url = f"{_EUTILS}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def _esearch(self, query: str, n: int) -> list[str]:
        data = self._get("esearch.fcgi", {
            "db": "pubmed", "term": query, "retmax": n,
            "retmode": "json", "sort": "relevance",
        })
        return (data.get("esearchresult") or {}).get("idlist") or []

    def _esummary(self, ids: list[str]) -> list[dict[str, Any]]:
        data = self._get("esummary.fcgi", {
            "db": "pubmed", "id": ",".join(ids), "retmode": "json",
        })
        res = data.get("result") or {}
        out: list[dict[str, Any]] = []
        for pid in ids:
            d = res.get(pid)
            if not isinstance(d, dict):
                continue
            authors = [a.get("name") for a in (d.get("authors") or []) if a.get("name")]
            authors_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            pubdate = d.get("pubdate") or ""
            year = pubdate.split(" ")[0][:4] if pubdate else ""
            out.append({
                "pmid": pid,
                "title": d.get("title") or "",
                "authors": authors_str,
                "journal": d.get("fulljournalname") or d.get("source") or "",
                "year": year,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            })
        return out
