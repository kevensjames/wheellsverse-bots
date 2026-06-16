"""Scan: /favicon.ico (or /favicon.svg) returns 404 on the live URL.

Browser auto-requests /favicon.ico on every page load — 404 shows in DevTools
and clutters logs. Fix is a static SVG + a 4-line route."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path


def _probe(url: str, timeout: float = 5.0) -> int:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            return r.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    if not live_url:
        return []

    findings: list[dict] = []
    for path in ("/favicon.ico", "/favicon.svg"):
        # Skip if a local file is staged for this path (likely already fixed)
        if (project / "frontend" / path.lstrip("/")).exists():
            continue
        status = _probe(live_url + path)
        if status == 200:
            continue
        if status == 0:
            continue  # unreachable origin; don't lie
        findings.append({
            "severity": "low",
            "location": "(production HTTP probe)",
            "evidence": f"GET {live_url}{path} → HTTP {status}",
            "fix_payload": {"favicon_path": path},
        })
    return findings
