"""Daemon-verified, fail-closed pipeline gates. The daemon runs these objective
checks itself — the agent never self-certifies. build = the project's tests must
pass; security = gitleaks must find no leaks."""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GateResult:
    ok: bool
    detail: str
    findings: int = 0


def run_build(worktree, *, cmd: str = "python -m pytest -q", timeout_s: int = 1800) -> GateResult:
    try:
        proc = subprocess.run(shlex.split(cmd), cwd=str(worktree),
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return GateResult(False, "build timed out")
    except Exception as e:  # missing interpreter, bad cmd -> fail closed
        return GateResult(False, f"build error: {e}")
    if proc.returncode == 0:
        return GateResult(True, "build passed")
    return GateResult(False, f"build failed (exit {proc.returncode})")


def run_security(worktree, *, timeout_s: int = 600) -> GateResult:
    if shutil.which("gitleaks") is None:
        return GateResult(False, "gitleaks not installed (fail-closed)")
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "gitleaks.json"
        try:
            proc = subprocess.run(
                ["gitleaks", "detect", "--source", str(worktree), "--no-git",
                 "--report-format", "json", "--report-path", str(report),
                 "--exit-code", "1"],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return GateResult(False, "security scan timed out")
        except Exception as e:
            return GateResult(False, f"security scan error: {e}")
        if proc.returncode == 0:
            return GateResult(True, "no leaks", 0)
        if proc.returncode == 1:
            findings = 0
            try:
                data = json.loads(report.read_text(encoding="utf-8"))
                findings = len(data) if isinstance(data, list) else 0
            except Exception:
                findings = 1  # leaks reported but report unreadable -> still block
            return GateResult(False, f"{findings} leak(s) found", findings)
        return GateResult(False, f"gitleaks error (exit {proc.returncode})")
