"""Research engine — search web, scrape article bodies, summarize, ingest to RAG.

Search provider: DuckDuckGo HTML (no API key). Scrape: requests + BeautifulSoup.
Summarization: NarAI router (deep tier). RAG ingest: existing narai.core.rag.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Any

import requests
from bs4 import BeautifulSoup

from narai.core import rag, router, skills


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NarAI/1.0; +https://wheellsverse.com/narai)"
}


# ── Search ────────────────────────────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = 8) -> list[dict[str, str]]:
    """DuckDuckGo HTML scrape. Returns [{title, url, snippet}]."""
    url = "https://html.duckduckgo.com/html/"
    r = requests.post(url, data={"q": query}, headers=_HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    for result in soup.select("div.result")[:max_results]:
        title_el = result.select_one("a.result__a")
        snippet_el = result.select_one(".result__snippet")
        if not title_el:
            continue
        link = title_el.get("href", "")
        # DDG wraps links in a redirect; extract uddg param
        m = re.search(r"uddg=([^&]+)", link)
        if m:
            from urllib.parse import unquote
            link = unquote(m.group(1))
        results.append({
            "title": title_el.get_text(strip=True),
            "url": link,
            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
        })
    return results


# ── Scrape ────────────────────────────────────────────────────────────────────

def _scrape_article(url: str, max_chars: int = 8000) -> str:
    """Extract article body text from URL."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.raise_for_status()
    except Exception:
        return ""

    soup = BeautifulSoup(r.text, "html.parser")
    # Strip scripts/styles/nav
    for tag in soup(["script", "style", "nav", "footer", "aside", "form", "header"]):
        tag.decompose()

    # Prefer <article>, <main>, then body
    container = soup.find("article") or soup.find("main") or soup.body or soup
    text = container.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars]


# ── Summarize ─────────────────────────────────────────────────────────────────

async def _summarize(text: str, query: str) -> str:
    if not text.strip():
        return ""
    prompt = (
        f"Summarize the following article in the context of the query: '{query}'.\n"
        "Output 5-8 bullet points of the most important, concrete findings. "
        "Skip fluff, marketing copy, and filler. If the article is not relevant, "
        "output only: 'NOT RELEVANT'.\n\n"
        f"---\n{text}\n---"
    )
    system = skills.build_system_prompt(
        base="You are NarAI in research mode. Extract signal, discard noise.",
    )
    result = await router.call(prompt, tier="deep", system=system)
    return result.get("content", "")


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class ResearchBrief:
    query: str
    max_sources: int = 6
    ingest_to_rag: bool = True
    rag_label: str = ""                # source label for RAG; defaults to query


@dataclass
class ResearchResult:
    query: str
    n_sources: int
    n_ingested: int
    summaries: list[dict[str, Any]]    # [{title, url, summary}]
    combined: str                       # meta-summary of all sources

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def research(brief: ResearchBrief) -> ResearchResult:
    # 1. Search
    hits = _ddg_search(brief.query, max_results=brief.max_sources)
    if not hits:
        return ResearchResult(query=brief.query, n_sources=0, n_ingested=0,
                              summaries=[], combined="No search results.")

    # 2. Scrape + summarize each
    label = brief.rag_label or f"research:{brief.query[:40]}"
    summaries = []
    n_ingested = 0
    for hit in hits:
        body = _scrape_article(hit["url"])
        if not body:
            continue
        summary = await _summarize(body, brief.query)
        if summary.startswith("NOT RELEVANT"):
            continue
        summaries.append({
            "title": hit["title"],
            "url": hit["url"],
            "summary": summary,
        })
        if brief.ingest_to_rag:
            try:
                rag.ingest_text(
                    text=f"{hit['title']}\n{hit['url']}\n\n{summary}\n\n---\n{body[:4000]}",
                    source_label=label,
                    file_type="research",
                )
                n_ingested += 1
            except Exception:
                pass

    # 3. Combined meta-summary
    combined = ""
    if summaries:
        all_summaries = "\n\n".join(f"[{s['title']}]\n{s['summary']}" for s in summaries)
        prompt = (
            f"Given these per-source summaries on '{brief.query}', produce a meta-summary. "
            "Identify: (1) consensus points across sources, (2) disagreements, "
            "(3) the 3 most actionable takeaways, (4) open questions. Markdown.\n\n"
            f"---\n{all_summaries}\n---"
        )
        result = await router.call(prompt, tier="deep")
        combined = result.get("content", "")

    return ResearchResult(
        query=brief.query,
        n_sources=len(summaries),
        n_ingested=n_ingested,
        summaries=summaries,
        combined=combined,
    )
