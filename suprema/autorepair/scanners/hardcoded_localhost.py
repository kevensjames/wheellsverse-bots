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


_DEV_CONDITIONAL_MARKERS = (
    "hostname === 'localhost'",
    'hostname === "localhost"',
    "hostname === '127.0.0.1'",
    'hostname === "127.0.0.1"',
    "process.env.NODE_ENV",
    "NODE_ENV !== 'production'",
    'NODE_ENV !== "production"',
    "if (dev)",
    "if (DEV)",
    "// dev only",
    "// DEV ONLY",
    "/* dev */",
)


def _is_dev_gated(lines: list[str], line_idx: int, window: int = 4) -> bool:
    """Look at the preceding `window` lines for a dev-mode conditional
    that would short-circuit this localhost reference in production."""
    lo = max(0, line_idx - window)
    ctx = "\n".join(lines[lo:line_idx + 1])
    return any(marker in ctx for marker in _DEV_CONDITIONAL_MARKERS)


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    findings: list[dict] = []
    for f in _candidate_files(project):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = content.splitlines()
        for m in LOCALHOST_RE.finditer(content):
            line = content[:m.start()].count("\n") + 1
            # Same-line dev marker (legacy check)
            line_text = lines[line - 1] if line - 1 < len(lines) else ""
            if "dev only" in line_text.lower() or "// dev" in line_text.lower():
                continue
            # Window check: was this reference made unreachable in prod by
            # a `hostname === 'localhost'` ternary or NODE_ENV guard above?
            if _is_dev_gated(lines, line - 1):
                continue
            findings.append({
                "severity": "medium",
                "location": f"{f.relative_to(project)}:{line}",
                "evidence": m.group(0)[:120],
                "fix_payload": {"file": str(f.relative_to(project)), "match": m.group(0)},
            })
    return findings
