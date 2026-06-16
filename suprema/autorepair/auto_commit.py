"""When autorepair applies a fix, commit the changes atomically per project
so the operator can audit / revert easily.

Skips projects that aren't git repos or have nothing to commit. Uses a
distinct commit message prefix (`chore(autorepair):`) so these stand out
in `git log` and can be filtered."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


def is_repo(project: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(project), capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() == "true"
    except Exception:
        return False


def commit_changes(project: Path, files: Sequence[str], pattern: str,
                   message_detail: str = "") -> dict:
    """Stage + commit the given files. Returns {success, commit_sha, message}.

    Each call creates one commit. The caller should batch related findings
    into one call so one fix == one commit."""
    if not is_repo(project):
        return {"success": False, "message": "not a git repo"}
    if not files:
        return {"success": False, "message": "no files to commit"}

    # Only stage files that actually exist + have changes
    real_files = [f for f in files if (project / f).exists()]
    if not real_files:
        return {"success": False, "message": "no extant files among given paths"}

    try:
        subprocess.run(["git", "add", *real_files], cwd=str(project),
                       capture_output=True, text=True, timeout=15, check=True)
    except subprocess.CalledProcessError as e:
        return {"success": False, "message": f"git add failed: {e.stderr.strip()}"}

    # Anything staged?
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"],
                          cwd=str(project), capture_output=True, text=True, timeout=10)
    if diff.returncode == 0:
        return {"success": False, "message": "nothing staged (likely already committed)"}

    commit_msg = (
        f"chore(autorepair): {pattern}\n\n"
        f"Applied automatically by SUPREMA autorepair.\n"
        f"{message_detail}\n\n"
        f"Generated-By: suprema-autorepair"
    )
    try:
        subprocess.run(["git", "commit", "-m", commit_msg],
                       cwd=str(project), capture_output=True, text=True, timeout=15, check=True)
    except subprocess.CalledProcessError as e:
        return {"success": False, "message": f"git commit failed: {e.stderr.strip()}"}

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         cwd=str(project), capture_output=True, text=True, timeout=5)
    return {
        "success": True,
        "commit_sha": sha.stdout.strip(),
        "message": f"committed {len(real_files)} file(s)",
    }
