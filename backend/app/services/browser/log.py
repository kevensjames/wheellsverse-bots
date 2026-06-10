"""Browser action log — append-only JSONL of every browser action (reads,
proposed writes, and blocked attempts). Powers the dashboard tab + gives a
visible record of what KAI did/looked-at/proposed. Mirrors the
failure_memory storage pattern (append-only, never raises).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# backend/app/services/browser/log.py → parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]

BROWSER_LOG_PATH = Path(
    os.environ.get(
        "KAI_BROWSER_LOG_PATH", str(_REPO_ROOT / "data" / "browser" / "actions.jsonl")
    )
)
BROWSER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

KINDS = ("navigate", "screenshot", "propose_write", "blocked")
STATUSES = ("ok", "blocked", "error")


@dataclass(slots=True)
class BrowserAction:
    ts: str
    kind: str            # navigate / screenshot / propose_write / blocked
    status: str          # ok / blocked / error
    url: str = ""
    detail: str = ""     # short human note (title, error, reason)
    proposed: dict[str, Any] | None = None  # for propose_write: the dry-run action


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_action(
    *,
    kind: str,
    status: str,
    url: str = "",
    detail: str = "",
    proposed: dict[str, Any] | None = None,
) -> BrowserAction:
    """Append one action record. NEVER raises — logging must not break a tool
    call or endpoint (fail-open, same posture as failure_memory)."""
    rec = BrowserAction(
        ts=_now(), kind=str(kind), status=str(status),
        url=url or "", detail=(detail or "")[:1000], proposed=proposed,
    )
    try:
        with BROWSER_LOG_PATH.open("a") as fp:
            fp.write(json.dumps(asdict(rec), default=str) + "\n")
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("browser.log: record_action swallowed: %s", e)
    return rec


def list_actions(limit: int = 50) -> list[dict[str, Any]]:
    """Recent actions, newest first."""
    if not BROWSER_LOG_PATH.exists():
        return []
    limit = max(1, min(int(limit), 1000))
    try:
        lines = BROWSER_LOG_PATH.read_text().splitlines()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("browser.log: read failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


def stats() -> dict[str, Any]:
    """Counts by kind + last navigated url, for the dashboard header."""
    actions = list_actions(limit=1000)
    by_kind: dict[str, int] = {}
    last_url = ""
    for a in actions:  # newest first
        k = a.get("kind", "?")
        by_kind[k] = by_kind.get(k, 0) + 1
        if not last_url and a.get("kind") == "navigate" and a.get("url"):
            last_url = a["url"]
    return {"total": len(actions), "by_kind": by_kind, "last_url": last_url}
