"""Catch broken /go/<slug> references before they ship to production.

The /go/<partner> redirector in core/api.py looks up `partner` in
core.click_tracker._resolve_destination(). Any slug used in code, bots, or
frontend HTML that isn't registered will 404 in production.

This test scans the tree and asserts every distinct slug RESOLVES to a destination.
(It formerly asserted registry membership; see _resolves() for why that changed.)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = ("core", "bots", "frontend", "narai")
SLUG_RE = re.compile(r"/go/([a-zA-Z0-9_-]+)")

# Slugs that look like /go/<x> but are NOT real affiliate redirector hits —
# template placeholders or unrelated routes.
TEMPLATE_PLACEHOLDERS = {
    "partner",   # /go/{partner} route definition
    "slug",      # template variables
}


def _resolves(slug: str) -> bool:
    """Whether click_tracker can turn this slug into a destination URL.

    This used to reflect on _affiliate_urls().keys(), because a slug that was not a key of that map
    really would 404. Commit a0e6cfa1 changed the design: _affiliate_urls() is now env-backed for the
    single owned-funnel key 'insider', and _resolve_destination() resolves EVERY other partner key on
    demand to the digital-product URL with utm_content set. So the failure this test was written to
    catch can no longer happen, and the old assertion failed on 16 perfectly working slugs.

    The invariant that still matters is the one the redirect actually depends on: every referenced
    slug must resolve to a non-empty destination. That is what is asserted now.
    """
    from core.click_tracker import _resolve_destination
    try:
        return bool(_resolve_destination(slug))
    except Exception:
        return False


EXCLUDE_DIR_NAMES = {".venv", "venv", "node_modules", "__pycache__", ".git", "_archive"}


def _used_slugs() -> dict[str, list[Path]]:
    """Find every /go/<slug> reference in the tree, mapping slug → list of files."""
    used: dict[str, list[Path]] = {}
    cmd = [
        "grep",
        "-rEH",
        *[f"--exclude-dir={d}" for d in EXCLUDE_DIR_NAMES],
        r"/go/[a-zA-Z0-9_-]+",
        *(str(ROOT / d) for d in SEARCH_DIRS if (ROOT / d).exists()),
    ]
    try:
        out = subprocess.check_output(cmd, text=True, errors="ignore")
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return {}
        raise

    for line in out.splitlines():
        path_part, sep, _ = line.partition(":")
        if not sep:
            continue
        for m in SLUG_RE.finditer(line):
            slug = m.group(1).lower()
            if slug in TEMPLATE_PLACEHOLDERS:
                continue
            used.setdefault(slug, []).append(Path(path_part))
    return used


USED = _used_slugs()


@pytest.mark.parametrize("slug", sorted(USED.keys()))
def test_slug_resolves_to_a_destination(slug: str) -> None:
    if not _resolves(slug):
        sample = USED[slug][0].relative_to(ROOT)
        more = f" (+{len(USED[slug]) - 1} more)" if len(USED[slug]) > 1 else ""
        pytest.fail(
            f"/go/{slug} is referenced (e.g. {sample}{more}) but "
            f"core.click_tracker._resolve_destination() returns nothing for it — "
            f"the redirect would have no destination."
        )


def test_some_slugs_were_discovered() -> None:
    """Guard against the grep silently finding nothing."""
    assert USED, "no /go/<slug> references found — did the search dirs change?"
