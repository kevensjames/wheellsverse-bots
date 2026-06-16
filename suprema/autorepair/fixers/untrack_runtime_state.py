"""Auto-safe fixer for committed_runtime_state findings.

For each finding:
  1. Add the gitignore pattern to .gitignore (if not already there)
  2. `git rm --cached` the file (untracks without deleting from disk)

The result is a committable state change: .gitignore has new entries,
and the index no longer tracks the runtime files. The auto_commit module
will batch all of these into one chore(autorepair): commit.

Note: this does NOT rewrite history — the file content is still in
previous commits. If the file contained secrets (auth tokens, session
cookies), the operator should also rotate those credentials. The fix
result's risk_notes calls this out when applicable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from suprema.autorepair.engine import FixResult

HEADER_COMMENT = "\n# Runtime state / logs / secrets — auto-added by SUPREMA autorepair\n"


def _ensure_gitignore_has(project: Path, patterns: list[str]) -> bool:
    """Append missing patterns to .gitignore. Returns True if file changed."""
    gi = project / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    existing_lines = {line.strip() for line in existing.splitlines() if line.strip()}

    new_patterns = [p for p in patterns if p not in existing_lines]
    if not new_patterns:
        return False

    addition = HEADER_COMMENT + "\n".join(new_patterns) + "\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    gi.write_text(existing + addition, encoding="utf-8")
    return True


def _git_rm_cached(project: Path, files: list[str]) -> tuple[list[str], list[str]]:
    """Run `git rm --cached` on each file. Returns (succeeded, failed)."""
    ok, fail = [], []
    for f in files:
        try:
            r = subprocess.run(
                ["git", "rm", "--cached", "-r", f],
                cwd=str(project),
                capture_output=True, text=True, timeout=20,
            )
            (ok if r.returncode == 0 else fail).append(f)
        except Exception:
            fail.append(f)
    return ok, fail


def apply(project: Path, finding) -> FixResult:
    payload = finding.fix_payload or {}
    target_file = payload.get("file")
    gi_pattern = payload.get("gitignore_pattern")
    descr = payload.get("description", "")
    if not target_file or not gi_pattern:
        return FixResult(False, message="missing fix_payload.file or .gitignore_pattern")

    # Refuse to auto-untrack files that likely contain actual data the
    # operator wants to keep tracked — DBs, vector stores, anything large
    # enough to be a real persistence layer rather than just runtime
    # scratch state.
    data_bearing_suffixes = (".db", ".sqlite", ".sqlite3", ".pkl", ".bin", ".vec")
    if any(target_file.endswith(s) for s in data_bearing_suffixes):
        return FixResult(
            success=False,
            message=f"{target_file}: data-bearing file — needs manual decision",
            risk_notes=(
                "This file may contain real persistent data. Auto-untracking "
                "is unsafe. Run manually if you're sure:\n"
                f"    echo '{gi_pattern}' >> .gitignore\n"
                f"    git rm --cached {target_file}\n"
                "    git commit -m 'chore: untrack runtime DB'"
            ),
        )

    # 1. Append to .gitignore (idempotent)
    gi_changed = _ensure_gitignore_has(project, [gi_pattern])

    # 2. Untrack the file (idempotent — git rm --cached on already-untracked
    # is a no-op error we handle below)
    ok, fail = _git_rm_cached(project, [target_file])

    # Only return files that need `git add` from the auto_commit module.
    # The `git rm --cached` calls above ALREADY staged the removals in the
    # index — re-adding via `git add` would fail (paths are now ignored).
    # auto_commit will `git add .gitignore` then `git commit`, picking up
    # the staged removals automatically.
    changed: list[str] = []
    if gi_changed:
        changed.append(".gitignore")

    if not ok and not gi_changed:
        return FixResult(
            success=True,
            message=f"{target_file}: already untracked and ignored (idempotent)",
        )

    risk = ""
    if any(k in descr.lower() for k in ("secret", "auth", "credentials")):
        risk = (
            "⚠️  This file likely contains secrets. Untracking does NOT remove "
            "the content from prior commits — the secret is still in git history. "
            "Rotate the credential and consider `git filter-repo` to scrub history."
        )

    return FixResult(
        success=True,
        changed_files=changed,
        message=f"untracked {target_file}; added '{gi_pattern}' to .gitignore",
        risk_notes=risk,
        # This fix only changes .gitignore + the git index — no executable
        # code touched. Skip smoke-test gating to keep the cycle fast and
        # avoid false-fail on projects without a runnable venv.
        requires_smoke_test=False,
    )
