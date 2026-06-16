"""Scan: the daily-output system shows ZERO production where there should
be some (silent dead-system detector).

Why this matters: NarAI Daily Report shipped this format:
    📱 Posts: 0 created, 0 published
    🛍️ Products: 0 created, 0 published
    📚 Books: 0 written
    🔬 QC: 0 reviews, 0 fixes

The bot fleet reported itself as "Mission active" but produced *nothing*.
Most monitors alert on errors; this one alerts on the absence of expected
output — healthy-looking systems can be silently dead.

Strategy:
    - Look for a recent NarAI daily report or stats JSON in known locations:
        * <project>/data/narai_daily.json
        * <project>/data/narai_stats.json
        * <project>/outputs/reports/narai_daily_*.json
        * <project>/.omc/state/narai_daily.json
    - If found AND modified within last 36h AND all production counters
      are 0 → HIGH finding.
    - If no such file exists, we silently no-op (can't conclude anything).
    - This pattern is intentionally narrow: it ONLY fires when we have
      explicit evidence that the system *thinks* it's working but isn't
      producing. False-positive risk is low.

Read-only.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Keys we look at in the stats blob. We accept either flat counters or
# a nested {"posts": {"created": N, "published": M}} shape.
PRODUCTION_KEYS = (
    "posts_created", "posts_published",
    "products_created", "products_published",
    "books_written",
    "qc_reviews", "qc_fixes",
)

NESTED_KEYS = ("posts", "products", "books", "qc")


def _candidate_files(project: Path) -> list[Path]:
    candidates: list[Path] = []
    for p in (
        project / "data" / "narai_daily.json",
        project / "data" / "narai_stats.json",
        project / ".omc" / "state" / "narai_daily.json",
    ):
        if p.is_file():
            candidates.append(p)
    reports = project / "outputs" / "reports"
    if reports.is_dir():
        candidates.extend(sorted(reports.glob("narai_daily_*.json"))[-3:])
    return candidates


def _is_recent(p: Path, hours: int = 36) -> bool:
    try:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return False
    return datetime.now(timezone.utc) - mtime < timedelta(hours=hours)


def _all_zero(blob: dict) -> tuple[bool, dict]:
    """Returns (all_zero, observed_counters). Handles flat or nested keys."""
    observed: dict = {}
    for k in PRODUCTION_KEYS:
        if k in blob and isinstance(blob[k], (int, float)):
            observed[k] = blob[k]
    for k in NESTED_KEYS:
        v = blob.get(k)
        if isinstance(v, dict):
            for sub_k, sub_v in v.items():
                if isinstance(sub_v, (int, float)):
                    observed[f"{k}.{sub_k}"] = sub_v
    if not observed:
        return False, {}
    return all(v == 0 for v in observed.values()), observed


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    findings: list[dict] = []
    for f in _candidate_files(project):
        if not _is_recent(f):
            continue
        try:
            blob = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(blob, dict):
            continue

        all_zero, observed = _all_zero(blob)
        if not all_zero:
            continue

        # Single high-severity finding — investigate which agents stalled
        findings.append({
            "severity": "high",
            "location": str(f.relative_to(project)),
            "evidence": (f"NarAI daily report shows zero production: "
                         + ", ".join(f"{k}={v}" for k, v in observed.items())
                         + " — system reports as active but isn't producing."),
            "fix_payload": {
                "action": "investigate_productivity_dead_zone",
                "stats_file": str(f),
                "observed": observed,
            },
        })
        break  # one finding is enough — don't duplicate across candidate files

    return findings
