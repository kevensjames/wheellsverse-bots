"""Live proof: KAI drives the pinned harness over ACP against a LOCAL model only.

Run directly. Prints an evidence block; exits non-zero on failure.
Note stdout is reserved for ACP JSON-RPC, so the harness is launched via node
directly rather than through `pnpm dsh` (pnpm echoes a `$ ...` banner to stdout,
which would corrupt the protocol stream).
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "connector"))

from acp_client import REJECT, AcpClient, PermissionRequest  # noqa: E402
from jail import JailSpec  # noqa: E402

HARNESS = "/Users/jhonwheeler/kai-harness-runtime/deepseek-harness"
DSH_HOME = "/Users/jhonwheeler/kai-harness-runtime/dsh-home"
WORKSPACE = "/Users/jhonwheeler/kai-harness-runtime/workspaces/probe"
OVERLAYS = os.path.join(HERE, "..", "harness")

os.makedirs(WORKSPACE, exist_ok=True)

updates: list[dict] = []
stderr_lines: list[str] = []
permission_asks: list[PermissionRequest] = []


def deny_everything(req: PermissionRequest) -> str:
    """OBSERVE mode: every permission request is denied by KAI, deterministically."""
    permission_asks.append(req)
    return REJECT


argv = [
    "node", "--import", "tsx/esm", os.path.join(HARNESS, "apps/cli/src/bin.ts"),
    "--profile", "acp",
    "--patch", os.path.join(OVERLAYS, "00-containment.patch.yml"),
    "--patch", os.path.join(OVERLAYS, "10-model-local-only.patch.yml"),
    "--patch", os.path.join(OVERLAYS, "20-mode-observe.patch.yml"),
]

env = {
    "CI": "true",
    "DSH_HOME": DSH_HOME,
    "KAI_TASK_WORKSPACE": WORKSPACE,
    "KAI_LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
    "KAI_LOCAL_LLM_MODEL": "qwen2.5:7b",
    # Placeholder credential: the local endpoint requires no authentication. Never a
    # real cloud key -- LOCAL_ONLY must not carry one into the child environment.
    "KAI_LOCAL_LLM_API_KEY": "local-no-auth-required",
    # Prove no cloud credential is even present in the child's environment.
    "DEEPSEEK_API_KEY": "",
}

# The worker runs inside the kernel jail. Plugin removal is defence in depth; this is
# the boundary. AcpClient refuses to spawn unconfined unless a probe says so explicitly.
JAIL = JailSpec(workspace=WORKSPACE,
                dsh_home=DSH_HOME,
                harness_dir=HARNESS,
                model_base_url=env["KAI_LOCAL_LLM_BASE_URL"],
                tmpdir="/tmp/kai-jail")

client = AcpClient(
    argv, cwd=HARNESS, env=env,
    permission_handler=deny_everything,
    on_update=updates.append,
    on_stderr=stderr_lines.append,
    jail=JAIL,
)

t0 = time.time()
failures: list[str] = []
try:
    client.start()
    init = client.initialize()
    print(f"[1] initialize OK  protocolVersion={init.get('protocolVersion')}")

    sid = client.session_new(WORKSPACE)
    print(f"[2] session/new OK  sessionId={sid}")

    reply = client.prompt(sid, "Reply with exactly the word: HARNESS_LOCAL_OK", timeout=300)
    print(f"[3] session/prompt returned  stopReason={reply.get('stopReason')}")

    text = "".join(
        b.get("text", "")
        for u in updates
        for b in ([u.get("update", {}).get("content")] if isinstance(u.get("update", {}).get("content"), dict) else [])
        if isinstance(b, dict)
    )
    blob = repr(updates)[:4000]
    print(f"[4] session/update frames received: {len(updates)}")
    if "HARNESS_LOCAL_OK" in blob or "HARNESS_LOCAL_OK" in text:
        print("[5] LOCAL MODEL ANSWERED THROUGH THE HARNESS: HARNESS_LOCAL_OK found")
    else:
        failures.append("model answer not found in session/update stream")
        print("[5] answer text not located; first frames follow for diagnosis:")
        for u in updates[:6]:
            print("    ", repr(u)[:300])

    client.cancel(sid)
    print("[6] session/cancel sent (STOP path exercised)")
finally:
    client.close()

print(f"\nelapsed={time.time()-t0:.1f}s  permission_requests={len(permission_asks)}")
if stderr_lines:
    print("--- harness stderr (last 15) ---")
    for line in stderr_lines[-15:]:
        print("   ", line)

print("\nRESULT:", "PASS" if not failures else "FAIL")
for f in failures:
    print("  !", f)
sys.exit(1 if failures else 0)
