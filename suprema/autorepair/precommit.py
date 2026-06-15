"""Pre-commit hook installer for SUPREMA projects.

Drops a `.git/hooks/pre-commit` script in each project's git repo. The
script invokes the autorepair scanner; if any auto-safe pattern finding
touches staged files, the commit is blocked with a friendly message and
a one-liner to fix it.

This is the "make patterns sticky" mechanism — once a fix lands, the
hook prevents the same bug from being reintroduced on the next commit.

Bypass for emergencies: `git commit --no-verify`."""

from __future__ import annotations

import logging
import stat
from pathlib import Path

log = logging.getLogger("suprema.autorepair")

# Template uses <<TOKENS>> instead of {placeholders} to avoid collisions
# with the embedded bash $VARS and Python f-strings.
HOOK_TEMPLATE = r"""#!/usr/bin/env bash
# SUPREMA autorepair pre-commit hook (auto-installed)
#
# Blocks commits that reintroduce known auto-safe pattern bugs in staged
# files. Bypass with `git commit --no-verify` if you really need to.
#
# Disable per-project: set SUPREMA_PRECOMMIT_DISABLE=1 in your env.
# Disable globally:   set SUPREMA_DISABLE=1
set -e

if [ "${SUPREMA_DISABLE:-0}" = "1" ] || [ "${SUPREMA_PRECOMMIT_DISABLE:-0}" = "1" ]; then
  exit 0
fi

STAGED=$(git diff --cached --name-only --diff-filter=ACM)
if [ -z "$STAGED" ]; then
  exit 0
fi

SUPREMA_ROOT="<<SUPREMA_ROOT>>"
PROJECT_NAME="<<PROJECT_NAME>>"
PY="<<PYTHON>>"

# Get all findings in JSON
RESULT=$(SUPREMA_STDOUT=0 PYTHONPATH="$SUPREMA_ROOT" "$PY" -m suprema.autorepair.cli \
            --project "$PROJECT_NAME" scan --json 2>/dev/null || echo '[]')

# Single Python call: filter + print + exit. Avoids heredoc/stdin clash.
SUPREMA_STDOUT=0 PYTHONPATH="$SUPREMA_ROOT" "$PY" - "$RESULT" "$STAGED" "$SUPREMA_ROOT" "$PROJECT_NAME" "$PY" <<'PYEOF'
import json, sys
raw, staged_str, suprema_root, proj, py = sys.argv[1:6]
data = json.loads(raw or "[]")
staged_paths = set(staged_str.splitlines())
from suprema.autorepair.engine import CATALOG
blocking = []
for f in data:
    loc = f.get("location", "")
    file_only = loc.split(":")[0] if ":" in loc else loc
    if not file_only:
        continue
    if any(s.endswith(file_only) or file_only.endswith(s) for s in staged_paths):
        if CATALOG.get(f["pattern"], {}).get("safety") == "auto-safe":
            blocking.append(f)
if blocking:
    print()
    print(f"⛔ SUPREMA autorepair blocked this commit — {len(blocking)} auto-safe finding(s) in staged files:")
    for f in blocking:
        print(f"   • [{f['pattern']}]  {f['location']}")
        if f.get("evidence"):
            print(f"       ↳ {f['evidence'][:120]}")
    print()
    print("To auto-fix:")
    print(f"   cd {suprema_root}")
    print(f"   PYTHONPATH=. {py} -m suprema.autorepair.cli --project {proj} fix --commit")
    print()
    print("To bypass this hook (emergency only):")
    print("   git commit --no-verify")
    print()
    sys.exit(1)
sys.exit(0)
PYEOF
"""


def install_one(project: Path, python_bin: str) -> tuple[bool, str]:
    """Install pre-commit hook for a single project. Returns (success, message)."""
    if not (project / ".git").exists():
        return False, "not a git repo"
    hooks_dir = project / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_file = hooks_dir / "pre-commit"

    # Don't overwrite a non-suprema hook silently
    if hook_file.exists():
        existing = hook_file.read_text(errors="replace")
        if "SUPREMA autorepair pre-commit hook" not in existing:
            backup = hook_file.with_suffix(".pre-suprema.bak")
            backup.write_text(existing)
            log.info(f"  backed up existing hook to {backup.relative_to(project)}")

    content = (
        HOOK_TEMPLATE
        .replace("<<SUPREMA_ROOT>>", str(project.parent))
        .replace("<<PROJECT_NAME>>", project.name)
        .replace("<<PYTHON>>", python_bin)
    )
    hook_file.write_text(content)
    mode = hook_file.stat().st_mode
    hook_file.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return True, f"installed at {hook_file.relative_to(project)}"


def install_all(only_projects: list[str] | None = None) -> int:
    """Install hooks in each git-tracked SUPREMA project."""
    from suprema.autorepair.engine import PROJECTS, project_path

    import os
    import shutil
    # Prefer system-installed python over the first-on-PATH (which may be
    # a stale venv from another project). Order: env override → homebrew →
    # PATH lookup → hardcoded fallback.
    python_bin = (
        os.environ.get("SUPREMA_PYTHON")
        or ("/opt/homebrew/bin/python3"
            if Path("/opt/homebrew/bin/python3").exists() else None)
        or shutil.which("python3")
        or "/usr/bin/python3"
    )

    projects = only_projects or list(PROJECTS)
    failures = 0
    for proj_name in projects:
        proj = project_path(proj_name)
        if not proj.is_dir():
            print(f"  ⚪ {proj_name}: not present, skipping")
            continue
        ok, msg = install_one(proj, python_bin)
        tag = "✓" if ok else "✗"
        print(f"  {tag} {proj_name}: {msg}")
        if not ok:
            failures += 1
    return 0 if failures == 0 else 1
