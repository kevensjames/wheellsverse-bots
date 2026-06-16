"""Auto-safe fixer for malformed_api_helper_call.

Rewrites:
    api('/api/foo', {method:'POST', body:JSON.stringify({k:v})})
into:
    api('/api/foo', 'POST', {k:v})

Per the wheellsverse-bots api() helper convention:
    async function api(path, method='GET', body=null) { ... }

Only rewrites bodies that are literal {...} object expressions inside the
JSON.stringify call. If the body is a variable reference (e.g. `body:JSON.stringify(payload)`),
the fixer leaves it for human review (would otherwise lose the variable
binding)."""

from __future__ import annotations

import re
from pathlib import Path

from suprema.autorepair.engine import FixResult

# Same regex as the scanner — captures path, method, optional inline-object body
PATTERN = re.compile(
    r"""\bapi\(\s*(['"`][^'"`]+['"`])\s*,\s*\{\s*method\s*:\s*['"](GET|POST|PUT|DELETE|PATCH)['"]"""
    r"""(?:\s*,\s*body\s*:\s*JSON\.stringify\((\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})\))?\s*\}\s*\)""",
)


def _rewrite(match: re.Match) -> str:
    url = match.group(1)
    method = match.group(2).upper()
    body = match.group(3)
    if body:
        return f"api({url}, '{method}', {body})"
    return f"api({url}, '{method}')"


def apply(project: Path, finding) -> FixResult:
    rel_file = finding.fix_payload.get("file")
    if not rel_file:
        return FixResult(False, message="missing fix_payload.file")
    target = project / rel_file
    if not target.is_file():
        return FixResult(False, message=f"target file not found: {rel_file}")

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        return FixResult(False, message=f"read failed: {e}")

    # Defense in depth: never rewrite a file whose api() helper isn't positional.
    # The scanner already filters to positional-helper files, but this guard
    # makes the fixer safe even if invoked directly on a stale/foreign finding.
    from suprema.autorepair.scanners.malformed_api_helper_call import (
        _helper_is_positional,
    )
    if _helper_is_positional(content) is not True:
        return FixResult(
            False,
            message=f"refusing to rewrite {rel_file}: its api() helper is "
                    "options-style or undefined here, so the options-bag call "
                    "is correct — rewriting would BREAK it",
        )

    new = PATTERN.sub(_rewrite, content)
    if new == content:
        return FixResult(
            success=True,
            message="already rewritten (idempotent) or pattern no longer matches",
        )

    target.write_text(new, encoding="utf-8")
    n_changes = sum(1 for _ in PATTERN.finditer(content))
    return FixResult(
        success=True,
        changed_files=[rel_file],
        message=f"rewrote {n_changes} malformed api() call(s) in {rel_file}",
        risk_notes="only inline-object bodies are rewritten; variable bodies "
                   "(e.g. body:JSON.stringify(payload)) are left for human review",
    )
