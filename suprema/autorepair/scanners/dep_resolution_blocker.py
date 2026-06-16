"""Scan: requirements.txt has unresolvable version conflicts.

Runs `pip install --dry-run -r requirements.txt --quiet --no-deps=false`
in a temp env. Catches the openai/litellm/httpx style conflict before
the next docker build hits it in CI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def scan(project: Path, live_url: str | None = None) -> list[dict]:
    reqs = project / "requirements.txt"
    if not reqs.is_file():
        return []

    # Use the current Python's pip — guaranteed to exist and not point at a
    # stale venv from another project. `python -m pip install --dry-run` is
    # the canonical pip resolution probe.
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--dry-run",
             "--quiet", "--no-input", "-r", str(reqs)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return [{
            "severity": "medium",
            "location": str(reqs.relative_to(project)),
            "evidence": "pip resolution timed out (>180s) — likely struggling with conflict",
            "fix_payload": {},
        }]
    except Exception as e:
        return [{
            "severity": "low",
            "location": "scanner",
            "evidence": f"pip dry-run crashed: {e}",
            "fix_payload": {},
        }]

    err = (result.stderr or "") + (result.stdout or "")
    if "ResolutionImpossible" in err or "ERROR: Cannot install" in err:
        # Pull out the conflicting package lines so the user sees the actual collision
        lines = [ln.strip() for ln in err.splitlines()
                 if "depends on" in ln or "requires" in ln.lower()]
        evidence = " ; ".join(lines[:4])[:300] or "ResolutionImpossible (see pip output)"
        return [{
            "severity": "high",
            "location": str(reqs.relative_to(project)),
            "evidence": evidence,
            "fix_payload": {"stderr_tail": err[-500:]},
        }]

    return []
