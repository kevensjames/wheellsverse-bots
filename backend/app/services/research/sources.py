"""Source fetchers — HN top stories, arXiv cs.AI, GitHub Trending.

Each fetcher returns a list[Item]. Item is a uniform shape across sources
so the scorer + digest don't have to special-case. Network failures are
caught + logged; the digest cycle continues with whatever sources succeed.

Why these three:
  HN              — operator-relevant tech signal, near-real-time
  arXiv cs.AI     — research direction, slower but higher signal
  GH Trending     — what people are actually building right now

CVE feed was on the original sprint plan but skipped for MVP — KAI
Supreme already scans for env-completeness; CVEs would overlap with
that surface without much marginal value at this stage.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 kai-research/1.0"
_HTTP_TIMEOUT = 15.0


@dataclass(slots=True)
class Item:
    source: str        # "hn" / "arxiv" / "gh_trending"
    title: str
    url: str
    summary: str       # short — what makes this interesting
    score: float = 0.0  # set by scorer; 0..1
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# ─── Hacker News ─────────────────────────────────────────────────────


def fetch_hn(top_n: int = 30) -> list[Item]:
    """HN's official Firebase API. Free, no auth, ~no rate limits at this
    volume. Returns the top N stories ranked by their current HN score."""
    try:
        ids = _get_json(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
        )[:top_n]
    except Exception as e:
        logger.warning("research: hn topstories failed: %s", e)
        return []

    out: list[Item] = []
    for sid in ids:
        try:
            s = _get_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if not s or s.get("type") != "story":
                continue
            title = s.get("title") or ""
            url = s.get("url") or f"https://news.ycombinator.com/item?id={sid}"
            out.append(Item(
                source="hn",
                title=title,
                url=url,
                summary=f"{s.get('score', 0)} pts · {s.get('descendants', 0)} comments",
                metadata={
                    "hn_id": sid,
                    "hn_score": s.get("score"),
                    "by": s.get("by"),
                },
            ))
        except Exception as e:
            logger.warning("research: hn item %s failed: %s", sid, e)
            continue
    return out


# ─── arXiv ───────────────────────────────────────────────────────────


def fetch_arxiv(category: str = "cs.AI", max_results: int = 30) -> list[Item]:
    """arXiv's Atom feed. Returns the most recent papers in the category.

    The Atom XML parsing is intentionally a regex/string split instead of
    pulling lxml — the structure is stable and the deps are heavy.
    """
    qs = urllib.parse.urlencode({
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": int(max_results),
    })
    url = f"http://export.arxiv.org/api/query?{qs}"
    try:
        body = _get_text(url)
    except Exception as e:
        logger.warning("research: arxiv fetch failed: %s", e)
        return []

    return _parse_arxiv_atom(body)


def _parse_arxiv_atom(xml: str) -> list[Item]:
    """Pull <entry> blocks out of arXiv's Atom feed. Tolerates minor
    formatting drift — we use compiled regexes against the field tags."""
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
    out: list[Item] = []
    for e in entries:
        title = _pluck(e, "title")
        summary = _pluck(e, "summary")
        link = ""
        link_m = re.search(r'<link[^>]+href="([^"]+)"[^>]*rel="alternate"', e)
        if link_m:
            link = link_m.group(1)
        if not link:
            link_m = re.search(r'<id>([^<]+)</id>', e)
            if link_m:
                link = link_m.group(1).strip()
        if not title or not link:
            continue
        out.append(Item(
            source="arxiv",
            title=_collapse_ws(title),
            url=link,
            summary=_collapse_ws(summary)[:500],
            metadata={"arxiv_id": link.rsplit("/", 1)[-1]},
        ))
    return out


# ─── GitHub Trending ─────────────────────────────────────────────────


def fetch_gh_trending(window_days: int = 1, top_n: int = 25) -> list[Item]:
    """GitHub doesn't expose Trending as an API. We use the search API
    sorted by stars created in the last N days — a reasonable proxy. The
    `created:` filter targets brand-new projects; tweak to `pushed:` for
    actively-maintained ones."""
    from datetime import datetime, timedelta, timezone
    since = (
        datetime.now(timezone.utc) - timedelta(days=max(1, int(window_days)))
    ).strftime("%Y-%m-%d")
    qs = urllib.parse.urlencode({
        "q": f"created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": int(top_n),
    })
    url = f"https://api.github.com/search/repositories?{qs}"
    try:
        body = _get_json(url)
    except Exception as e:
        logger.warning("research: gh trending failed: %s", e)
        return []
    out: list[Item] = []
    for r in (body or {}).get("items", []):
        out.append(Item(
            source="gh_trending",
            title=r.get("full_name") or "",
            url=r.get("html_url") or "",
            summary=(r.get("description") or "")[:500],
            metadata={
                "stars": r.get("stargazers_count"),
                "language": r.get("language"),
                "topics": r.get("topics") or [],
            },
        ))
    return out


# ─── helpers ────────────────────────────────────────────────────────


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
        return json.loads(r.read())


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


def _pluck(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL)
    return (m.group(1) if m else "").strip()


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()
