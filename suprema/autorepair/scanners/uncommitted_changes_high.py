"""Scan: working tree has accumulated a lot of uncommitted changes.

Why this matters: KAI Supreme flagged "163 uncommitted changes" on the Mac
mini's wheellsverse_bots clone. A working tree that large is risky for
three reasons:
    1. A `git checkout` or `git reset` could destroy hours/days of work.
    2. Mixed concerns — secrets + code + generated files — make a single
       `git add -A` dangerous (we already had one near-miss with leaked
       creds; see project memory).
    3. It's usually a smell: the daemon is writing runtime state into the
       repo, or generated outputs aren't gitignored, or the operator is
       working across branches without committing.

Strategy:
    - Run `git status --porcelain` from the project root.
    - Count modified/added/deleted/untracked lines.
    - HIGH at >=100, MEDIUM at >=30.
    - In the evidence, break down top dirs so the operator immediately sees
      whether it's runtime junk (`logs/`, `outputs/`, `data/`) or real code.

Read-only; never mutates the working tree.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path


def _git_status_porcelain(project: Path) -> list[str]:
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project, capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return []
        return [line for line in r.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _top_dirs(lines: list[str], n: int = 5) -> list[tuple[str, int]]:
    """Return [(dir, count), ...] for the top-N directories appearing in
    the porcelain output. Skips secret-ish files entirely (we'll mention
    them explicitly)."""
    counts: Counter[str] = Counter()
    for line in lines:
        # porcelain format: "XY path/to/file" or "XY -> new/path"
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        parts = path.split("/", 1)
        top = parts[0] if len(parts) > 1 else "(root)"
        counts[top] += 1
    return counts.most_common(n)


def _has_secret_files(lines: list[str]) -> bool:
    SECRET_NAMES = (".env", ".env.local", ".env.production",
                    "credentials.json", "secrets.json", ".pem", ".key")
    for line in lines:
        path = line[3:].strip().lower()
        for s in SECRET_NAMES:
            if path.endswith(s) or path.endswith(s + ".bak"):
                return True
    return False


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    if not (project / ".git").exists():
        return []

    lines = _git_status_porcelain(project)
    count = len(lines)
    if count < 30:
        return []

    top = _top_dirs(lines)
    breakdown = ", ".join(f"{d}: {c}" for d, c in top)
    has_secrets = _has_secret_files(lines)

    if count >= 100:
        sev = "high"
        verdict = "Large diff = risk of losing work or leaking secrets if reset."
    else:
        sev = "medium"
        verdict = "Consider committing or stashing — diff is growing."

    evidence = f"{count} uncommitted changes. Top: {breakdown}. {verdict}"
    if has_secrets:
        evidence += " ⚠️ .env / credentials files in diff — do NOT `git add -A`."
        sev = "high"

    return [{
        "severity": sev,
        "location": f"{project} (working tree)",
        "evidence": evidence[:300],
        "fix_payload": {
            "action": "review_working_tree",
            "count": count,
            "top_dirs": top,
            "has_secrets": has_secrets,
        },
    }]
