"""Read-side helpers for KAI Supreme proposals.

The scanner writes scan-*.json files to PROPOSALS_DIR. These helpers let
the admin endpoints surface them without each route re-implementing the
glob/sort/parse dance.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.supreme.scanner import PROPOSALS_DIR

logger = logging.getLogger(__name__)


def list_proposals(limit: int = 50) -> list[dict[str, Any]]:
    """Return proposal metadata (no full findings) most-recent-first.

    Used by the admin history endpoint — listing 100 proposals shouldn't
    pay the cost of loading every finding into memory.
    """
    if not PROPOSALS_DIR.exists():
        return []
    files = sorted(
        PROPOSALS_DIR.glob("scan-*.json"),
        key=lambda p: p.name,
        reverse=True,
    )[:max(1, min(int(limit), 500))]

    out: list[dict[str, Any]] = []
    for p in files:
        try:
            data = json.loads(p.read_text())
        except Exception as e:
            logger.warning("supreme: skipping bad proposal %s: %s", p.name, e)
            continue
        out.append({
            "name": p.name,
            "scanned_at": data.get("scanned_at"),
            "finding_count": data.get("finding_count", 0),
            "severity_counts": data.get("severity_counts", {}),
        })
    return out


def read_proposal(name: str) -> dict[str, Any] | None:
    """Load one proposal in full (with all findings). Returns None if not
    found or unreadable. Name is the basename (e.g. scan-20260609T...Z.json)
    — we deliberately reject path separators to keep this from escaping
    PROPOSALS_DIR.
    """
    if "/" in name or "\\" in name or ".." in name or not name.startswith("scan-"):
        return None
    p = PROPOSALS_DIR / name
    if not p.exists() or not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:
        logger.warning("supreme: could not read proposal %s: %s", name, e)
        return None


def latest_proposals(n: int = 1) -> list[dict[str, Any]]:
    """The N most recent proposals in full. Used by the dashboard's main
    'last scan' panel and the API consumer that wants the freshest finding
    set without hitting a separate detail endpoint."""
    if not PROPOSALS_DIR.exists():
        return []
    files = sorted(
        PROPOSALS_DIR.glob("scan-*.json"),
        key=lambda p: p.name,
        reverse=True,
    )[:max(1, n)]
    out: list[dict[str, Any]] = []
    for p in files:
        try:
            out.append(json.loads(p.read_text()))
        except Exception as e:
            logger.warning("supreme: skipping bad proposal %s: %s", p.name, e)
    return out
