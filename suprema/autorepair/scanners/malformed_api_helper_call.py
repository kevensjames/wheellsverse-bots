"""Scan: api() helper called with a Fetch-style options bag instead of positional method.

Project convention (in dashboard/index.html ~L6586):
    async function api(path, method='GET', body=null) { ... }

WRONG (silently fails because the object becomes method=):
    api('/api/foo', {method:'POST', body:JSON.stringify({...})})

RIGHT:
    api('/api/foo', 'POST', {...})

This bug landed in dashboard/index.html twice in this codebase before
this scanner existed, and the buttons that used the malformed call
silently did nothing for the user.
"""

from __future__ import annotations

import re
from pathlib import Path

# Match: api( ANY , { method : ... } )
# CASE-SENSITIVE: only lowercase `api(` to avoid touching unrelated helpers
# named Api(), API(), etc. that may have different signatures.
PATTERN = re.compile(
    r"""\bapi\(\s*(['"`][^'"`]+['"`])\s*,\s*\{\s*method\s*:\s*['"](GET|POST|PUT|DELETE|PATCH)['"]"""
    r"""(?:\s*,\s*body\s*:\s*JSON\.stringify\((\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})\))?\s*\}\s*\)""",
)


def _candidate_files(project: Path) -> list[Path]:
    out = []
    for root in ("dashboard", "frontend", "admin", "src"):
        d = project / root
        if not d.is_dir():
            continue
        for ext in ("*.html", "*.js"):
            for p in d.rglob(ext):
                if any(x in str(p) for x in ("/_archive/", "node_modules")):
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
        for m in PATTERN.finditer(content):
            line_no = content[:m.start()].count("\n") + 1
            findings.append({
                "severity": "high",
                "location": f"{f.relative_to(project)}:{line_no}",
                "evidence": m.group(0)[:180],
                "fix_payload": {
                    "file": str(f.relative_to(project)),
                    "match_start": m.start(),
                    "match_end": m.end(),
                    "url_literal": m.group(1),
                    "method": m.group(2).upper(),
                    "body_literal": m.group(3) or "",
                },
            })
    return findings
