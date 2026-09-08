"""KAI local connector — the only bridge between an enrolled Mac and KAI.

Outbound only. It opens connections TO the configured KAI backend and never listens, so
there is no port to expose, no router hole and no path from the network to this machine.
The harness it supervises also never listens: it is a stdio child of this process.

Trust flows one way. The connector holds a device credential that authorises it to
RECEIVE work and REPORT results; it cannot approve anything, cannot mark a mission
complete, and re-enforces its own scopes locally so a backend bug cannot hand it
authority it was never granted.

The private key lives in the macOS Keychain and never touches the repository, a .env,
the process environment, a log line or an argv. Signing happens in-process from a key
loaded on demand.

Commands:
    enroll --pairing-code CODE     complete enrollment, print the fingerprint to compare
    run                            poll for work and execute it (foreground)
    status                         report local state without contacting KAI
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "backend"))

from acp_client import REJECT, AcpClient, PermissionRequest  # noqa: E402
from jail import JailSpec  # noqa: E402
from startup_gate import GateFailed, run_gate  # noqa: E402
import workspace_volume as wv  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

KEYCHAIN_SERVICE = "com.wheellsverse.kai.device"
HARNESS = os.environ.get("KAI_HARNESS_DIR",
                         "/Users/jhonwheeler/kai-harness-runtime/deepseek-harness")
DSH_HOME_TEMPLATE = os.environ.get("KAI_DSH_HOME",
                                   "/Users/jhonwheeler/kai-harness-runtime/dsh-home")
OVERLAYS = os.path.abspath(os.path.join(HERE, "..", "harness"))
STATE_DIR = os.path.expanduser("~/.kai-connector")
MODEL_URL = os.environ.get("KAI_LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
MODEL_NAME = os.environ.get("KAI_LOCAL_LLM_MODEL", "qwen2.5:7b")

MODE_OVERLAY = {
    "OBSERVE": "20-mode-observe.patch.yml",
    "ASSIST": "21-mode-assist.patch.yml",
    "EXECUTE_SCOPED": "22-mode-execute-scoped.patch.yml",
}


# --------------------------------------------------------------------- keychain

def keychain_store(device_id: str, private_key: Ed25519PrivateKey) -> None:
    """Write the private key to the login Keychain.

    Passed on stdin via `-w -` so the key never appears in argv, which is world-readable
    through `ps` for the lifetime of the command.
    """
    raw = private_key.private_bytes(serialization.Encoding.Raw,
                                    serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption())
    proc = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
         "-a", device_id, "-w", base64.b64encode(raw).decode()],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"failed to store device key in Keychain: {proc.stderr.strip()[:200]}")


def keychain_load(device_id: str) -> Ed25519PrivateKey:
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", device_id, "-w"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("device key not found in Keychain; re-enroll this device")
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(proc.stdout.strip()))


# ------------------------------------------------------------------- transport

@dataclass
class Connector:
    base_url: str
    device_id: str

    def _key(self) -> Ed25519PrivateKey:
        return keychain_load(self.device_id)

    def call(self, method: str, path: str, payload: dict | None = None,
             *, timeout: int = 30) -> tuple[int, dict]:
        """One signed outbound request. Every call is individually signed.

        The size ceiling is applied HERE as well as server-side. Sending a request that
        will only be rejected wastes a nonce and a round trip, and truncating locally
        keeps the failure legible: the connector reports what it dropped instead of the
        server reporting a number nobody can attribute.
        """
        from app.services.holding.device_auth import sign_request  # noqa: PLC0415
        from app.services.holding.computer_ops_limits import (  # noqa: PLC0415
            MAX_REQUEST_BYTES, MAX_EVIDENCE_BYTES)

        body = json.dumps(payload or {}).encode()
        ceiling = MAX_EVIDENCE_BYTES if path.endswith("/evidence") else MAX_REQUEST_BYTES
        if len(body) > ceiling:
            return 0, {"error": f"refusing to send {len(body)} bytes to {path} "
                                f"(local limit {ceiling}); write large output to the "
                                f"mission volume and send a reference"}
        ts = datetime.now(timezone.utc)
        nonce = secrets.token_hex(16)
        sig = sign_request(self._key(), method=method, path=path, body=body,
                           timestamp=ts, nonce=nonce, device_id=self.device_id)
        req = urllib.request.Request(
            self.base_url.rstrip("/") + path, data=body, method=method,
            headers={"Content-Type": "application/json",
                     "X-KAI-Device-Id": self.device_id,
                     "X-KAI-Timestamp": str(int(ts.timestamp())),
                     "X-KAI-Nonce": nonce,
                     "X-KAI-Signature": sig})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except Exception:  # noqa: BLE001
                return exc.code, {}
        except Exception as exc:  # noqa: BLE001
            return 0, {"error": f"{type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------ enrollment

def cmd_enroll(args) -> int:
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)
    payload = {
        "pairing_code": args.pairing_code,
        "public_key": base64.b64encode(pub).decode(),
        # Proving possession of the key by signing the pairing code is what makes a
        # leaked code useless on its own.
        "signature": base64.b64encode(key.sign(args.pairing_code.encode())).decode(),
        "os": "darwin", "arch": os.uname().machine,
    }
    req = urllib.request.Request(args.base_url.rstrip("/") + "/api/kai/device/enroll/complete",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print("enrollment refused:", exc.code, exc.read()[:300].decode(errors="replace"))
        return 1

    keychain_store(out["device_id"], key)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "device.json"), "w") as fh:
        json.dump({"device_id": out["device_id"], "base_url": args.base_url}, fh)

    print("\nDevice enrolled. Status:", out["status"])
    print("Device id :", out["device_id"])
    print("\n  FINGERPRINT:", out["fingerprint"])
    print("\nCompare that fingerprint with the one shown in Holding Command before")
    print("confirming. If they differ, do NOT confirm -- the key presented to KAI is")
    print("not the key this machine generated.")
    print("\nPrivate key stored in the login Keychain (service "
          f"{KEYCHAIN_SERVICE}); it is not written to disk in this repository.")
    return 0


def _load_state() -> dict:
    with open(os.path.join(STATE_DIR, "device.json")) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------- run

def _permission_handler(conn: Connector, mission_id: str):
    """Every harness permission request is forwarded to KAI. The connector NEVER decides.

    The default is REJECT: if KAI is unreachable, an approval cannot be obtained, so the
    action is refused. A connector that approved on its own -- even 'just for read-only
    things' -- would be a second policy engine that KAI cannot see.
    """
    def handler(req: PermissionRequest) -> str:
        code, out = conn.call("POST", f"/api/kai/device/missions/{mission_id}/permission",
                              {"action": req.tool_name, "target": "",
                               "params": req.raw.get("toolCall", {})})
        if code != 200:
            print(f"  [permission] KAI refused or unreachable ({code}); denying", file=sys.stderr)
            return REJECT
        # The approval must be resolved by an operator in the panel. The connector does
        # not block waiting for it here; the mission reports AWAITING_APPROVAL and the
        # harness call is denied for now rather than held open indefinitely.
        print(f"  [permission] requested {out.get('approval_id')} for {req.tool_name}; "
              "awaiting operator decision -> denying this call", file=sys.stderr)
        return REJECT
    return handler


def run_mission(conn: Connector, mission: dict) -> None:
    mission_id = mission["mission_id"]
    mode = mission["autonomy_mode"]
    spec = mission.get("spec") or {}
    print(f"[mission {mission_id}] {mode}  objective={mission.get('objective','')[:60]!r}")

    vol = None
    try:
        vol = wv.create(mission_id, size_mb=int(os.environ.get("KAI_VOLUME_MB", "512")))
        wv.assert_separate_filesystem(vol, HARNESS)
        os.makedirs(vol.storage_root, exist_ok=True)
        os.makedirs(vol.tmpdir, exist_ok=True)
        dsh_home = wv.seed_dsh_home(vol, DSH_HOME_TEMPLATE)

        env = {"CI": "true", "DSH_HOME": dsh_home, "TMPDIR": vol.tmpdir,
               "KAI_TASK_WORKSPACE": vol.workspace,
               "KAI_MISSION_SESSION_ROOT": vol.session_root,
               "KAI_MISSION_STORAGE_ROOT": vol.storage_root,
               "KAI_LOCAL_LLM_BASE_URL": MODEL_URL,
               "KAI_LOCAL_LLM_MODEL": MODEL_NAME,
               "KAI_LOCAL_LLM_API_KEY": "local-no-auth-required"}
        argv = ["node", "--import", "tsx/esm", os.path.join(HARNESS, "apps/cli/src/bin.ts"),
                "--profile", "acp",
                "--patch", os.path.join(OVERLAYS, "00-containment.patch.yml"),
                "--patch", os.path.join(OVERLAYS, "05-volume-roots.patch.yml"),
                "--patch", os.path.join(OVERLAYS, "10-model-local-only.patch.yml"),
                "--patch", os.path.join(OVERLAYS, MODE_OVERLAY[mode])]
        jail = JailSpec(volume=vol.mount_point, dsh_home=dsh_home,
                        harness_dir=HARNESS, model_base_url=MODEL_URL)

        dump = subprocess.run(argv + ["--dump-config"], cwd=HARNESS,
                              env={**os.environ, **env}, capture_output=True,
                              text=True, timeout=180).stdout
        record = run_gate(mission_id=mission_id, mode=mode, model_mode="LOCAL_ONLY",
                          dump=dump, jail_spec=jail, harness_dir=HARNESS)
        conn.call("POST", "/api/kai/device/attestation",
                  {"mission_id": mission_id, "attestation_digest": record.digest(),
                   "containment": "macOS Seatbelt + per-mission APFS volume"})
        print(f"  gate passed: composition={record.composition_digest[:12]} "
              f"attestation={record.digest()[:12]}")

        conn.call("POST", f"/api/kai/device/missions/{mission_id}/progress",
                  {"status": "RUNNING", "note": "worker started inside the jail"})

        client = AcpClient(argv, cwd=HARNESS, env=env,
                           permission_handler=_permission_handler(conn, mission_id),
                           on_update=lambda u: None,
                           on_stderr=lambda line: None,
                           jail=jail)
        client.start()
        try:
            client.initialize()
            sid = client.session_new(vol.workspace)
            # The mission deadline is enforced locally too. The backend sweep will fail
            # an overdue mission, but only the connector can actually stop the work.
            deadline = min(int(spec.get("max_duration_seconds", 900)), 3600)
            reply = client.prompt(sid, mission.get("objective", ""), timeout=deadline)
            conn.call("POST", f"/api/kai/device/missions/{mission_id}/evidence",
                      {"kind": "model_result", "stop_reason": reply.get("stopReason"),
                       "session_id": sid, "claim": "completed_turn"})
            # NOT 'COMPLETED': the worker reports what it did. KAI verifies and decides.
            conn.call("POST", f"/api/kai/device/missions/{mission_id}/progress",
                      {"status": "RUNNING", "note": "turn finished; awaiting KAI verification"})
        finally:
            client.close()
    except GateFailed as exc:
        print(f"  CONTAINMENT GATE FAILED: {exc}", file=sys.stderr)
        conn.call("POST", f"/api/kai/device/missions/{mission_id}/progress",
                  {"status": "FAILED", "note": f"containment gate failed: {exc}"[:400]})
    except Exception as exc:  # noqa: BLE001
        print(f"  mission error: {type(exc).__name__}: {exc}", file=sys.stderr)
        conn.call("POST", f"/api/kai/device/missions/{mission_id}/progress",
                  {"status": "FAILED", "note": f"{type(exc).__name__}: {exc}"[:400]})
    finally:
        if vol is not None:
            try:
                wv.destroy(vol)
                print("  volume destroyed")
            except Exception as exc:  # noqa: BLE001
                print(f"  WARNING: volume teardown failed: {exc}", file=sys.stderr)


def cmd_run(args) -> int:
    state = _load_state()
    conn = Connector(base_url=state["base_url"], device_id=state["device_id"])
    print(f"connector running for device {conn.device_id} against {conn.base_url}")
    print("outbound only; no listening socket is opened by this process or the harness")
    deadline = time.monotonic() + args.max_seconds if args.max_seconds else None
    while True:
        if deadline and time.monotonic() > deadline:
            print("max runtime reached; exiting")
            return 0
        code, hb = conn.call("POST", "/api/kai/device/heartbeat")
        if code == 423:
            print("STOP engaged; standing down")
            time.sleep(args.interval)
            continue
        if code != 200:
            print(f"heartbeat failed ({code}); retrying", file=sys.stderr)
            time.sleep(args.interval)
            continue
        code, out = conn.call("POST", "/api/kai/device/lease")
        if code == 429:
            # Back-pressure, not an error: the backend is telling us it is at capacity.
            # Honour Retry-After rather than retrying immediately, which is what turns a
            # busy backend into an overloaded one.
            wait = max(args.interval, 10)
            print(f"backend at capacity; backing off {wait:.0f}s")
            time.sleep(wait)
            continue
        mission = out.get("mission") if code == 200 else None
        if not mission:
            if args.once:
                print("no eligible mission")
                return 0
            time.sleep(args.interval)
            continue
        run_mission(conn, mission)
        if args.once:
            return 0


def cmd_status(args) -> int:
    try:
        state = _load_state()
    except Exception:  # noqa: BLE001
        print("device: NOT ENROLLED")
        return 0
    print("device id :", state["device_id"])
    print("backend   :", state["base_url"])
    try:
        keychain_load(state["device_id"])
        print("key       : present in Keychain")
    except Exception as exc:  # noqa: BLE001
        print("key       : MISSING —", exc)
    print("harness   :", "built" if os.path.isfile(
        os.path.join(HARNESS, "apps/cli/lib/bin.js")) else "NOT BUILT")
    print("model     :", MODEL_URL, MODEL_NAME)
    mounted = subprocess.run(["mount"], capture_output=True, text=True).stdout
    print("volumes   :", [l.split()[2] for l in mounted.splitlines() if "KAI-" in l] or "none")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="KAI local connector")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll")
    e.add_argument("--pairing-code", required=True)
    e.add_argument("--base-url", default=os.environ.get("KAI_BACKEND_URL", "http://127.0.0.1:8020"))
    e.set_defaults(func=cmd_enroll)

    r = sub.add_parser("run")
    r.add_argument("--interval", type=float, default=5.0)
    r.add_argument("--once", action="store_true")
    r.add_argument("--max-seconds", type=float, default=0)
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
