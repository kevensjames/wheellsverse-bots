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

SSRF hardening (audit SSRF-001): the host is RESOLVED and every resulting
IP is checked against private/loopback/link-local/reserved ranges with the
`ipaddress` module (not a string-prefix check, which missed DNS names that
resolve internally, IPv6, and encoded IPs like http://2130706433/). Redirects
are followed MANUALLY so each hop's Location is re-validated — `follow_redirects`
is off, closing the "302 → 169.254.169.254" bypass.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 8_000
FETCH_TIMEOUT = 15.0
MAX_REDIRECTS = 5
_REDIRECT_CODES = (301, 302, 303, 307, 308)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15 "
    "KAI-bot/1.0 (+https://kai.wheellsverse.com)"
)


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → refuse
    return bool(
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def _assert_safe_url(url: str) -> None:
    """Reject non-http(s), hostless, and any host that resolves to a
    private/internal address. Resolution failures fail open (httpx will then
    just fail to connect — nothing internal is reached)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("url must start with http:// or https://")
    host = parsed.hostname
    if not host:
        raise ToolError("url is missing a host")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return  # can't resolve here → connection will fail anyway
    for info in infos:
        if _ip_is_blocked(info[4][0]):
            raise ToolError("blocked: URL resolves to a private/internal address")


def _fetch(url: str) -> httpx.Response:
    """GET `url`, following up to MAX_REDIRECTS hops MANUALLY so every hop's
    host is re-validated against the SSRF guard before we connect to it."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _assert_safe_url(current)
        try:
            r = httpx.get(
                current, timeout=FETCH_TIMEOUT, follow_redirects=False,
                headers={"User-Agent": USER_AGENT},
            )
        except httpx.HTTPError as e:
            raise ToolError(f"fetch failed: {e}")
        if r.status_code in _REDIRECT_CODES:
            loc = r.headers.get("location")
            if not loc:
                return r
            current = urljoin(str(r.url), loc)
            continue
        return r
    raise ToolError("too many redirects")


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

        r = _fetch(url.strip())

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
