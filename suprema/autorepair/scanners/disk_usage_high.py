"""Scan: host disk is filling up.

Why this matters: KAI Supreme on the Mac mini was reporting "Disk 82% full"
for days before SUPREMA noticed — because SUPREMA only inspected code, not
runtime state. Once the APFS container hits ~90% the mini starts evicting
caches, Gitea slows, Playwright Chromium downloads fail, and bots crash with
no-space errors that look like config bugs. We want this in the panel.

Strategy:
    - Probe the disk that holds the project working tree (whichever volume
      `project_path` lives on). On the Mac mini this is `/`; on the
      external SSD it's `/Volumes/Wheellsverse`.
    - HIGH if >=85% used. MEDIUM if >=75%. Otherwise silent.
    - Fire only ONCE per cycle (gate on the first project we see) — disk
      state is host-global, not per-project, and duplicate findings would
      just clutter the panel.

This scanner is read-only and never writes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Gate so we only emit a single finding per cycle even though the engine
# walks N projects. The first project to call us wins; the rest no-op.
_FIRED_THIS_CYCLE: dict[str, bool] = {}


def _percent_used(total: int, free: int) -> int:
    if total <= 0:
        return 0
    return round((total - free) / total * 100)


def _format_gb(n: int) -> str:
    return f"{n / (1024**3):.1f} GB"


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    # Host-global signal — only fire once per cycle
    if _FIRED_THIS_CYCLE.get("done"):
        return []
    _FIRED_THIS_CYCLE["done"] = True

    try:
        usage = shutil.disk_usage(str(project))
    except Exception as e:
        return [{
            "severity": "low",
            "location": str(project),
            "evidence": f"could not stat disk: {e}",
            "fix_payload": {"action": "investigate"},
        }]

    pct = _percent_used(usage.total, usage.free)
    free_h = _format_gb(usage.free)
    total_h = _format_gb(usage.total)
    loc = f"{project}  ({total_h} total)"

    if pct >= 85:
        return [{
            "severity": "high",
            "location": loc,
            "evidence": f"Disk {pct}% full — {free_h} free of {total_h}. "
                        "Cleanup recommended: __pycache__, old logs, archived outputs.",
            "fix_payload": {
                "action": "cleanup_disk",
                "percent_used": pct,
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "recipe": (
                    "find ~ -type d -name __pycache__ -exec rm -rf {} +;  "
                    "find ~/wheellsverse_bots/logs -name '*.log' -mtime +30 -delete;  "
                    "find ~/Library/Caches -mtime +60 -delete"
                ),
            },
        }]

    if pct >= 75:
        return [{
            "severity": "medium",
            "location": loc,
            "evidence": f"Disk {pct}% full — {free_h} free of {total_h}. "
                        "Headroom shrinking; consider proactive cleanup.",
            "fix_payload": {
                "action": "cleanup_disk_optional",
                "percent_used": pct,
                "free_bytes": usage.free,
            },
        }]

    return []
