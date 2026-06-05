#!/usr/bin/env python3
"""Re-stamp ?v=... cache-busters in static HTML based on each asset's mtime.

Why this exists
---------------
We had the bug: I'd ship new JS to chat.js but forget to bump
<script src="chat.js?v=20260604a"> to a new version on chat.html. Browsers
kept using the cached old JS while the new HTML referenced new IDs/handlers.
Result: the cancel survey form's submit handler silently didn't attach, and
the form fell back to a default GET submission.

This script makes that class of bug impossible by tying the version stamp
to the actual file's mtime. Run it after any static-asset edit:

    python scripts/stamp_static_assets.py

Or wire it into the launchd wrapper (deploy/start_nai.sh) so every daemon
restart re-stamps.

Behavior
--------
- Scans backend/app/static/nai/*.html
- For each <script src="X.js?v=Y"> and <link href="X.css?v=Y">:
    look up X's mtime → format as "ts-<unix>"
    replace ?v=Y with ?v=ts-<unix>
- Idempotent (running twice with no file changes is a no-op)
- Prints a one-line summary of how many refs were updated

This does NOT touch external URLs (https://...) or non-versioned refs.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
STATIC_DIR = ROOT / "backend" / "app" / "static" / "nai"

# Match  src="filename.ext?v=anything"  OR  href="filename.ext?v=anything"
# Keep the quote style for the replacement.
ASSET_REF_RE = re.compile(
    r"""(?P<attr>src|href)=(?P<q>["'])"""
    r"""(?P<file>[\w./-]+?\.(?:js|css|png|jpg|jpeg|gif|svg|webp))"""
    r"""\?v=[\w.-]+"""
    r"""(?P=q)"""
)


def stamp_html(html_path: Path) -> int:
    text = html_path.read_text()
    replacements = 0

    def _replace(m: re.Match) -> str:
        nonlocal replacements
        attr = m.group("attr")
        q = m.group("q")
        rel = m.group("file")
        # Resolve the asset path relative to the HTML file
        asset_path = (html_path.parent / rel).resolve()
        if not asset_path.exists():
            # Unknown asset — leave the ref alone rather than break it
            return m.group(0)
        mtime = int(asset_path.stat().st_mtime)
        replacements += 1
        return f'{attr}={q}{rel}?v=ts-{mtime}{q}'

    new_text = ASSET_REF_RE.sub(_replace, text)
    if new_text != text:
        html_path.write_text(new_text)
    return replacements


def main() -> int:
    if not STATIC_DIR.exists():
        print(f"FATAL: {STATIC_DIR} not found", file=sys.stderr)
        return 2

    total_files = 0
    total_refs = 0
    for html in sorted(STATIC_DIR.glob("*.html")):
        n = stamp_html(html)
        if n:
            print(f"  {html.name}  {n} ref{'s' if n != 1 else ''}")
            total_files += 1
            total_refs += n

    if total_refs == 0:
        print("  (no changes — all stamps already match file mtimes)")
    else:
        print(f"\nStamped {total_refs} refs across {total_files} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
