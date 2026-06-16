"""Scan: api() helper called with a Fetch-style options bag when the file's
own api() helper expects a POSITIONAL method argument.

This repo has TWO api() conventions, so the malformed-ness is per-file, not
global:

  POSITIONAL  (e.g. dashboard/index.html):
      async function api(path, method='GET', body=null) { ... }
      RIGHT: api('/x', 'POST', {...})
      WRONG: api('/x', {method:'POST', body:JSON.stringify({...})})  ← object
             becomes the `method` arg → request silently malformed.

  OPTIONS-BAG (e.g. frontend/sol/*.html, frontend/admin/siteboost.html):
      async function api(path, opts={}) { fetch(API+path, {...opts}) }
      RIGHT: api('/x', {method:'POST', body:JSON.stringify({...})})  ← correct!
      (the object IS the fetch options; there is no positional method.)

An earlier version of this scanner assumed every helper was positional and
"fixed" the options-bag calls in the options-style files, silently breaking
24 admin/user actions in the Sol app (incl. the money-movement kill-switch).
So we now inspect each file's actual api() definition and ONLY flag a call
when that file's helper is positional. If the helper can't be found in the
file (imported/shared), we do NOT flag — refusing to rewrite an unknown
convention is far safer than corrupting it.
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

# Find the file's own api() DEFINITION and capture its 2nd parameter name.
# Handles: `function api(path, X`, `const api = (path, X`, `api = async (path, X`,
# `api = function(path, X`, `api: async function(path, X`, arrow + async variants.
# A definition has identifier params; a call has string/expr args — so this won't
# match call sites like api('/x', {...}) (first arg there is a quote, not an ident).
_API_DEF_RE = re.compile(
    r"(?:function\s+api|\bapi\s*[:=]\s*(?:async\s+)?(?:function\s*)?)"
    r"\s*\(\s*[A-Za-z_$][\w$]*\s*,\s*([A-Za-z_$][\w$]*)"
)


def _helper_is_positional(content: str) -> bool | None:
    """Inspect the file's api() helper signature.

    Returns:
        True  — positional convention: 2nd param is `method` → options-bag calls
                ARE malformed and should be flagged.
        False — options-bag convention: 2nd param is an options object (opts,
                options, o, cfg, init, …) → options-bag calls are CORRECT.
        None  — no api() definition found in this file (imported/shared helper);
                convention unknown → caller should NOT flag (don't risk a break).
    """
    m = _API_DEF_RE.search(content)
    if not m:
        return None
    second = m.group(1).lower()
    return second == "method" or second.startswith("method")


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
        # Only flag files whose OWN api() helper is positional. Options-style
        # and unknown-convention files are skipped — the previous global
        # assumption is exactly what broke the Sol frontend.
        if _helper_is_positional(content) is not True:
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
