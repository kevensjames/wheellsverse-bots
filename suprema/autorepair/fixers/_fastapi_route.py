"""Helper: insert a FastAPI route into the project's main api.py if it
detects the FastAPI convention. Idempotent — if the route already exists,
returns without changes.

Used by the static-asset fixers (manifest, sw, favicon) and any future
fixer that needs to mount a new route.

Tries main api file in order: core/api.py, app/main.py, backend/main.py.
Returns (file_path, was_inserted). If was_inserted is False, the route was
already present (idempotent skip) OR the file didn't exist (caller decides).
"""

from __future__ import annotations

import re
from pathlib import Path


def find_main_api(project: Path) -> Path | None:
    for candidate in (
        project / "core" / "api.py",
        project / "app" / "main.py",
        project / "backend" / "main.py",
        project / "main.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def route_exists(api_file: Path, path: str, method: str = "get") -> bool:
    try:
        content = api_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    pat = re.compile(
        rf"""@app\.{method.lower()}\(\s*["']{re.escape(path)}["']""",
        re.IGNORECASE,
    )
    return bool(pat.search(content))


def insert_route_after_anchor(
    api_file: Path,
    route_block: str,
    anchor_pattern: str = r"@app\.get\(\s*[\"']/robots\.txt[\"']\)",
) -> bool:
    """Insert route_block after the end of the handler that matches
    anchor_pattern. The anchor is conventional — /robots.txt is a small
    static-asset route in many of our projects."""
    try:
        content = api_file.read_text(encoding="utf-8")
    except Exception:
        return False

    m = re.search(anchor_pattern, content)
    if not m:
        # Fallback: append to file before the last blank line
        new = content.rstrip() + "\n\n\n" + route_block.lstrip() + "\n"
        api_file.write_text(new, encoding="utf-8")
        return True

    # Find end of the matched handler — heuristic: the next two consecutive
    # blank lines after the anchor's line.
    start = m.start()
    tail = content[start:]
    end_match = re.search(r"\n\n\n", tail)
    if not end_match:
        # Just append after first run of two newlines
        end_match = re.search(r"\n\n", tail)
    if not end_match:
        new = content.rstrip() + "\n\n\n" + route_block.lstrip() + "\n"
        api_file.write_text(new, encoding="utf-8")
        return True

    insert_at = start + end_match.end()
    new = content[:insert_at] + route_block.lstrip() + "\n\n" + content[insert_at:]
    api_file.write_text(new, encoding="utf-8")
    return True
