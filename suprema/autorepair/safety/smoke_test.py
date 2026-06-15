"""Smoke-test gating.

Before any fixer commits its changes, run a project-specific smoke test
to verify the change didn't break the build. Abort + revert on failure.

Default smoke test: `python -c "from core.api import app"` — same check
the Dockerfile uses. Each project can override via `.suprema/smoketest.sh`
which is run with the project as CWD and must exit 0.

If no smoke test is configured AND no default-matching file structure is
found, the gating is skipped (with a logged warning) — we don't want to
block fixes on projects that genuinely don't have an entry point yet
(e.g. the spec-kit-only SUPREMA projects)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("suprema.autorepair")


def _project_python(project: Path) -> str:
    """Prefer the project's own venv Python (which has the right deps)
    over the autorepair-runtime Python."""
    for candidate in (
        project / ".venv" / "bin" / "python3",
        project / ".venv" / "bin" / "python",
        project / "venv" / "bin" / "python3",
        project / "venv" / "bin" / "python",
        project / ".python" / "bin" / "python3",
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _smoke_command(project: Path) -> list[str] | None:
    """Decide what to run as the smoke test for this project."""
    override = project / ".suprema" / "smoketest.sh"
    if override.is_file():
        return ["bash", str(override)]

    py = _project_python(project)

    # Default: FastAPI-style import check, matching Dockerfile BUILD CHECK pattern
    for entry in ("core.api", "app.main", "backend.main", "main"):
        rel = entry.replace(".", "/") + ".py"
        if (project / rel).is_file():
            return [
                py,
                "-c",
                f"from {entry} import app; print('[SMOKE] {entry}.app imports OK')",
            ]

    # Plain Python project with __main__ or a single entrypoint
    if (project / "main.py").is_file():
        return [py, str(project / "main.py"), "--help"]

    return None


def run(project: Path, *, timeout: int = 60) -> tuple[bool, str]:
    """Run the smoke test for `project`. Returns (passed, message).

    A None command (no detectable entry) is treated as a PASS so spec-kit
    projects without code yet don't block — but we log it so it's visible."""
    cmd = _smoke_command(project)
    if cmd is None:
        log.info(f"smoke-test: no entry point in {project.name} — skipping (treated as pass)")
        return True, "skipped: no entry point"

    env = None  # inherit
    try:
        r = subprocess.run(
            cmd,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    except Exception as e:
        return False, f"smoke-test crashed: {e}"

    if r.returncode == 0:
        return True, (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "ok"
    err = (r.stderr or r.stdout or "").strip()
    return False, err[:500]


# ── Rollback helpers ───────────────────────────────────────────────────────
def stash_create(project: Path, label: str) -> str | None:
    """Snapshot the working tree without disturbing it. Returns stash sha
    so caller can pop/drop later."""
    if not (project / ".git").exists():
        return None
    try:
        r = subprocess.run(
            ["git", "stash", "create", label],
            cwd=str(project),
            capture_output=True, text=True, timeout=15,
        )
        sha = r.stdout.strip()
        return sha or None
    except Exception:
        return None


def restore(project: Path, stash_sha: str) -> bool:
    """Restore working tree from a previously-created stash sha."""
    if not stash_sha:
        return False
    try:
        # checkout-index style restore so we don't add a stash entry
        r = subprocess.run(
            ["git", "checkout", stash_sha, "--", "."],
            cwd=str(project),
            capture_output=True, text=True, timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def revert_last_commit(project: Path) -> bool:
    """Reset HEAD~1, restoring the prior state. Only call this when the
    last commit was the autorepair one and the smoke test failed.

    Uses --mixed (default) so file changes stay in the working tree for
    inspection — operator can review what went wrong."""
    try:
        r = subprocess.run(
            ["git", "reset", "HEAD~1"],
            cwd=str(project),
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False
