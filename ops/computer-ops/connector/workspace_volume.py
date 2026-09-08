"""Per-mission disposable workspace volume (APFS sparse image).

Why a separate filesystem rather than just a directory
------------------------------------------------------
macOS Seatbelt authorises by PATH. A hard link inside the workspace shares an inode with
its target outside it, so writing to an "in-workspace" path can modify an outside file.
Measured: `(deny file-write*)` does stop the WORKER creating such a link, but a link
planted by any other local process before the mission would still be honoured, and the
blanket `(deny file-link)` that would cover it also breaks the harness's atomic session
publish (write .tmp then link to the final name), so it is not usable.

Putting the workspace and the mission's session root on their own filesystem removes the
problem instead of policing it: hard links cannot cross filesystems, so `link()` from any
outside file returns EXDEV from the kernel. That is structural, not a rule that has to be
kept correct as upstream changes.

It also buys three things a directory cannot:
  * a hard size cap, so a runaway mission cannot exhaust the boot disk;
  * disposal that is genuinely complete -- detach and delete the image;
  * a clean evidence boundary, since everything the mission wrote is one artefact.

No sudo is required: `hdiutil create` / `attach -nobrowse` run as the user.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

#: Mission ids reach here from KAI; constrain them before they become paths and
#: `hdiutil` arguments.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


class VolumeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissionVolume:
    mission_id: str
    image_path: str
    mount_point: str

    @property
    def workspace(self) -> str:
        return os.path.join(self.mount_point, "workspace")

    @property
    def session_root(self) -> str:
        return os.path.join(self.mount_point, "sessions")

    @property
    def storage_root(self) -> str:
        return os.path.join(self.mount_point, "storages")

    @property
    def tmpdir(self) -> str:
        return os.path.join(self.mount_point, "tmp")

    @property
    def dsh_home(self) -> str:
        """Per-mission DSH_HOME. See seed_dsh_home() for why it is not shared."""
        return os.path.join(self.mount_point, "dsh-home")


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def create(mission_id: str, *, size_mb: int = 512,
           images_dir: str = "/Users/jhonwheeler/kai-harness-runtime/volumes") -> MissionVolume:
    """Create and attach a fresh volume for one mission.

    The volume name is derived from the mission id so an operator can see, in Finder or
    `mount`, exactly which mission owns a mounted filesystem.
    """
    if not _SAFE_ID.match(mission_id):
        raise VolumeError(f"unsafe mission id {mission_id!r}")
    os.makedirs(images_dir, exist_ok=True)
    image = os.path.join(images_dir, f"{mission_id}.sparseimage")
    if os.path.exists(image):
        raise VolumeError(f"volume image already exists for mission {mission_id}: {image}")

    volname = f"KAI-{mission_id}"[:27]
    made = _run(["hdiutil", "create", "-size", f"{size_mb}m", "-fs", "APFS",
                 "-volname", volname, "-type", "SPARSE", image])
    if made.returncode != 0:
        raise VolumeError(f"hdiutil create failed: {made.stderr.strip()[:300]}")

    attached = _run(["hdiutil", "attach", "-nobrowse", image])
    if attached.returncode != 0:
        raise VolumeError(f"hdiutil attach failed: {attached.stderr.strip()[:300]}")
    mount_point = ""
    for line in attached.stdout.splitlines():
        if "/Volumes/" in line:
            mount_point = line.split("\t")[-1].strip()
    if not mount_point or not os.path.isdir(mount_point):
        raise VolumeError(f"could not determine mount point from: {attached.stdout[:300]}")

    vol = MissionVolume(mission_id=mission_id, image_path=image, mount_point=mount_point)
    os.makedirs(vol.workspace, exist_ok=True)
    os.makedirs(vol.session_root, exist_ok=True)
    return vol


def seed_dsh_home(vol: MissionVolume, template: str) -> str:
    """Give the mission its own DSH_HOME on the volume, seeded from a template.

    The harness REWRITES its profile on every boot (`prepareProfile` writes
    `$DSH_HOME/profiles/<name>/cordis.yml`), so DSH_HOME must be writable. Leaving it on
    the boot volume would put a writable path outside the mission volume, and the whole
    reason every writable path lives on one separate filesystem is that it makes a
    cross-boundary hard link impossible rather than merely denied. So DSH_HOME moves
    onto the volume too.

    This is cheap -- the template is ~100 KB because `profiles/node_modules` is symlinks
    into the pinned harness install, which stays read-only -- and it means each mission
    boots a fresh profile with no state carried over from the last one.

    `cp -a` is used rather than shutil.copytree so those symlinks are preserved as
    symlinks instead of being dereferenced into a full dependency copy.
    """
    dest = vol.dsh_home
    os.makedirs(dest, exist_ok=True)
    for entry in os.listdir(template):
        # sessions/ and storages/ are re-rooted onto the volume by overlay, so a stale
        # copy would only be confusing.
        if entry in ("sessions", "storages"):
            continue
        r = _run(["cp", "-a", os.path.join(template, entry), dest])
        if r.returncode != 0:
            raise VolumeError(f"failed to seed DSH_HOME entry {entry!r}: {r.stderr.strip()[:200]}")
    return dest


def assert_separate_filesystem(vol: MissionVolume, outside_path: str) -> None:
    """Prove the volume really is a different filesystem before trusting EXDEV.

    An image that silently failed to mount would leave the workspace on the boot volume,
    where the hard-link escape is live again. Checking st_dev makes that a startup
    failure rather than an invisible downgrade.
    """
    if os.stat(vol.mount_point).st_dev == os.stat(outside_path).st_dev:
        raise VolumeError(
            f"mission volume {vol.mount_point} is on the SAME filesystem as {outside_path}; "
            "cross-device link protection would not apply. Refusing to run.")


def destroy(vol: MissionVolume, *, keep_image: bool = False) -> None:
    """Detach and (by default) delete. Disposal is the point of the design.

    `keep_image` retains the image for evidence capture; the caller is then responsible
    for its lifecycle and for the fact that it contains mission output.
    """
    det = _run(["hdiutil", "detach", vol.mount_point, "-force"])
    if det.returncode != 0 and os.path.ismount(vol.mount_point):
        raise VolumeError(f"failed to detach {vol.mount_point}: {det.stderr.strip()[:200]}")
    if not keep_image and os.path.exists(vol.image_path):
        os.remove(vol.image_path)
