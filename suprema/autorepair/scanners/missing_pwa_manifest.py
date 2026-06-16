"""Scan: HTML refs <link rel="manifest"> but the path 404s.

Detects a class of bug that produced 6 console errors per /admin load
for ~30 days. Cheap fix: drop a 200-byte JSON file + a single FastAPI
route.

Detection strategy:
    1. Find HTML files in the project that have <link rel="manifest" href="...">
    2. For each unique manifest path referenced, probe it (locally first,
       then live URL if provided)
    3. If 404, emit Finding with fix_payload={"manifest_path": "/manifest.json"}
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path

LINK_RE = re.compile(
    r'<link\s+rel=["\']manifest["\']\s+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _html_files(project: Path) -> list[Path]:
    candidates = []
    for root in ("dashboard", "frontend", "admin", "src"):
        d = project / root
        if not d.is_dir():
            continue
        for p in d.rglob("*.html"):
            # Skip archives/backups
            s = str(p)
            if any(x in s for x in ("/_archive/", ".backup", "node_modules")):
                continue
            candidates.append(p)
    return candidates


def _probe(url: str, timeout: float = 5.0) -> int:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0  # unreachable


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    findings: list[dict] = []
    seen_paths: set[str] = set()

    for html in _html_files(project):
        try:
            content = html.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in LINK_RE.finditer(content):
            href = m.group(1)
            if not href.startswith("/"):
                continue  # CDN URL, skip
            if href in seen_paths:
                continue
            seen_paths.add(href)

            # Local check first: is there a file at frontend/<href>?
            local_target = project / "frontend" / href.lstrip("/")
            if local_target.exists():
                continue

            # Live probe if URL is given
            status = 0
            if live_url:
                status = _probe(live_url + href)
            if status == 200:
                continue

            findings.append({
                "severity": "medium",
                "location": f"{html.relative_to(project)}:{content[:m.start()].count(chr(10)) + 1}",
                "evidence": f'<link rel="manifest" href="{href}"> → '
                            f'{"HTTP " + str(status) if status else "local file missing"}',
                "fix_payload": {"manifest_path": href},
            })

    return findings
