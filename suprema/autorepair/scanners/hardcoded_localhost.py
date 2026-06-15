r"""Scan: hardcoded localhost:NNNN references in deployed-frontend code.

Pattern from this session: `dashboard/index.html` had two `localhost:8000`
references — one fetch (`fetch('http://localhost:8000/health')`) and one
link (`href="http://localhost:8000/docs"`). Both worked in dev and silently
broke for every real user.

Detection: any `localhost:\d+` or `127\.0\.0\.1:\d+` substring in a file
under dashboard/, frontend/, admin/, src/. Severity: medium (silent UX
break, not security)."""

from __future__ import annotations

import re
from pathlib import Path

LOCALHOST_RE = re.compile(
    r"""(?:https?://)?(?:localhost|127\.0\.0\.1):\d+\b[/\w?&=.\-]*""",
)


def _candidate_files(project: Path) -> list[Path]:
    out = []
    for root in ("dashboard", "frontend", "admin", "src"):
        d = project / root
        if not d.is_dir():
            continue
        for ext in ("*.html", "*.js", "*.tsx", "*.ts", "*.jsx"):
            for p in d.rglob(ext):
                if any(x in str(p) for x in (
                    "/_archive/", "node_modules", "/dist/", "/build/",
                )):
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
        for m in LOCALHOST_RE.finditer(content):
            line = content[:m.start()].count("\n") + 1
            # Skip if the surrounding context says "dev only" or is inside a
            # comment marker the regex won't naturally consume.
            line_text = content.splitlines()[line - 1] if line - 1 < len(content.splitlines()) else ""
            if "dev only" in line_text.lower() or "// dev" in line_text.lower():
                continue
            findings.append({
                "severity": "medium",
                "location": f"{f.relative_to(project)}:{line}",
                "evidence": m.group(0)[:120],
                "fix_payload": {"file": str(f.relative_to(project)), "match": m.group(0)},
            })
    return findings
