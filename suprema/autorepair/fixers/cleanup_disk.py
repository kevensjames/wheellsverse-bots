"""Fixer: free disk space when disk_usage_high fires.

Strategy — only touch regenerable junk, never the operator's data:
    1. Remove every `__pycache__` directory under the project tree.
    2. Remove `*.log` files in <project>/logs/ older than 30 days.
    3. Remove `*.log.*` rotated-log siblings (gz, .1, .2, …) older than 30d.

We DO NOT touch:
    - `outputs/` (operator content)
    - `data/` (KAI / SUPREMA state)
    - `.git/` (history)
    - logs newer than 30 days (still useful for triage)

The fixer is safe to re-run; idempotent; sets `requires_smoke_test=False`
because no executable code is touched.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Engine resolves imports via package; import FixResult lazily to avoid cycles
def _make_result(success: bool, changed_files: list[str], message: str,
                 risk_notes: str = "") -> object:
    # Engine is imported as either `suprema.autorepair.engine` (vendored) or
    # `autorepair.engine` (standalone /Volumes/Wheellsverse/suprema repo).
    try:
        from suprema.autorepair.engine import FixResult
    except ImportError:
        from autorepair.engine import FixResult
    return FixResult(
        success=success,
        changed_files=changed_files,
        message=message,
        risk_notes=risk_notes,
        requires_smoke_test=False,
    )


MAX_LOG_AGE_DAYS = 30
SKIP_DIRS = {"outputs", "data", ".git", ".venv", "venv", "node_modules"}


def _iter_pycache(root: Path):
    for dirpath, dirnames, _ in os.walk(root):
        # prune skip-dirs before descending
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if Path(dirpath).name == "__pycache__":
            yield Path(dirpath)


def _is_log_stale(p: Path, max_age_days: int) -> bool:
    try:
        age_s = abs(p.stat().st_mtime - p.stat().st_ctime)
    except Exception:
        return False
    # Use wall-clock mtime check
    import time
    return (time.time() - p.stat().st_mtime) > max_age_days * 86400


def apply(project: Path, finding: dict) -> object:
    """Clean __pycache__ and stale logs under `project`. Returns FixResult."""
    bytes_freed = 0
    files_deleted: list[str] = []

    # 1. __pycache__ dirs
    for pyc in _iter_pycache(project):
        try:
            for f in pyc.rglob("*"):
                if f.is_file():
                    try:
                        bytes_freed += f.stat().st_size
                    except Exception:
                        pass
            shutil.rmtree(pyc, ignore_errors=True)
            files_deleted.append(str(pyc.relative_to(project)))
        except Exception:
            continue

    # 2. logs/*.log older than 30d
    logs_dir = project / "logs"
    if logs_dir.is_dir():
        for log_path in list(logs_dir.glob("*.log")) + list(logs_dir.glob("*.log.*")):
            try:
                if not _is_log_stale(log_path, MAX_LOG_AGE_DAYS):
                    continue
                bytes_freed += log_path.stat().st_size
                log_path.unlink()
                files_deleted.append(str(log_path.relative_to(project)))
            except Exception:
                continue

    mb_freed = round(bytes_freed / (1024 * 1024), 1)
    msg = (f"freed {mb_freed} MB across {len(files_deleted)} path(s) "
           f"({sum(1 for f in files_deleted if '__pycache__' in f)} pycache, "
           f"{sum(1 for f in files_deleted if f.endswith('.log') or '.log.' in f)} log)")

    return _make_result(
        success=len(files_deleted) > 0 or bytes_freed == 0,  # success even if nothing to clean
        changed_files=files_deleted[:50],  # cap reporting; engine doesn't need all
        message=msg,
        risk_notes="only removed __pycache__ + logs >30d old; nothing in outputs/, data/, or .git/",
    )
