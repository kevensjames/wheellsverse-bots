#!/usr/bin/env python3
"""
scripts/migrate_blog_slugs.py
─────────────────────────────────────────────────────────────────────────────
Migrate blog filenames from `{YYYYMMDD}-{slug}.html` to clean `{slug}.html`
and generate a 301 redirect map so old URLs keep working.

WHY THIS EXISTS
    The publisher was writing files as `20260326-my-post.html` but telling
    users the live URL was `/blog/my-post.html`. Every shared link 404'd.
    We're standardizing on clean slugs for SEO + shareability, and 301'ing
    every old URL to its new home so nothing in search results or social
    posts breaks.

COLLISION POLICY
    When 2+ files collapse to the same clean slug (the dataset has several
    cases of re-published articles with different date prefixes), the file
    with the newest date prefix wins. Files without a date prefix are
    treated as the newest. All losers get 301'd to the winner.

USAGE
    # dry-run (default) — shows the plan, changes nothing:
    python scripts/migrate_blog_slugs.py

    # apply — actually rename files and write _redirects + sitemap:
    python scripts/migrate_blog_slugs.py --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
BLOG_DIR = ROOT / "frontend" / "blog"
ARCHIVE_DIR = ROOT / "frontend" / "blog" / "_archive"
SITEMAP = ROOT / "frontend" / "sitemap.xml"
REDIRECTS = ROOT / "frontend" / "_redirects"
BLOG_INDEX = ROOT / "frontend" / "blog" / "index.html"
SITE_BASE = "https://wheellsverse.com"

# Files we never touch — these aren't articles, and _archive/ is a subdir
# we created ourselves so it must never be re-processed.
SKIP = {"index.html", "_archive"}

DATE_PREFIX_RE = re.compile(r"^(\d{8})-(.+\.html)$")


def clean_slug(filename: str) -> Tuple[str, str]:
    """
    Split a filename into (date_prefix, clean_filename).

    Examples:
        '20260326-foo.html' -> ('20260326', 'foo.html')
        'foo.html'          -> ('',         'foo.html')
    """
    m = DATE_PREFIX_RE.match(filename)
    if m:
        return m.group(1), m.group(2)
    return "", filename


def build_plan() -> Tuple[Dict[str, str], List[Tuple[str, str]]]:
    """
    Walk BLOG_DIR, group by clean slug, pick winners.

    Returns:
        renames:   {old_filename: new_filename} — files to rename in place
        redirects: [(old_url, new_url), ...] — 301 entries to add
    """
    if not BLOG_DIR.exists():
        print(f"ERROR: {BLOG_DIR} does not exist", file=sys.stderr)
        sys.exit(1)

    # Group every file by its clean slug.
    groups: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for p in sorted(BLOG_DIR.iterdir()):
        if not p.is_file() or not p.name.endswith(".html") or p.name in SKIP:
            continue
        date, clean = clean_slug(p.name)
        groups[clean].append((date, p.name))

    renames: Dict[str, str] = {}
    redirects: List[Tuple[str, str]] = []

    for clean_name, items in groups.items():
        # Winner: highest date prefix (empty prefix sorts last = treated as
        # newest, which matches intent: manually-fixed files already use
        # clean slugs and should be preserved).
        items_sorted = sorted(
            items,
            key=lambda dn: (dn[0] or "99999999"),
            reverse=True,
        )
        winner_date, winner_name = items_sorted[0]
        losers = items_sorted[1:]

        # Winner: rename to clean_name if it has a date prefix.
        if winner_name != clean_name:
            renames[winner_name] = clean_name
            redirects.append((f"/blog/{winner_name}", f"/blog/{clean_name}"))

        # Losers: delete (they're stale duplicates) + 301 to the canonical.
        for _, loser in losers:
            renames[loser] = None  # None = delete
            redirects.append((f"/blog/{loser}", f"/blog/{clean_name}"))

        # Also redirect the bare slug (no .html) form, since the FastAPI route
        # accepts both; this way anything that links without the extension
        # also gets a proper 301 to the canonical.
        # (We don't need an entry for the winner's new path — that's the target.)

    return renames, redirects


def apply_renames(renames: Dict[str, str]) -> None:
    """Rename winners, archive losers.

    Losers move to frontend/blog/_archive/ rather than being deleted, so
    the content is recoverable if we later find a wrongly-merged pair
    (e.g. two distinct articles whose slugs collided at the 60-char
    truncation boundary). The FastAPI /blog/{slug} route only looks at
    files directly inside frontend/blog/, so archived files are not
    publicly reachable — the 301 redirects still point at the canonical
    winner.
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for old, new in renames.items():
        old_p = BLOG_DIR / old
        if new is None:
            if old_p.exists():
                dest = ARCHIVE_DIR / old
                # If we've run the migration before, a prior loser may
                # already exist in the archive — don't clobber, rename
                # with a numeric suffix.
                if dest.exists():
                    i = 2
                    while (ARCHIVE_DIR / f"{dest.stem}-{i}{dest.suffix}").exists():
                        i += 1
                    dest = ARCHIVE_DIR / f"{dest.stem}-{i}{dest.suffix}"
                old_p.rename(dest)
                print(f"  archived {old}  →  _archive/{dest.name}")
            continue
        new_p = BLOG_DIR / new
        if new_p.exists() and new_p != old_p:
            # Shouldn't happen given group-by-winner logic, but be defensive.
            print(f"  SKIP {old} → {new} (target already exists)")
            continue
        old_p.rename(new_p)
        print(f"  renamed  {old} → {new}")


