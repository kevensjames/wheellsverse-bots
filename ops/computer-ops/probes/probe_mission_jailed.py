"""End-to-end: disposable mission volume + kernel jail + harness ACP round trip.

Proves the containment architecture does not break the thing it contains: the worker
still reaches the local model and answers, while confined to one filesystem with no
network except that model.
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "connector"))

from acp_client import REJECT, AcpClient, PermissionRequest  # noqa: E402
from jail import JailSpec  # noqa: E402
import workspace_volume as wv  # noqa: E402

HARNESS = "/Users/jhonwheeler/kai-harness-runtime/deepseek-harness"
DSH_HOME = "/Users/jhonwheeler/kai-harness-runtime/dsh-home"
OV = os.path.abspath(os.path.join(HERE, "..", "harness"))
MISSION_ID = "probe-jailed-001"

updates: list[dict] = []
stderr_lines: list[str] = []
asks: list[PermissionRequest] = []

vol = None
failures: list[str] = []
try:
    # Fresh disposable volume for this mission.
    try:
        wv.destroy(wv.MissionVolume(MISSION_ID,
                   f"/Users/jhonwheeler/kai-harness-runtime/volumes/{MISSION_ID}.sparseimage",
                   f"/Volumes/KAI-{MISSION_ID}"[:33]))
    except Exception:
        pass
    vol = wv.create(MISSION_ID, size_mb=256)
    print(f"[1] mission volume mounted: {vol.mount_point}")

    wv.assert_separate_filesystem(vol, HARNESS)
    print(f"[2] separate filesystem confirmed "
          f"(st_dev volume={os.stat(vol.mount_point).st_dev} != harness={os.stat(HARNESS).st_dev})")

    os.makedirs(vol.storage_root, exist_ok=True)
    os.makedirs(vol.tmpdir, exist_ok=True)
    mission_dsh_home = wv.seed_dsh_home(vol, DSH_HOME)
    print(f"[2b] per-mission DSH_HOME seeded on the volume: {mission_dsh_home}")

    env = {
        "CI": "true",
        "DSH_HOME": mission_dsh_home,
        "TMPDIR": vol.tmpdir,
        "KAI_TASK_WORKSPACE": vol.workspace,
        "KAI_MISSION_SESSION_ROOT": vol.session_root,
        "KAI_MISSION_STORAGE_ROOT": vol.storage_root,
        "KAI_LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "KAI_LOCAL_LLM_MODEL": "qwen2.5:7b",
        "KAI_LOCAL_LLM_API_KEY": "local-no-auth-required",
    }
    argv = [
        "node", "--import", "tsx/esm", os.path.join(HARNESS, "apps/cli/src/bin.ts"),
        "--profile", "acp",
        "--patch", os.path.join(OV, "00-containment.patch.yml"),
        "--patch", os.path.join(OV, "05-volume-roots.patch.yml"),
        "--patch", os.path.join(OV, "10-model-local-only.patch.yml"),
        "--patch", os.path.join(OV, "20-mode-observe.patch.yml"),
    ]
    jail = JailSpec(volume=vol.mount_point, dsh_home=mission_dsh_home,
                    harness_dir=HARNESS, model_base_url=env["KAI_LOCAL_LLM_BASE_URL"])

    client = AcpClient(argv, cwd=HARNESS, env=env,
                       permission_handler=lambda r: (asks.append(r), REJECT)[1],
                       on_update=updates.append, on_stderr=stderr_lines.append,
                       jail=jail)
    t0 = time.time()
    client.start()
    try:
        client.initialize()
        print("[3] initialize OK (worker running inside kernel jail)")
        sid = client.session_new(vol.workspace)
        print(f"[4] session/new OK  sessionId={sid}")
        reply = client.prompt(sid, "Reply with exactly the word: JAILED_LOCAL_OK", timeout=300)
        print(f"[5] session/prompt returned  stopReason={reply.get('stopReason')}")
        blob = repr(updates)
        if "JAILED_LOCAL_OK" in blob:
            print("[6] LOCAL MODEL ANSWERED FROM INSIDE THE JAIL: JAILED_LOCAL_OK")
        else:
            failures.append("model answer not found")
            for u in updates[:6]:
                print("     ", repr(u)[:220])
        client.cancel(sid)
        print(f"[7] session/cancel sent   elapsed={time.time()-t0:.1f}s")
    finally:
        client.close()

    # Session data must have landed on the mission volume, not the boot volume.
    on_volume = os.path.isdir(vol.session_root) and any(os.scandir(vol.session_root))
    print(f"[8] session data written to the mission volume: {on_volume}")
    if not on_volume:
        failures.append("session data did not land on the mission volume")

finally:
    if vol is not None:
        wv.destroy(vol)
        print(f"[9] volume destroyed; image removed: {not os.path.exists(vol.image_path)}")

print("\nRESULT:", "PASS" if not failures else f"FAIL {failures}")
sys.exit(1 if failures else 0)
