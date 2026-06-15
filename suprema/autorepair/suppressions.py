"""Suppress mechanism — operator-dismissed findings stay out of the panel
until the suppression is explicitly cleared.

Storage: `wheellsverse-bots/data/suprema-suppressions.json` — committed to
the repo so suppressions follow the project, not the machine.

Format:
  [
    {
      "pattern": "frontend_backend_diff",
      "project": "wheellsverse-bots",
      "location": "dashboard/index.html:9870",
      "reason": "dead UI feature, removing the frontend in v3",
      "suppressed_at": "2026-06-15T12:34:56Z",
      "suppressed_by": "operator"
    },
    ...
  ]

A finding is suppressed if (pattern, project, location) matches any entry.
The location is allowed to drift by ±5 lines so trivial edits above the
finding don't un-suppress it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Same path the panel + state-sync use — keeps everything in one place
SUPPRESSIONS_FILE = Path(
    "/Volumes/Wheellsverse/wheellsverse-bots/data/suprema-suppressions.json"
)


def _load_all() -> list[dict[str, Any]]:
    if not SUPPRESSIONS_FILE.is_file():
        return []
    try:
        data = json.loads(SUPPRESSIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_all(items: list[dict[str, Any]]) -> bool:
    try:
        SUPPRESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SUPPRESSIONS_FILE.write_text(json.dumps(items, indent=2))
        return True
    except Exception:
        return False


def _line_no(loc: str) -> int | None:
    m = re.search(r":(\d+)\s*$", loc or "")
    return int(m.group(1)) if m else None


def _file_only(loc: str) -> str:
    if ":" in (loc or ""):
        return loc.rsplit(":", 1)[0]
    return loc or ""


def is_suppressed(pattern: str, project: str, location: str,
                  fuzzy_lines: int = 5) -> bool:
    """Return True if any suppression matches this finding.

    Line numbers drift; we match on file with ±fuzzy_lines tolerance so a
    suppression survives small edits."""
    target_file = _file_only(location)
    target_line = _line_no(location)
    for entry in _load_all():
        if entry.get("pattern") != pattern:
            continue
        if entry.get("project") != project:
            continue
        entry_loc = entry.get("location", "")
        if entry_loc == location:
            return True
        if _file_only(entry_loc) == target_file:
            el = _line_no(entry_loc)
            if el is not None and target_line is not None:
                if abs(el - target_line) <= fuzzy_lines:
                    return True
            elif el is None and target_line is None:
                return True
    return False


def add(pattern: str, project: str, location: str,
        reason: str = "", suppressed_by: str = "operator") -> dict[str, Any]:
    """Add a suppression. Idempotent — if already suppressed, returns the
    existing entry without duplicating."""
    items = _load_all()
    for existing in items:
        if (existing.get("pattern") == pattern
                and existing.get("project") == project
                and existing.get("location") == location):
            return {"status": "already_suppressed", "entry": existing}
    new_entry = {
        "pattern": pattern,
        "project": project,
        "location": location,
        "reason": reason or "(no reason given)",
        "suppressed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "suppressed_by": suppressed_by,
    }
    items.append(new_entry)
    if not _save_all(items):
        return {"status": "error", "message": "could not write suppressions file"}
    return {"status": "ok", "entry": new_entry, "total": len(items)}


def remove(pattern: str, project: str, location: str) -> dict[str, Any]:
    """Clear a suppression. Returns the removed entry or status."""
    items = _load_all()
    kept = [e for e in items
            if not (e.get("pattern") == pattern
                    and e.get("project") == project
                    and e.get("location") == location)]
    if len(kept) == len(items):
        return {"status": "not_found"}
    if not _save_all(kept):
        return {"status": "error", "message": "could not write suppressions file"}
    return {"status": "ok", "removed": len(items) - len(kept), "remaining": len(kept)}


def list_all() -> list[dict[str, Any]]:
    return _load_all()


def filter_findings(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]],
                                                              list[dict[str, Any]]]:
    """Split findings into (visible, hidden). Used by run_cycle to exclude
    suppressed items from the panel without losing them entirely — they
    still appear in `hidden` so the operator can review what's been
    dismissed."""
    visible, hidden = [], []
    for f in findings:
        if is_suppressed(
            f.get("pattern", ""), f.get("project", ""), f.get("location", "")
        ):
            hidden.append(f)
        else:
            visible.append(f)
    return visible, hidden
