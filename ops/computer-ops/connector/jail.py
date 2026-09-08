"""Outer execution boundary for the harness worker (macOS Seatbelt).

Why this exists
---------------
The previous phase established, by measurement, that harness plugin control is not
containment: the harness's own sandbox profile is `(allow default) (deny file-write*)`,
so process execution, network egress and arbitrary reads stay open, and one re-mounted
tool reopened all three with zero approval requests reaching KAI.

A plugin allowlist constrains CONFIGURATION. This jail constrains the PROCESS, in the
kernel. It holds regardless of which plugins load, what they do at runtime, or what a
future upstream version adds. That is the difference between a boundary and a policy.

Why Seatbelt rather than a container or VM
------------------------------------------
Evaluated on the actual host (Mac mini M4, macOS 25.6.0):
  * Docker/colima  -- installed but the daemon is NOT running; starting it is an
                      operator action, and it would add a large privileged surface.
  * VM (Lima/UTM/Virtualization.framework) -- strongest isolation, but needs an
                      operator decision on disk and lifecycle, and a local model
                      endpoint reachable from the guest.
  * Seatbelt (`sandbox-exec`) -- available now, needs no root and no daemon, and is
                      enforced by the kernel per-process.

Seatbelt is what this host can enforce TODAY, so it is what ships. It is Apple-
deprecated but functional and still used by the harness itself. If the operator later
approves a VM, this module is the seam to swap: `wrap()` is the only place that knows
how the worker is confined.

What is NOT claimed: Seatbelt is not a hypervisor boundary. A kernel vulnerability
defeats it. It is a strong, verified reduction in blast radius, not perfect isolation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

SBPL_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "runtime", "worker-jail.sbpl")


class JailUnavailable(RuntimeError):
    """Raised when the jail cannot be applied.

    Deliberately fatal rather than a warning: running the worker unconfined because the
    boundary is unavailable is exactly the silent downgrade this design exists to
    prevent. A mission that cannot be contained does not run.
    """


@dataclass(frozen=True)
class JailSpec:
    #: Mount point of the per-mission APFS volume. This is the ONLY writable location:
    #: workspace, session root, storage root and TMPDIR all live under it, on a
    #: filesystem separate from the boot volume, which is what makes hard links across
    #: the boundary impossible (EXDEV) rather than merely denied.
    volume: str
    dsh_home: str
    harness_dir: str
    model_base_url: str
    home: str = os.path.expanduser("~")

    @property
    def workspace(self) -> str:
        return os.path.join(self.volume, "workspace")

    def model_hostport(self) -> str:
        """`host:port` for the SBPL `remote ip` rule.

        Seatbelt matches the literal host string, so a URL whose host is not a loopback
        name is refused here rather than silently producing a rule that allows nothing
        (which would look like a broken model instead of a policy error).
        """
        parsed = urlparse(self.model_base_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise JailUnavailable(
                f"LOCAL_ONLY requires a loopback model endpoint; got host {host!r} from "
                f"{self.model_base_url!r}. Refusing to widen the jail for a remote host.")
        # Seatbelt's remote-ip matcher takes the name form for loopback.
        return f"localhost:{port}"


def render_profile(spec: JailSpec) -> str:
    with open(SBPL_TEMPLATE, encoding="utf-8") as fh:
        text = fh.read()
    subs = {
        "@MODEL_HOSTPORT@": spec.model_hostport(),
        "@VOLUME@": os.path.realpath(spec.volume),
        "@DSH_HOME@": os.path.realpath(spec.dsh_home),
        "@HARNESS_DIR@": os.path.realpath(spec.harness_dir),
        "@HOME@": os.path.realpath(spec.home),
    }
    for key, value in subs.items():
        if '"' in value:
            raise JailUnavailable(f"refusing to build a profile with a quote in {key}: {value!r}")
        text = text.replace(key, value)
    leftover = [k for k in subs if k in text]
    if leftover:
        raise JailUnavailable(f"unsubstituted placeholders remain: {leftover}")
    return text


def available() -> bool:
    return os.uname().sysname == "Darwin" and shutil.which("sandbox-exec") is not None


def assert_workspace_hygiene(workspace: str) -> None:
    """Refuse a workspace containing hard links to files outside it.

    Seatbelt authorises by path, so a hard link planted in the workspace before the
    mission starts is a write-through to whatever it points at. The worker cannot create
    one (the profile denies `file-link`), but a pre-existing link would still be honoured
    -- so the workspace is checked before it is trusted. Any file with st_nlink > 1 is
    refused rather than inspected: proving where the other link lives is more expensive
    and less reliable than simply declining to run.
    """
    for root, _dirs, files in os.walk(workspace):
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not os.path.islink(path) and st.st_nlink > 1:
                raise JailUnavailable(
                    f"workspace hygiene: {path} has st_nlink={st.st_nlink}; a hard link in the "
                    "mission workspace can write through to a file outside it. Refusing to run.")


def preflight(spec: JailSpec) -> None:
    """Prove the kernel accepts and ENFORCES the profile before a mission uses it.

    Two checks, because an accepted profile is not the same as an enforcing one:
      1. `sandbox-exec` exits non-zero if `sandbox_init` refuses the profile.
      2. A real denied operation must actually be denied.
    Without (2) a typo that silently produced a permissive profile would pass.
    """
    if not available():
        raise JailUnavailable("sandbox-exec is unavailable; this host cannot confine the worker")
    assert_workspace_hygiene(spec.workspace)
    profile = render_profile(spec)

    accepted = subprocess.run(["sandbox-exec", "-p", profile, "/usr/bin/true"],
                              capture_output=True, text=True, timeout=20)
    if accepted.returncode != 0:
        raise JailUnavailable(f"kernel refused the jail profile: {accepted.stderr.strip()[:400]}")

    # Enforcement probe: writing outside the workspace must fail.
    outside = os.path.join(spec.home, ".kai_jail_enforcement_probe")
    probe = subprocess.run(
        ["sandbox-exec", "-p", profile, "/bin/sh", "-c", f"echo x > {outside!r} 2>/dev/null"],
        capture_output=True, text=True, timeout=20)
    if os.path.exists(outside):
        os.remove(outside)
        raise JailUnavailable(
            "jail profile was accepted but did NOT enforce: a write outside the workspace "
            "succeeded. Refusing to run a mission behind a boundary that does not hold.")
    del probe
    return None


def workspace_identity(workspace: str) -> tuple[int, int]:
    """(st_dev, st_ino) of the workspace root, captured at attestation time.

    The rendered profile allows a resolved PATH. If that path were later repointed at a
    different directory, the allowance would follow the name rather than the directory
    that was attested. The worker itself cannot do this -- it has no write access to the
    workspace's parent, verified: renaming its own root returns "Operation not permitted"
    -- so this guards against another local process, not against the worker.

    Capture before dispatch and re-check with `assert_same_workspace` before trusting
    results.
    """
    st = os.stat(workspace)
    return (st.st_dev, st.st_ino)


def assert_same_workspace(workspace: str, expected: tuple[int, int]) -> None:
    actual = workspace_identity(workspace)
    if actual != expected:
        raise JailUnavailable(
            f"workspace identity changed after attestation: expected dev/ino {expected}, "
            f"found {actual}. The directory the jail was built for is not the directory "
            "now at that path. Refusing to trust this mission.")


def wrap(argv: list[str], spec: JailSpec) -> list[str]:
    """Return argv wrapped so the worker runs inside the jail.

    Every harness launch goes through here. There is intentionally no bypass parameter:
    an 'unjailed for debugging' flag is how boundaries end up disabled in production.
    """
    profile = render_profile(spec)
    return ["sandbox-exec", "-p", profile, *argv]