def write_redirects(redirects: List[Tuple[str, str]]) -> None:
    """Append blog redirects to frontend/_redirects, preserving existing lines."""
    header = "# --- Blog slug migration (auto-generated, do not hand-edit) ---"
    footer = "# --- end blog slug migration ---"

    existing = REDIRECTS.read_text() if REDIRECTS.exists() else ""
    # Strip any prior auto-generated block so re-running is idempotent.
    if header in existing:
        pre, _, rest = existing.partition(header)
        _, _, post = rest.partition(footer)
        existing = pre.rstrip() + post.lstrip()

    lines = [header]
    lines.append(f"# generated {datetime.utcnow().isoformat()}Z")
    for old_path, new_path in sorted(set(redirects)):
        # Netlify / Cloudflare Pages format: from  to  status
        lines.append(f"{old_path:<80} {new_path:<60} 301")
    lines.append(footer)

    new_content = existing.rstrip() + "\n\n" + "\n".join(lines) + "\n"
    REDIRECTS.write_text(new_content)
    print(f"  wrote    {REDIRECTS.relative_to(ROOT)} (+{len(redirects)} entries)")


def regenerate_sitemap() -> None:
    """Rebuild sitemap.xml with clean-slug URLs only, newest first."""
    entries = []
    for p in sorted(BLOG_DIR.iterdir()):
        if not p.is_file() or not p.name.endswith(".html") or p.name in SKIP:
            continue
        slug = p.stem  # filename without .html
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
        entries.append((mtime, slug))
    entries.sort(reverse=True)  # newest first

    today = datetime.utcnow().strftime("%Y-%m-%d")
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml.append(f'  <url><loc>{SITE_BASE}/</loc><changefreq>daily</changefreq>'
               f'<priority>1.0</priority><lastmod>{today}</lastmod></url>')
    xml.append(f'  <url><loc>{SITE_BASE}/blog/</loc><changefreq>daily</changefreq>'
               f'<priority>0.9</priority><lastmod>{today}</lastmod></url>')
    for mtime, slug in entries:
        xml.append(f'  <url><loc>{SITE_BASE}/blog/{slug}</loc>'
                   f'<changefreq>weekly</changefreq><priority>0.8</priority>'
                   f'<lastmod>{mtime}</lastmod></url>')
    xml.append('</urlset>')

    SITEMAP.write_text("\n".join(xml) + "\n")
    print(f"  wrote    {SITEMAP.relative_to(ROOT)} ({len(entries)} articles)")


def update_blog_index() -> None:
    """Rewrite the blog/index.html links from old filenames to clean slugs.

    Only touches href="..." values — leaves text content alone. Safe no-op
    if the file doesn't reference old-style URLs.
    """
    if not BLOG_INDEX.exists():
        return
    html = BLOG_INDEX.read_text()
    changed = 0

    def fix(match: re.Match) -> str:
        nonlocal changed
        url = match.group(1)
        # Only rewrite if it looks like a blog/YYYYMMDD- URL
        m = re.search(r"/blog/(\d{8}-[^\"'>\s]+\.html)", url)
        if not m:
            return match.group(0)
        old_name = m.group(1)
        _, clean = clean_slug(old_name)
        new_url = url.replace(old_name, clean.replace(".html", ""))
        changed += 1
        return f'href="{new_url}"'

    new_html = re.sub(r'href="([^"]+)"', fix, html)
    if changed:
        BLOG_INDEX.write_text(new_html)
        print(f"  updated  blog/index.html ({changed} links rewritten)")


def print_plan(renames: Dict[str, str], redirects: List[Tuple[str, str]]) -> None:
    to_rename = {k: v for k, v in renames.items() if v is not None}
    to_archive = [k for k, v in renames.items() if v is None]

    print("=" * 72)
    print("BLOG SLUG MIGRATION — DRY RUN")
    print("=" * 72)
    print(f"Files to RENAME (winner gets clean slug): {len(to_rename)}")
    for old, new in sorted(to_rename.items())[:10]:
        print(f"    {old}  →  {new}")
    if len(to_rename) > 10:
        print(f"    … and {len(to_rename) - 10} more")

    print(f"\nFiles to ARCHIVE → frontend/blog/_archive/ (older duplicate of a winner): {len(to_archive)}")
    for name in sorted(to_archive)[:10]:
        print(f"    {name}")
    if len(to_archive) > 10:
        print(f"    … and {len(to_archive) - 10} more")

    print(f"\n301 REDIRECT entries to emit: {len(redirects)}")
    print(f"    (ensures every old URL — in social posts, search index, email")
    print(f"     blasts — lands on the new canonical slug)")
    print()
    print(f"Sitemap: will regenerate with clean-slug URLs")
    print(f"Blog index: will rewrite href values to clean slugs")
    print()
    print("To apply:  python scripts/migrate_blog_slugs.py --apply")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually perform the migration (default: dry-run)")
    args = parser.parse_args()

    renames, redirects = build_plan()

    if not args.apply:
        print_plan(renames, redirects)
        return 0

    print("Applying migration...")
    apply_renames(renames)
    write_redirects(redirects)
    regenerate_sitemap()
    update_blog_index()
    print("\n✅ Migration complete.")
    print("   Next: commit + push so Cloudflare/Railway serves the new state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
