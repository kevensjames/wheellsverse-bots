#!/usr/bin/env python3
"""
core/indexnow.py
─────────────────────────────────────────────────────────────────────────────
Ping Bing / Yandex / Seznam (and any IndexNow-compliant search engine) when
new articles are published, so they re-crawl immediately instead of waiting
for their next scheduled crawl of the sitemap.

Free. No auth besides a shared key. Takes effect within minutes.

SETUP (one-time, ~2 minutes):

  1. Generate a key (any 8–128 hex chars):
        python -c "import secrets; print(secrets.token_hex(16))"

  2. Add to .env:
        INDEXNOW_KEY=<the key>

  3. Host the key at <domain>/<key>.txt. The file content must be the key
     itself on a single line. Two ways:

     a) Serve it through core/api.py (wire a /{INDEXNOW_KEY}.txt route
        that returns the key as plain text). One-time FastAPI change.

     b) Drop a file at frontend/<key>.txt with the key as content. If
        Cloudflare Pages or similar serves frontend/ statically, this
        works without a code change.

  4. Verify: curl https://wheellsverse.com/<your-key>.txt should return
     your key in plaintext.

  5. Done. Every future publish will auto-ping Bing/Yandex.

USAGE:

    from core import indexnow
    indexnow.ping_urls(["https://wheellsverse.com/blog/my-new-post"])
    indexnow.ping_all_canonical()  # bulk-ping every article on disk
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger("indexnow")

ROOT = Path(__file__).parent.parent

# Public IndexNow endpoints. Pinging ANY of them propagates to all
# IndexNow-participating engines within minutes, but hitting 2+ reduces
# single-endpoint outage risk. https://www.indexnow.org/
_ENDPOINTS = [
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
]

_MAX_URLS_PER_REQUEST = 10_000  # spec limit


def _get_host(url: str) -> str:
    """Extract hostname from a URL."""
    from urllib.parse import urlparse
    return urlparse(url).netloc


def ping_urls(urls: List[str], timeout: int = 10) -> dict:
    """
    Notify IndexNow endpoints about URLs that just changed.

    Returns {"sent": N, "results": [...], "skipped": reason}.
    Never raises — IndexNow is best-effort signaling, and a failure here
    should not break a publish flow.
    """
    key = os.getenv("INDEXNOW_KEY", "").strip()
    if not key:
        logger.debug("INDEXNOW_KEY not set — skipping IndexNow ping")
        return {"sent": 0, "skipped": "INDEXNOW_KEY not set"}

    if not urls:
        return {"sent": 0, "skipped": "no urls"}

    # All URLs in a single request must share the same host.
    host = _get_host(urls[0])
    if not host:
        return {"sent": 0, "skipped": "invalid url"}
    urls = [u for u in urls[:_MAX_URLS_PER_REQUEST] if _get_host(u) == host]

    payload = {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": urls,
    }

    try:
        import requests  # lazy import — keeps base_bot imports cheap
    except ImportError:
        logger.warning("requests not installed — skipping IndexNow ping")
        return {"sent": 0, "skipped": "requests not installed"}

    results = []
    for endpoint in _ENDPOINTS:
        try:
            r = requests.post(endpoint, json=payload, timeout=timeout)
            results.append({
                "endpoint": endpoint,
                "status": r.status_code,
                # 200 OK / 202 Accepted are both success per spec.
                "ok": r.status_code in (200, 202),
            })
            if r.status_code not in (200, 202):
                # 422 typically means key-file verification failed — log
                # the body so the operator can see what's wrong.
                logger.warning("IndexNow %s → %s: %s",
                               endpoint, r.status_code, r.text[:200])
            else:
                logger.info("IndexNow %s → %s (%d urls)",
                            endpoint, r.status_code, len(urls))
        except Exception as e:
            results.append({"endpoint": endpoint, "ok": False, "error": str(e)})
            logger.warning("IndexNow %s failed: %s", endpoint, e)

    any_ok = any(r.get("ok") for r in results)
    return {"sent": len(urls) if any_ok else 0, "results": results}


def ping_all_canonical(site_base: str = "") -> dict:
    """
    Ping IndexNow with every canonical article on disk. Useful to run once
    after the big slug migration so search engines re-crawl the new URLs.
    """
    site_base = (site_base or os.getenv("CTA_URL", "https://wheellsverse.com")).rstrip("/")
    blog_dir = ROOT / "frontend" / "blog"
    if not blog_dir.exists():
        return {"sent": 0, "skipped": "no blog dir"}
    urls = [
        f"{site_base}/blog/{p.stem}"
        for p in sorted(blog_dir.iterdir())
        if p.is_file() and p.suffix == ".html" and p.name != "index.html"
    ]
    # Also refresh the index itself and the sitemap, since the URL set changed.
    urls.extend([
        f"{site_base}/",
        f"{site_base}/blog/",
        f"{site_base}/sitemap.xml",
    ])
    return ping_urls(urls)


def is_configured() -> bool:
    return bool(os.getenv("INDEXNOW_KEY", "").strip())
