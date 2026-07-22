"""Disposable-container sandbox — the SWE runtime's secured execution primitive.

Runs a bounded command inside a locked-down, throwaway Docker container:
  - NO host bind mount: source is copied IN via `docker cp` (edited on a
    disposable copy), artifacts copied OUT — zero host filesystem exposure.
  - `--network none` (no egress), `--cap-drop ALL`, `--security-opt
    no-new-privileges`, no host Docker socket.
  - resource caps (memory/pids/cpu), wall-clock timeout (docker kill on breach),
    container force-removed afterward.
The OpenHands agent brain (a later increment) runs its edit/test commands through
THIS envelope; this module is the security primitive, not the agent.
"""
from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.swe_runtime import policy as pol
from app.services.swe_runtime.config import SandboxPolicy, runtime_enabled

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    artifacts: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    disabled: bool = False

    def as_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "disabled": self.disabled,
            "error": self.error,
            "stdout": self.stdout[-8000:],
            "stderr": self.stderr[-4000:],
            "artifact_files": sorted(self.artifacts.keys()),
        }


@runtime_checkable
class SandboxBackend(Protocol):
    def run(self, *, source_dir: str, command: str, policy: SandboxPolicy) -> SandboxResult: ...


class DisabledSandbox:
    """Default backend when the runtime is off — never executes anything."""

    def run(self, *, source_dir: str, command: str, policy: SandboxPolicy) -> SandboxResult:
        return SandboxResult(
            exit_code=-1, stdout="", stderr="", disabled=True,
            error="SWE runtime disabled (set KAI_SWE_RUNTIME_ENABLED=1 on a non-prod runner)",
        )


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def _docker(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def build_create_args(command: str, policy: SandboxPolicy) -> list[str]:
    """The `docker create` argv encoding the full lockdown. Pure function so a
    unit test can assert every containment flag is present without a daemon."""
    return [
        "create", "--pull", "never",
        "--network", "none",
        "--memory", policy.memory, "--memory-swap", policy.memory,
        "--pids-limit", str(policy.pids_limit), "--cpus", policy.cpus,
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--workdir", "/work",
        policy.image, "sh", "-c", command,
    ]


class DockerSandbox:
    """create (locked down) → cp source in → start (wall-clock bounded) →
    cp artifacts out → rm -f. No host mount, no network, capability-stripped,
    resource-capped, ephemeral."""

    def run(self, *, source_dir: str, command: str, policy: SandboxPolicy) -> SandboxResult:
        pol.validate(command, policy)  # raises PolicyDenied
        cid = None
        try:
            created = _docker(build_create_args(command, policy), timeout=30)
            if created.returncode != 0:
                return SandboxResult(-1, "", created.stderr, error=f"create failed: {created.stderr[:300]}")
            cid = created.stdout.strip()
            cp_in = _docker(["cp", f"{source_dir}/.", f"{cid}:/work"], timeout=60)
            if cp_in.returncode != 0:
                return SandboxResult(-1, "", cp_in.stderr, error=f"source copy failed: {cp_in.stderr[:300]}")

            timed_out = False
            try:
                started = _docker(["start", "-a", cid], timeout=policy.timeout_seconds)
                stdout, stderr, code = started.stdout, started.stderr, started.returncode
            except subprocess.TimeoutExpired:
                _docker(["kill", cid], timeout=15)
                timed_out, stdout, stderr, code = True, "", "wall-clock timeout — killed", 124

            artifacts = self._collect_artifacts(cid, policy)
            return SandboxResult(code, stdout, stderr, timed_out=timed_out, artifacts=artifacts)
        except pol.PolicyDenied:
            raise
        except Exception as e:  # pragma: no cover - defensive
            return SandboxResult(-1, "", "", error=f"sandbox error: {type(e).__name__}: {e}")
        finally:
            if cid:
                _docker(["rm", "-f", cid], timeout=15)

    def _collect_artifacts(self, cid: str, policy: SandboxPolicy) -> dict[str, str]:
        # SECURITY: `docker cp` on copy-out PRESERVES symlinks. A container
        # command can plant `ln -s /etc/passwd /work/p` or `ln -s /dev/zero
        # /work/z`; dereferencing those against the HOST would read host files or
        # hang on a device (getsize reports 0, evading the cap). So we NEVER
        # follow a symlink and NEVER read a non-regular file, verify each path
        # stays inside tmp, open with O_NOFOLLOW, and bound every read.
        out: dict[str, str] = {}
        tmp = tempfile.mkdtemp(prefix="kai-swe-artifacts-")
        real_tmp = os.path.realpath(tmp)
        try:
            if _docker(["cp", f"{cid}:/work/.", tmp], timeout=60).returncode != 0:
                return out
            total = 0
            for root, dirs, files in os.walk(tmp, followlinks=False):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
                for name in files:
                    if len(out) >= policy.max_artifact_files:
                        return out
                    path = os.path.join(root, name)
                    if os.path.islink(path):
                        continue  # never follow a container-planted symlink
                    if not os.path.realpath(path).startswith(real_tmp + os.sep):
                        continue  # escaped tmp — reject
                    try:
                        st = os.stat(path, follow_symlinks=False)
                    except OSError:
                        continue
                    if not stat.S_ISREG(st.st_mode):
                        continue  # skip devices/fifos/sockets
                    if st.st_size > policy.max_artifact_bytes:
                        continue
                    remaining = policy.max_artifact_bytes - total
                    if remaining <= 0:
                        return out
                    try:
                        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    except OSError:
                        continue  # ELOOP if a final-component symlink slipped through
                    try:
                        data = os.read(fd, remaining)  # hard byte bound
                    finally:
                        os.close(fd)
                    out[os.path.relpath(path, tmp)] = data.decode("utf-8", "replace")
                    total += len(data)
            return out
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def get_backend() -> SandboxBackend:
    """DockerSandbox when the runtime is enabled, else DisabledSandbox (default)."""
    return DockerSandbox() if runtime_enabled() else DisabledSandbox()
