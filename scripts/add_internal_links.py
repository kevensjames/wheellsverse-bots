#!/usr/bin/env python3
"""
scripts/add_internal_links.py
─────────────────────────────────────────────────────────────────────────────
Add a "Related Articles" block to every canonical article in frontend/blog/.

WHY THIS EXISTS
    Internal linking is the single biggest whole-site SEO lift you can do
    on an existing corpus. Each article gains 3–5 inbound links from other
    articles on the same domain, which:
      - Spreads link equity across the site
      - Gives search engines more context about topic clusters
      - Increases session depth (users click through related content)
      - Lowers bounce rate

    Cost: zero. Risk: zero (no external API, no account age required).

SIMILARITY
    Cheap token-overlap on the slug. "best-crypto-exchange-for-beginners"
    shares tokens {best, crypto, exchange, for, beginners} with other crypto
    posts. Stopwords (the, a, and, …) are filtered so matches reflect
    topical overlap instead of grammar overlap.

IDEMPOTENT
    Wraps the injected block in HTML comment markers. Re-running the script
    strips any prior block and regenerates. Safe to run after every batch
    of new articles.

USAGE
    # dry-run (default):
    python scripts/add_internal_links.py

    # apply:
    python scripts/add_internal_links.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
BLOG_DIR = ROOT / "frontend" / "blog"
SKIP = {"index.html"}

# Stopwords that create noise in slug-token overlap. These words appear in
# many slugs without signaling a shared topic.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "the", "to", "with", "without",
    "my", "your", "you", "we", "us", "i", "me", "do", "does", "did",
    "that", "this", "these", "those", "not", "vs", "what", "when", "which",
    "why", "who", "best", "top", "new", "real", "also", "them",
})

# How many related articles to surface per post.
_RELATED_COUNT = 5

# Marker strings so re-runs are idempotent.
_START = "<!-- wheellsverse-related-start -->"
_END = "<!-- wheellsverse-related-end -->"

# Minimum shared tokens to consider two articles related. Below this, we
# skip the pair — prevents showing unrelated posts just to fill the slot.
_MIN_OVERLAP = 1


def tokenize(slug: str) -> Set[str]:
    tokens = re.split(r"[-_]+", slug.lower())
    return {
        t for t in tokens
        if t and not t.isdigit() and t not in _STOPWORDS and len(t) > 2
    }


def extract_title(html: str, fallback_slug: str) -> str:
    """Pull the <title> or first <h1> content. Fall back to a prettified slug."""
    for pat in (r"<title>([^<]+?)(?:\s+—\s+WheellsVerse)?</title>",
                r"<h1[^>]*>([^<]+)</h1>"):
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    # Fallback: title-case the slug.
    return fallback_slug.replace("-", " ").title()


def strip_existing_block(html: str) -> str:
    """Remove any prior Related Articles block so re-runs regenerate."""
    return re.sub(
        f"{re.escape(_START)}.*?{re.escape(_END)}",
        "",
        html,
        flags=re.DOTALL,
    )


def build_related_html(source_slug: str,
                       related: List[Tuple[str, str]]) -> str:
    """Build the injected HTML fragment. `related` is [(slug, title), ...]."""
    items = "".join(
        f'    <li style="margin:6px 0"><a href="/blog/{slug}" '
        f'style="color:#0099bb;text-decoration:none">{title}</a></li>\n'
        for slug, title in related
    )
    return (
        f"{_START}\n"
        f'<aside style="margin:40px 0 24px;padding:20px;background:#f7f9fb;'
        f'border-left:3px solid #00d4ff;border-radius:6px;'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif">\n'
        f'  <h3 style="margin:0 0 12px;font-size:16px;color:#111">Related reading</h3>\n'
        f'  <ul style="list-style:none;padding:0;margin:0;font-size:14px;line-height:1.6">\n'
        f"{items}"
        f"  </ul>\n"
        f"</aside>\n"
        f"{_END}"
    )


def inject_before_footer(html: str, block: str) -> Tuple[str, bool]:
    """Insert the block immediately before <footer>. Returns (html, inserted)."""
    # Match opening <footer tag, capturing the whitespace that precedes it
    # so we can keep indentation consistent.
    m = re.search(r"(\n\s*)<footer", html, re.IGNORECASE)
    if m:
        insert_at = m.start(1)  # just before the newline+indent
        return html[:insert_at] + "\n" + block + html[insert_at:], True
    # Fallback: insert just before </body>
    m = re.search(r"</body>", html, re.IGNORECASE)
    if m:
        return html[:m.start()] + block + "\n" + html[m.start():], True
    return html, False


def compute_related(index: Dict[str, Set[str]],
                    k: int = _RELATED_COUNT) -> Dict[str, List[str]]:
    """For each slug, pick top-k others by shared-token count."""
    result: Dict[str, List[str]] = {}
    slugs = list(index.keys())
    for slug in slugs:
        src_tokens = index[slug]
        if not src_tokens:
            result[slug] = []
            continue
        scored = []
        for other in slugs:
            if other == slug:
                continue
            overlap = len(src_tokens & index[other])
            if overlap < _MIN_OVERLAP:
                continue
            # Tiebreaker: prefer articles with MORE tokens (longer titles
            # are usually more specific, not less — counterintuitive but
            # holds on this corpus).
            scored.append((overlap, len(index[other]), other))
        scored.sort(reverse=True)
        result[slug] = [s for _, _, s in scored[:k]]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually rewrite files (default: dry-run)")
    args = parser.parse_args()

    if not BLOG_DIR.exists():
        print(f"ERROR: {BLOG_DIR} not found", file=sys.stderr)
        return 1

    articles: Dict[str, Path] = {}
    for p in sorted(BLOG_DIR.iterdir()):
        if p.is_file() and p.suffix == ".html" and p.name not in SKIP:
            articles[p.stem] = p

    # Build token index + title index.
    tokens: Dict[str, Set[str]] = {}
    titles: Dict[str, str] = {}
    for slug, path in articles.items():
        html = path.read_text(encoding="utf-8")
        tokens[slug] = tokenize(slug)
        titles[slug] = extract_title(html, slug)

    related_map = compute_related(tokens)
    total = len(articles)
    with_links = sum(1 for v in related_map.values() if v)
    avg = (sum(len(v) for v in related_map.values()) / total) if total else 0
    orphans = [s for s, v in related_map.items() if not v]

    print(f"Articles scanned:     {total}")
    print(f"Articles with links:  {with_links}")
    print(f"Avg related / post:   {avg:.1f}")
    print(f"Orphans (no match):   {len(orphans)}")
    if orphans:
        for s in orphans[:5]:
            print(f"    - {s}")
        if len(orphans) > 5:
            print(f"    … and {len(orphans) - 5} more")

    if not args.apply:
        print("\nDRY RUN. To apply:  python scripts/add_internal_links.py --apply")
        return 0

    print("\nApplying...")
    updated = 0
    for slug, path in articles.items():
        html = path.read_text(encoding="utf-8")
        html = strip_existing_block(html)
        related = related_map.get(slug, [])
        if related:
            related_pairs = [(s, titles.get(s, s)) for s in related]
            block = build_related_html(slug, related_pairs)
            html, inserted = inject_before_footer(html, block)
            if inserted:
                path.write_text(html, encoding="utf-8")
                updated += 1
        else:
            # Orphan: still write back to strip any stale block.
            path.write_text(html, encoding="utf-8")
    print(f"Updated: {updated}/{total} articles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
