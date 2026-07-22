"""SWE-runtime configuration + policy defaults.

Feature-flagged OFF by default (KAI_SWE_RUNTIME_ENABLED). This subsystem runs
agent/operator-supplied commands inside a disposable container; it must never be
active unless the operator explicitly enables it, and never on the production
daemon (enable only on a non-production runner — see docs/swe_runtime.md).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def runtime_enabled() -> bool:
    return _truthy("KAI_SWE_RUNTIME_ENABLED")


# Images the sandbox may run (comma-separated env override). Deny-by-default:
# only allowlisted images can be used.
def _image_allowlist() -> tuple[str, ...]:
    raw = (os.environ.get("KAI_SWE_IMAGE_ALLOWLIST") or "python:3.11-slim").strip()
    return tuple(i.strip() for i in raw.split(",") if i.strip())


# Command substrings that are denied even inside the (already network-isolated)
# sandbox — defense-in-depth against egress attempts, credential reads, and
# escapes. The container has --network none so these are already inert, but we
# reject them so intent is auditable.
DEFAULT_DENIED_SUBSTRINGS = (
    "curl", "wget", "nc ", "netcat", "ssh", "scp", "ftp", "telnet",
    "/proc/1/", "docker", "kubectl", "mount", "sudo", "chroot",
    "/etc/shadow", "id_rsa", "~/.aws", "~/.ssh", "credentials",
)


@dataclass(slots=True)
class SandboxPolicy:
    image: str = "python:3.11-slim"
    timeout_seconds: int = 120
    memory: str = "512m"
    pids_limit: int = 256
    cpus: str = "1.0"
    # Containment is via --network none + --cap-drop ALL + no-new-privileges +
    # no host mount + ephemeral (not a non-root user — cp'd source must be
    # editable; a chown-on-entry non-root variant is a hardening follow-up).
    max_artifact_bytes: int = 2_000_000    # cap total artifact bytes copied out
    max_artifact_files: int = 500
    denied_substrings: tuple[str, ...] = DEFAULT_DENIED_SUBSTRINGS


def default_policy() -> SandboxPolicy:
    p = SandboxPolicy()
    p.image = _image_allowlist()[0]
    p.timeout_seconds = int(os.environ.get("KAI_SWE_MAX_WALL_SECONDS", "120"))
    p.memory = os.environ.get("KAI_SWE_MEMORY", "512m")
    p.pids_limit = int(os.environ.get("KAI_SWE_PIDS_LIMIT", "256"))
    p.cpus = os.environ.get("KAI_SWE_CPUS", "1.0")
    return p


def image_allowed(image: str) -> bool:
    return image in _image_allowlist()


def _repo_allowlist() -> tuple[str, ...]:
    raw = (os.environ.get("KAI_SWE_REPO_ALLOWLIST") or "").strip()
    if not raw:
        return ()
    sep = os.pathsep if os.pathsep in raw else ","
    return tuple(p.strip() for p in raw.split(sep) if p.strip())


def repo_allowed(path: str) -> bool:
    """A source dir may be run only if it resolves under an allowlisted root.
    Deny-by-default: with no allowlist configured, nothing is runnable."""
    real = os.path.realpath(path)
    for root in _repo_allowlist():
        r = os.path.realpath(root)
        if real == r or real.startswith(r + os.sep):
            return True
    return False
