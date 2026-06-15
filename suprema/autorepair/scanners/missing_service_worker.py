"""Scan: JS registers `navigator.serviceWorker.register('/sw.js')` but path 404s.

Silent failure because the registration is usually wrapped in `.catch(() => {})`.
Found in production for ~30 days before this scanner existed."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path

SW_REG_RE = re.compile(
    r"""navigator\.serviceWorker\.register\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def _html_and_js(project: Path) -> list[Path]:
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


def _probe(url: str, timeout: float = 5.0) -> int:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
            return r.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    findings: list[dict] = []
    seen: set[str] = set()

    for f in _html_and_js(project):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in SW_REG_RE.finditer(content):
            sw_path = m.group(1)
            if not sw_path.startswith("/"):
                continue
            if sw_path in seen:
                continue
            seen.add(sw_path)

            local_target = project / "frontend" / sw_path.lstrip("/")
            if local_target.exists():
                continue

            status = _probe(live_url + sw_path) if live_url else 0
            if status == 200:
                continue

            findings.append({
                "severity": "low",
                "location": f"{f.relative_to(project)}:{content[:m.start()].count(chr(10)) + 1}",
                "evidence": f"register('{sw_path}') → "
                            f"{'HTTP ' + str(status) if status else 'local file missing'}",
                "fix_payload": {"sw_path": sw_path},
            })

    return findings
