from __future__ import annotations

import json
import os
import time
from datetime import datetime

from ..models import BackupStatus, RunnerStatus
from .base import run_cmd


def parse_snapshots(stdout: str, now_epoch: float) -> tuple[int, int | None]:
    stdout = stdout.strip()
    if not stdout:
        return 0, None
    snaps = json.loads(stdout)
    if not snaps:
        return 0, None
    newest = None
    for s in snaps:
        t = datetime.fromisoformat(s["time"].replace("Z", "+00:00")).timestamp()
        newest = t if newest is None else max(newest, t)
    return len(snaps), int(now_epoch - newest)


def run_backup_and_check(repo: str, backup_paths: list[str], now_epoch: float) -> tuple[BackupStatus, RunnerStatus]:
    t0 = time.time()
    if not repo or not os.environ.get("RESTIC_PASSWORD"):
        return (BackupStatus(repo=repo, configured=False),
                RunnerStatus(tool="restic", ok=False, error="repo or RESTIC_PASSWORD unset",
                             duration_ms=int((time.time() - t0) * 1000)))
    env_repo = ["-r", repo]
    run_cmd(["restic", *env_repo, "backup", *backup_paths])  # best effort
    rc_chk, _, chk_err = run_cmd(["restic", *env_repo, "check"])
    rc_snap, snap_out, snap_err = run_cmd(["restic", *env_repo, "snapshots", "--json"])
    if rc_snap == 127:
        return (BackupStatus(repo=repo, configured=False),
                RunnerStatus(tool="restic", ok=False, error="restic not installed",
                             duration_ms=int((time.time() - t0) * 1000)))
    count, age = parse_snapshots(snap_out, now_epoch)
    status = BackupStatus(repo=repo, configured=True, snapshot_count=count,
                          last_snapshot_age_s=age, check_ok=(rc_chk == 0))
    return (status, RunnerStatus(tool="restic", ok=(rc_snap == 0),
                                 error=(snap_err or chk_err or None) if rc_snap else None,
                                 duration_ms=int((time.time() - t0) * 1000)))
