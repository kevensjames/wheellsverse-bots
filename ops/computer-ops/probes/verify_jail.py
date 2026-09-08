"""Behavioural containment tests for the harness worker jail.

Deliberately NOT a named-plugin scan. Every check here performs a real operation from
inside the jail and observes whether the kernel permitted it. That is the lesson of the
previous phase: an attestation that the right plugins were disabled passed 23/23 while
the model was executing shell commands with zero approvals.

Layout:
  A. Process-level enforcement -- run real binaries in the jail and observe.
  C. Path-canonicalisation attacks -- symlink, hardlink, env expansion, workspace swap.
(Model-driven path tests live in verify_model_paths.py, which is slower.)

Exit non-zero if ANY containment property fails.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "connector"))
from jail import (JailSpec, JailUnavailable, assert_same_workspace,  # noqa: E402
                  assert_workspace_hygiene, preflight, wrap, workspace_identity)

import workspace_volume as wv  # noqa: E402

HOME = os.path.expanduser("~")
MISSION_ID = "jailtest"

# The jail is defined against a real per-mission volume, because the volume being a
# SEPARATE FILESYSTEM is itself one of the containment properties under test.
try:
    wv.destroy(wv.MissionVolume(MISSION_ID,
               f"/Users/jhonwheeler/kai-harness-runtime/volumes/{MISSION_ID}.sparseimage",
               f"/Volumes/KAI-{MISSION_ID}"))
except Exception:
    pass
VOL = wv.create(MISSION_ID, size_mb=128)
WS = VOL.workspace
os.makedirs(VOL.tmpdir, exist_ok=True)

SPEC = JailSpec(volume=VOL.mount_point,
                dsh_home=VOL.dsh_home,
                harness_dir="/Users/jhonwheeler/kai-harness-runtime/deepseek-harness",
                model_base_url="http://127.0.0.1:11434/v1")

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def jailed(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(wrap(cmd, SPEC), capture_output=True, text=True, timeout=timeout)


print("=== preflight ===")
preflight(SPEC)
check("jail profile accepted and enforcing", True)
check("mission volume is a separate filesystem (EXDEV protects hard links)",
      os.stat(VOL.mount_point).st_dev != os.stat(HOME).st_dev,
      f"volume dev={os.stat(VOL.mount_point).st_dev} home dev={os.stat(HOME).st_dev}")

print("\n=== A. network enforcement ===")
# NOTE: probes use python3, NOT curl. The profile exec-denies /usr/bin/curl, so a
# curl-based network probe measures the exec denial and would "pass" even if the
# network were wide open. An earlier revision of this file made exactly that mistake.
NET_PROBE = (
    "import urllib.request,sys\n"
    "def go(u):\n"
    "    try: return str(urllib.request.urlopen(u, timeout=%d).status)\n"
    "    except Exception as e: return 'DENIED:'+type(e).__name__\n"
    "print(go(sys.argv[1]))\n"
)


def net(url: str, timeout: int = 8) -> str:
    r = jailed(["/usr/bin/python3", "-c", NET_PROBE % timeout, url], timeout=timeout + 12)
    return (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "NO_OUTPUT"


out = net("https://example.com")
check("external HTTPS egress denied", out.startswith("DENIED"), f"probe={out!r}")

out = net("http://127.0.0.1:11434/api/tags", timeout=6)
check("approved local model endpoint reachable", out == "200", f"probe={out!r}")

listener = subprocess.Popen([sys.executable, "-m", "http.server", "9998", "--bind", "127.0.0.1"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.2)
try:
    un = subprocess.run(["/usr/bin/python3", "-c", NET_PROBE % 4, "http://127.0.0.1:9998/"],
                        capture_output=True, text=True, timeout=20).stdout.strip()
    jd = net("http://127.0.0.1:9998/", timeout=5)
    check("non-approved loopback port denied while a listener is running",
          un == "200" and jd.startswith("DENIED"), f"unsandboxed={un!r} jailed={jd!r}")
finally:
    listener.terminate()
    listener.wait(timeout=5)

print("\n=== A. credential reads ===")
for label, path in (("~/.ssh", f"{HOME}/.ssh"), ("~/.aws", f"{HOME}/.aws"),
                    ("Keychains", f"{HOME}/Library/Keychains")):
    exists = os.path.exists(path)
    r = jailed(["/bin/ls", path])
    # Denied reads surface as a non-zero exit; a path that does not exist is not evidence.
    check(f"read {label} denied", r.returncode != 0,
          "path absent on host - vacuous" if not exists else f"rc={r.returncode}")

print("\n=== A. write confinement ===")
outside = f"{HOME}/.kai_jail_write_probe"
jailed(["/bin/sh", "-c", f"echo x > {outside}"])
check("write outside workspace denied", not os.path.exists(outside))
if os.path.exists(outside):
    os.remove(outside)

inside = os.path.join(WS, "allowed.txt")
if os.path.exists(inside):
    os.remove(inside)
jailed(["/bin/sh", "-c", f"echo ok > {inside}"])
check("write inside mission workspace allowed", os.path.exists(inside))

print("\n=== A. desktop / secret binaries ===")
for label, path in (("screencapture", "/usr/sbin/screencapture"),
                    ("osascript", "/usr/bin/osascript"),
                    ("security(keychain)", "/usr/bin/security")):
    r = jailed([path, "--help"] if label != "screencapture"
               else [path, "-x", "-R", "0,0,1,1", os.path.join(VOL.tmpdir, "s.png")])
    denied = r.returncode != 0 and "not permitted" in (r.stderr or "").lower()
    check(f"exec {label} denied", denied, f"rc={r.returncode} err={(r.stderr or '').strip()[:60]}")

print("\n=== C. path canonicalisation attacks (worker capabilities) ===")
# C1: a symlink inside the workspace pointing outside it must not become a write path.
link = os.path.join(WS, "escape_link")
target_dir = os.path.join(HOME, ".kai_jail_symlink_target")
os.makedirs(target_dir, exist_ok=True)
if os.path.islink(link) or os.path.exists(link):
    os.remove(link)
os.symlink(target_dir, link)
jailed(["/bin/sh", "-c", f"echo pwned > {os.path.join(link, 'pwned.txt')}"])
real_victim = os.path.join(target_dir, "pwned.txt")
check("symlink escape from workspace denied", not os.path.exists(real_victim))
if os.path.exists(real_victim):
    os.remove(real_victim)
os.remove(link)

# C2: the WORKER must not be able to create a hard link from an outside file into its
# workspace. That is the reachable attack; a link planted by another process before the
# mission is covered by C3.
src = os.path.join(HOME, ".kai_jail_hardlink_src")
with open(src, "w") as fh:
    fh.write("original\n")
r = jailed(["/usr/bin/python3", "-c",
            f"import os\ntry:\n os.link({src!r}, {os.path.join(WS,'hl.txt')!r})\n print('CREATED')\n"
            f"except OSError as e:\n print('DENIED', e.strerror)"])
worker_out = (r.stdout or "").strip()
# Expect EXDEV ("Cross-device link"): the escape is structurally impossible because the
# workspace is on its own filesystem, not merely refused by a policy rule that could be
# edited away. A plain "Operation not permitted" would mean we are relying on the rule.
check("worker cannot hardlink an outside file into its workspace",
      worker_out.startswith("DENIED"), f"probe={worker_out!r}")
# The sandbox rule fires before the kernel reaches EXDEV, so the worker sees
# "Operation not permitted". Assert the STRUCTURAL barrier separately, unsandboxed:
# even with full host privileges the link is impossible across the filesystem boundary.
# That is what makes the guarantee independent of the policy staying correct.
_x = subprocess.run(["/usr/bin/python3", "-c",
                     f"import os\ntry:\n os.link({src!r}, {os.path.join(WS,'xdev.txt')!r})\n print('CREATED')\n"
                     f"except OSError as e:\n print('DENIED', e.strerror)"],
                    capture_output=True, text=True).stdout.strip()
check("hardlink barrier is structural (EXDEV) even without the sandbox",
      "Cross-device" in _x, f"unsandboxed probe={_x!r}")
for p_ in (src, os.path.join(WS, "hl.txt")):
    if os.path.exists(p_):
        os.remove(p_)

# C3: planting a hard link in the workspace from OUTSIDE it is now impossible, because
# the workspace lives on its own filesystem. Previously this was the one hard-link path
# the worker rules could not close; it is now closed by the kernel, with full host
# privileges, which is strictly stronger than a policy rule.
planted_src = os.path.join(HOME, ".kai_planted_src")
with open(planted_src, "w") as fh:
    fh.write("victim\n")
try:
    os.link(planted_src, os.path.join(WS, "planted_hl.txt"))
    check("planting a hardlink into the workspace from outside is impossible", False,
          "a cross-boundary hard link was created")
    os.remove(os.path.join(WS, "planted_hl.txt"))
except OSError as exc:
    check("planting a hardlink into the workspace from outside is impossible",
          exc.errno == 18, f"errno={exc.errno} ({exc.strerror})")
finally:
    if os.path.exists(planted_src):
        os.remove(planted_src)

# C3b: the hygiene check itself must still reject a workspace containing a hard link,
# for any future deployment where the workspace is NOT on its own filesystem.
same_fs = os.path.join(VOL.workspace, "hygiene_probe")
os.makedirs(same_fs, exist_ok=True)
a = os.path.join(same_fs, "a.txt")
with open(a, "w") as fh:
    fh.write("x\n")
os.link(a, os.path.join(same_fs, "b.txt"))
try:
    assert_workspace_hygiene(same_fs)
    check("workspace hygiene rejects a hardlinked file", False, "hygiene accepted it")
except JailUnavailable as exc:
    check("workspace hygiene rejects a hardlinked file", "st_nlink" in str(exc), str(exc)[:60])

# C4: environment expansion must not widen the jail (profile is rendered from realpaths).
subprocess.run(wrap(["/bin/sh", "-c", "echo x > $HOME/.kai_env_probe"], SPEC),
               capture_output=True, text=True, env={**os.environ, "HOME": WS})
check("env-var expansion cannot widen the jail",
      not os.path.exists(os.path.join(HOME, ".kai_env_probe")))

# C5: the worker must not be able to replace its own workspace root. This is what makes
# the post-attestation swap unreachable FROM THE WORKER; an external local process is
# covered by C6.
r = jailed(["/usr/bin/python3", "-c",
            f"import os\ntry:\n os.rename({WS!r}, {WS + '_moved'!r})\n print('RENAMED')\n"
            f"except OSError as e:\n print('DENIED', e.strerror)"])
worker_out = (r.stdout or "").strip()
check("worker cannot replace its own workspace root", worker_out.startswith("DENIED"),
      f"probe={worker_out!r}")
if os.path.exists(WS + "_moved"):
    os.rename(WS + "_moved", WS)

# C6: if some other local process DOES repoint the workspace path after attestation,
# the identity binding must detect it. Seatbelt authorises the resolved path, so this is
# defence in depth rather than the primary control.
ident = workspace_identity(WS)
swap = "/tmp/kai_ws_swap_target"
os.makedirs(swap, exist_ok=True)
moved = WS + "_stash"
try:
    os.rename(WS, moved)
    os.symlink(swap, WS)
    try:
        assert_same_workspace(WS, ident)
        check("external workspace swap detected by identity binding", False,
              "identity check accepted a swapped workspace")
    except JailUnavailable as exc:
        check("external workspace swap detected by identity binding",
              "identity changed" in str(exc), str(exc)[:60])
finally:
    if os.path.islink(WS):
        os.remove(WS)
    if os.path.exists(moved):
        os.rename(moved, WS)

wv.destroy(VOL)
print(f"\nmission volume destroyed; image removed: {not os.path.exists(VOL.image_path)}")

print("\n" + "=" * 62)
passed = sum(1 for _, ok, _ in results if ok)
print(f"{passed}/{len(results)} containment properties hold")
bad = [n for n, ok, _ in results if not ok]
print("RESULT:", "JAIL CONTAINMENT VERIFIED" if not bad else f"FAILED: {bad}")
sys.exit(1 if bad else 0)
