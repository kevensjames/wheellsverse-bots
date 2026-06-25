"""Opportunity Scanner — real outward-facing demand signal, not an empty report.

Pulls LIVE public feeds (Hacker News front page via the Algolia API, and recently
-popular GitHub repos via the search API — both free, no auth), scores each item
for "buildable opportunity" signal, and returns a SHORT ranked, actionable list
(open the link, act or dismiss). Feeds needing auth/scraping (Reddit, Product Hunt,
Indie Hackers) are reported as not-connected rather than faked.

Anti-trap design: this exists to point OUTWARD at real demand and produce a small
number of acts — not to emit a daily wall of analysis. Every item is a real URL.
"""
from __future__ import annotations

import json
import time
import urllib.request

# Signals that a headline describes a thing people build/buy/launch — i.e. a
# potential product wedge, not just news.
_SIGNAL_WORDS = {
    "saas", "tool", "automation", "api", "ai", "agent", "boilerplate",
    "open source", "open-source", "self-host", "self-hosted", "selfhost",
    "launch", "show hn", "i built", "i made", "side project", "indie",
    "mvp", "no-code", "no code", "nocode", "workflow", "dashboard",
    "analytics", "newsletter", "cms", "scheduling", "scheduler", "crm",
    "alternative to", "replace", "monetize", "revenue", "first paying",
}


def _get_json(url: str, timeout: int = 8):
    """Single network read — the seam tests monkeypatch."""
    req = urllib.request.Request(url, headers={"User-Agent": "wmos-opportunity-scanner"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https only)
        return json.loads(r.read().decode("utf-8"))


def _score(title: str) -> int:
    t = (title or "").lower()
    return sum(1 for w in _SIGNAL_WORDS if w in t)


def _hackernews() -> dict:
    try:
        d = _get_json("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30")
        items = []
        for h in d.get("hits", []):
            title = h.get("title") or ""
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            items.append({"source": "hackernews", "title": title, "url": url,
                          "popularity": int(h.get("points") or 0), "score": _score(title)})
        return {"connected": True, "items": items}
    except Exception as e:  # network/parse failure -> honest not-connected
        return {"connected": False, "error": str(e), "items": []}


def _github(now: float | None = None) -> dict:
    try:
        now = now if now is not None else time.time()
        since = time.strftime("%Y-%m-%d", time.gmtime(now - 21 * 86400))
        q = urllib.request.quote(f"created:>{since}")
        d = _get_json(f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=20")
        items = []
        for r in d.get("items", []):
            title = ((r.get("name") or "") + " — " + (r.get("description") or "")).strip(" —")
            items.append({"source": "github", "title": title, "url": r.get("html_url", ""),
                          "popularity": int(r.get("stargazers_count") or 0), "score": _score(title)})
        return {"connected": True, "items": items}
    except Exception as e:
        return {"connected": False, "error": str(e), "items": []}


def scan(limit: int = 10, *, now: float | None = None) -> dict:
    """Live scan -> ranked, actionable opportunity list + honest feed connectivity."""
    hn = _hackernews()
    gh = _github(now=now)
    feeds = {
        "hackernews": hn["connected"],
        "github": gh["connected"],
        "reddit": False,          # needs OAuth
        "producthunt": False,     # needs API token
        "indiehackers": False,    # no public API (scrape only)
    }
    pool = [it for it in (hn["items"] + gh["items"])]
    # Rank: signal score first, then popularity. Only surface items with >=1 signal.
    ranked = sorted([p for p in pool if p["score"] > 0],
                    key=lambda p: (p["score"], p["popularity"]), reverse=True)[:limit]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time())),
        "feeds": feeds,
        "connected_feeds": sum(1 for v in feeds.values() if v),
        "opportunities": ranked,
        "scanned": len(pool),
        "note": "Each item is a real link. Act on it or dismiss it — do not let this become a report you scroll past.",
    }
