"""Catch broken /go/<slug> references before they ship to production.

The /go/<partner> redirector in core/api.py looks up `partner` in
core.click_tracker._affiliate_urls(). Any slug used in code, bots, or
frontend HTML that isn't registered will 404 in production.

This test scans the tree and asserts every distinct slug is registered.
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


def _registered_slugs() -> set[str]:
    """Reflect on click_tracker._affiliate_urls() so the test follows the source of truth."""
    from core.click_tracker import _affiliate_urls
    return set(_affiliate_urls().keys())


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
def test_slug_is_registered(slug: str) -> None:
    registered = _registered_slugs()
    if slug not in registered:
        sample = USED[slug][0].relative_to(ROOT)
        more = f" (+{len(USED[slug]) - 1} more)" if len(USED[slug]) > 1 else ""
        pytest.fail(
            f"/go/{slug} is referenced (e.g. {sample}{more}) but not registered "
            f"in core.click_tracker._affiliate_urls(). It will 404 in production."
        )


def test_some_slugs_were_discovered() -> None:
    """Guard against the grep silently finding nothing."""
    assert USED, "no /go/<slug> references found — did the search dirs change?"
