"""Scan: FastAPI `add_event_handler` / `@app.on_event` usage.

Deprecated in FastAPI ≥ 0.93 in favor of the lifespan context-manager
pattern. Pattern from this session's build log:

    [WARNING] api: NarAI v2 briefing scheduler not registered:
              'FastAPI' object has no attribute 'add_event_handler'
    [WARNING] api: Insider promo scheduler not registered:
              'FastAPI' object has no attribute 'add_event_handler'
    [WARNING] api: Discord bot startup not registered:
              'FastAPI' object has no attribute 'add_event_handler'

In current FastAPI versions, this attribute IS still there but emits
DeprecationWarning. In some future version it'll be removed entirely.
Report-only — auto-rewriting startup hooks is risky."""

from __future__ import annotations

import re
from pathlib import Path

PATTERNS = (
    re.compile(r"""\.add_event_handler\(\s*["']([^"']+)["']"""),
    re.compile(r"""@app\.on_event\(\s*["']([^"']+)["']"""),
    re.compile(r"""@[\w_]+\.on_event\(\s*["']([^"']+)["']"""),
)


def _candidate_files(project: Path) -> list[Path]:
    out = []
    for root in ("core", "backend", "app", "src", "infra"):
        d = project / root
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            if any(x in str(p) for x in ("__pycache__", "/tests/", "_test.py")):
                continue
            out.append(p)
    return out


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    findings: list[dict] = []
    for f in _candidate_files(project):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for pat in PATTERNS:
            for m in pat.finditer(content):
                line = content[:m.start()].count("\n") + 1
                findings.append({
                    "severity": "low",
                    "location": f"{f.relative_to(project)}:{line}",
                    "evidence": f"event handler '{m.group(1)}' — migrate to lifespan",
                    "fix_payload": {"file": str(f.relative_to(project)),
                                    "event": m.group(1)},
                })
    return findings
