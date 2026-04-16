#!/usr/bin/env python3
"""
core/search_engine.py
─────────────────────────────────────────────────────────────────────────────
Web search for NarAI chat using DuckDuckGo (free, no API key).
Fetches page content with BeautifulSoup for deep answers.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import re
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("search_engine")

SEARCH_ENABLED = os.getenv("SEARCH_ENABLED", "true").lower() == "true"
MAX_SNIPPET_LEN = 300
MAX_PAGE_CHARS = 8_000
TIMEOUT = 8

# ─── Intent patterns that trigger search ─────────────────────────────────────
_SEARCH_PATTERNS = re.compile(
    r'\b(?:search|look up|find|what is the latest|current|today|'
    r'news about|find me info on|whats happening|latest on|'
    r'trending|breaking|who is|when did|how much|price of)\b',
    re.I
)


def should_search(text: str) -> bool:
    """Return True if the message likely needs a web search."""
    if not SEARCH_ENABLED:
        return False
    return bool(_SEARCH_PATTERNS.search(text))


# ─── DuckDuckGo search ────────────────────────────────────────────────────────

def search(query: str, num_results: int = 5) -> List[Dict]:
    """
    Search DuckDuckGo. Returns list of {title, url, snippet}.
    Uses duckduckgo-search library if available, falls back to DDG HTML.
    """
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")[:MAX_SNIPPET_LEN],
                })
        return results
    except ImportError:
        return _ddg_html_fallback(query, num_results)
    except Exception as e:
        logger.warning(f"[search] DuckDuckGo error: {e}")
        return _ddg_html_fallback(query, num_results)


def _ddg_html_fallback(query: str, num_results: int) -> List[Dict]:
    """HTML scrape fallback for DuckDuckGo."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NarAI/1.0)"}
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            timeout=TIMEOUT,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for el in soup.select(".result__body")[:num_results]:
            title_el = el.select_one(".result__title")
            snippet_el = el.select_one(".result__snippet")
            link_el = el.select_one(".result__url")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            url = link_el.get_text(strip=True) if link_el else ""
            if not url.startswith("http"):
                url = "https://" + url
            results.append({"title": title, "url": url, "snippet": snippet[:MAX_SNIPPET_LEN]})
        return results
    except Exception as e:
        logger.warning(f"[search] HTML fallback failed: {e}")
        return []


# ─── Fetch page content ───────────────────────────────────────────────────────

def fetch_page(url: str) -> str:
    """
    Fetch and clean the text content of a web page.
    Returns cleaned text string (max MAX_PAGE_CHARS).
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NarAI/1.0)"}
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style/nav/footer
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:MAX_PAGE_CHARS]
    except Exception as e:
        logger.debug(f"[search] fetch_page failed for {url}: {e}")
        return ""


# ─── Format results for Claude ────────────────────────────────────────────────

def format_results_for_claude(query: str, results: List[Dict]) -> str:
    """Format search results as a system-context string for Claude."""
    if not results:
        return f"[Web Search: '{query}' — no results found]"

    lines = [f"[Web Search Results for: '{query}']\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   URL: {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        lines.append("")
    lines.append("Use the above search results to inform your answer. Always cite sources.")
    return "\n".join(lines)


def run_search(query: str, num_results: int = 5) -> Dict[str, Any]:
    """
    Full search pipeline: search + format for Claude.
    Returns {results, context, query}
    """
    results = search(query, num_results)
    context = format_results_for_claude(query, results)
    return {
        "results": results,
        "context": context,
        "query": query,
        "found": len(results),
    }
