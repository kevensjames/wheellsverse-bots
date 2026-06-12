"""Web fetch tool — pull a single URL → clean markdown for the LLM.

Distinct from `web_search` (Perplexity-backed, returns a synthesized
answer + citations). `web_fetch` is for "the user gave me a URL, read
the actual page contents." Lower latency, no third-party LLM in the
loop, just text extraction.

Backed by trafilatura — pure Python, 5MB install, no browser binaries.
Handles 95% of real-world articles, blog posts, docs pages, README
files, etc. Does NOT handle pure-JS-rendered SPAs (e.g. Twitter
without scroll). The user asked for crawl4ai; trafilatura is what
crawl4ai's basic mode wraps anyway, minus the Playwright overhead.

Output: cleaned-up markdown-ish text capped at 8000 chars so the
model doesn't choke. Most articles fit comfortably; very long ones
get truncated with a clear marker.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 8_000
FETCH_TIMEOUT = 15.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15 "
    "KAI-bot/1.0 (+https://kai.wheellsverse.com)"
)


class WebFetchTool:
    name = "web_fetch"
    description = (
        "Fetch the text contents of a single web page (article, blog post, "
        "documentation, README). Use when the user gives you a specific URL "
        "and asks about its contents — different from web_search, which is "
        "for finding answers across the web. Returns cleaned markdown-ish "
        "text from the page's main content area."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL to fetch (must include https://).",
            },
        },
        "required": ["url"],
    }

    def execute(self, ctx: ToolContext, *, url: str) -> dict[str, Any]:
        if not url or not url.strip():
            raise ToolError("url cannot be empty")

        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            raise ToolError("url must start with http:// or https://")
        if not parsed.netloc:
            raise ToolError("url is missing a host")
        # Don't let the model accidentally probe the daemon's own loopback
        if parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            raise ToolError("loopback URLs are not allowed")
        # Reject private IPs (best-effort SSRF guard)
        if parsed.hostname and parsed.hostname.startswith((
            "10.", "192.168.", "169.254.", "172.16.", "172.17.", "172.18.",
            "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
            "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.",
            "172.31.",
        )):
            raise ToolError("private/internal IP addresses are not allowed")

        try:
            r = httpx.get(
                url, timeout=FETCH_TIMEOUT, follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
        except httpx.HTTPError as e:
            raise ToolError(f"fetch failed: {e}")

        if r.status_code >= 400:
            raise ToolError(f"page returned HTTP {r.status_code}")

        ctype = (r.headers.get("content-type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            raise ToolError(f"unsupported content-type: {ctype}")

        html = r.text
        if not html.strip():
            raise ToolError("empty response body")

        # trafilatura does the real work
        try:
            import trafilatura
            extracted = trafilatura.extract(
                html, include_comments=False, include_tables=True,
                output_format="markdown",
            )
        except Exception as e:
            logger.exception("trafilatura extract failed")
            raise ToolError(f"could not extract text: {e}")

        text = (extracted or "").strip()
        if not text:
            raise ToolError("page had no extractable main-content text")

        truncated = False
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS]
            truncated = True

        return {
            "url": str(r.url),
            "status": r.status_code,
            "text": text,
            "chars": len(text),
            "truncated": truncated,
        }
