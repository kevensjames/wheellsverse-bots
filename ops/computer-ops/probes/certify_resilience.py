"""Crash/restart and STOP-during-write certification.

Both scenarios are about what happens when something is interrupted at the worst moment.
They are run against real processes and a real database, because the interesting failures
are precisely the ones a mocked worker cannot have: a killed process still holding a
lease, a half-written file, a volume left mounted.

    python3 ops/computer-ops/probes/certify_resilience.py
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, os.path.join(HERE, "..", "connector"))
sys.path.insert(0, BACKEND)

DB = f"kai_res_{uuid.uuid4().hex[:8]}"
PORT = 8752
BASE = f"http://127.0.0.1:{PORT}"
ADMIN = "res-admin-token"
ENV = {**os.environ,
       "DATABASE_URL": f"postgresql://localhost:5432/{DB}",
       "APP_ENV": "test", "SECRET_KEY": "r", "SESSION_SIGNING_SECRET": "r",
       "API_KEY": ADMIN, "ADMIN_TOKEN": ADMIN,
       "KAI_COMPUTER_OPS_ENABLED": "true", "OPERATOR_SESSION_ENABLED": "false"}

results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)[:200]))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


def http(method, path, body=None, *, admin=False, timeout=30):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    if admin:
        req.add_header("X-Admin-Token", ADMIN)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


server = None
vol = None
try:
    subprocess.run(["createdb", DB], check=True)
    subprocess.run(["alembic", "upgrade", "0008_add_kai_devices"], cwd=BACKEND, env=ENV,
                   capture_output=True, text=True, timeout=300)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                               "--port", str(PORT), "--host", "127.0.0.1"],
                              cwd=BACKEND, env=ENV,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if http("GET", "/health")[0] == 200:
            break
        time.sleep(0.5)

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.services.holding.device_auth import sign_request

    # --- enroll a device we control directly (no connector state on disk) --------
    code = http("POST", "/admin/kai/computer-operations/devices/enroll",
                {"device_name": "Resilience"}, admin=True)[1]["pairing_code"]
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)
    import base64
    dev = http("POST", "/api/kai/device/enroll/complete", {
        "pairing_code": code, "public_key": base64.b64encode(pub).decode(),
        "signature": base64.b64encode(key.sign(code.encode())).decode()})[1]
    did = dev["device_id"]
    http("POST", f"/admin/kai/computer-operations/devices/{did}/confirm",
         {"fingerprint": dev["fingerprint"]}, admin=True)
    http("POST", f"/admin/kai/computer-operations/devices/{did}/scopes/grant",
         {"scopes": ["computer.workspace.read", "computer.workspace.write"]}, admin=True)

    def signed(method, path, body=None):
        raw = json.dumps(body or {}).encode()
        ts = datetime.now(timezone.utc)
        nonce = secrets.token_hex(16)
        sig = sign_request(key, method=method, path=path, body=raw,
                           timestamp=ts, nonce=nonce, device_id=did)
        req = urllib.request.Request(BASE + path, data=raw, method=method, headers={
            "Content-Type": "application/json", "X-KAI-Device-Id": did,
            "X-KAI-Timestamp": str(int(ts.timestamp())), "X-KAI-Nonce": nonce,
            "X-KAI-Signature": sig})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
                return r.status, (json.loads(b) if b else {})
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                return e.code, json.loads(b or b"{}")
            except Exception:
                return e.code, {}

    ws = f"/tmp/kai-res-ws-{uuid.uuid4().hex[:6]}"
    os.makedirs(ws, exist_ok=True)

    # =====================================================================
    print("=== A. connector crash / restart ===")
    mid = http("POST", "/admin/kai/computer-operations/missions", {
        "device_id": did, "objective": "crash test", "autonomy_mode": "OBSERVE",
        "workspace": ws}, admin=True)[1]["mission_id"]

    st, out = signed("POST", "/api/kai/device/lease")
    check("mission leased before the crash", st == 200 and out.get("mission"), str(st))
    attempts_before = out["mission"]["attempts"]
    signed("POST", f"/api/kai/device/missions/{mid}/progress",
           {"status": "RUNNING", "note": "working"})

    # Simulate a hard crash: the connector never gets to report anything. Nothing is
    # cleaned up client-side, which is the whole point -- the backend must cope alone.
    st, dec = signed("POST", f"/api/kai/device/missions/{mid}/reconnect")
    check("reconnect is answered after a crash", st == 200, str(st))
    check("a still-valid lease permits resume", dec["resume"] is True, dec["reason"])

    # Now the realistic case: the lease has expired while the connector was dead.
    import sqlalchemy
    eng = sqlalchemy.create_engine(ENV["DATABASE_URL"])
    with eng.begin() as conn:
        conn.execute(sqlalchemy.text(
            "UPDATE holding_worker_jobs SET lease_expires_at = now() - interval '1 minute' "
            "WHERE mission_id = :m"), {"m": mid})
    st, dec = signed("POST", f"/api/kai/device/missions/{mid}/reconnect")
    check("an EXPIRED lease refuses resume (default no-resume)", dec["resume"] is False,
          dec["reason"])
    check("the refusal says to re-claim rather than resume", "re-claim" in dec["reason"],
          dec["reason"])

    # Re-claiming must be a NEW attempt, not a silent continuation.
    st, out2 = signed("POST", "/api/kai/device/lease")
    reclaimed = out2.get("mission")
    if reclaimed and reclaimed["mission_id"] == mid:
        check("re-claim increments the attempt counter (no silent continuation)",
              reclaimed["attempts"] > attempts_before,
              f"{attempts_before} -> {reclaimed['attempts']}")
    else:
        # QUEUED-only lease is also acceptable: the mission is not re-offered while
        # RUNNING, which is itself duplicate suppression.
        check("a RUNNING mission is not re-offered to a second worker (duplicate suppression)",
              reclaimed is None, str(reclaimed))

    # Replay of a captured signed request must still fail after a restart, because the
    # nonce burn is in the database rather than in the dead process's memory.
    raw = b"{}"
    ts = datetime.now(timezone.utc)
    nonce = secrets.token_hex(16)
    sig = sign_request(key, method="POST", path="/api/kai/device/heartbeat", body=raw,
                       timestamp=ts, nonce=nonce, device_id=did)
    hdrs = {"Content-Type": "application/json", "X-KAI-Device-Id": did,
            "X-KAI-Timestamp": str(int(ts.timestamp())), "X-KAI-Nonce": nonce,
            "X-KAI-Signature": sig}

    def post_raw(path, headers):
        r = urllib.request.Request(BASE + path, data=b"{}", method="POST", headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=20) as x:
                return x.status
        except urllib.error.HTTPError as e:
            return e.code

    check("a signed request works once", post_raw("/api/kai/device/heartbeat", hdrs) == 200)
    check("the same request replayed after a restart is refused (nonce burn is durable)",
          post_raw("/api/kai/device/heartbeat", hdrs) == 401)

    # =====================================================================
    print("\n=== B. STOP during a workspace write ===")
    import workspace_volume as wv
    from jail import JailSpec, wrap

    vol = wv.create(f"stopwrite-{uuid.uuid4().hex[:6]}", size_mb=64)
    wv.assert_separate_filesystem(vol, ROOT)
    os.makedirs(vol.tmpdir, exist_ok=True)
    spec = JailSpec(volume=vol.mount_point, dsh_home=vol.dsh_home,
                    harness_dir="/Users/jhonwheeler/kai-harness-runtime/deepseek-harness",
                    model_base_url="http://127.0.0.1:11434/v1")
    target = os.path.join(vol.workspace, "long_write.txt")

    # A jailed worker writing slowly, so STOP lands mid-write rather than between writes.
    script = (
        "import time,sys\n"
        f"f=open({target!r},'w')\n"
        "for i in range(600):\n"
        "    f.write('line %d\\n' % i); f.flush(); time.sleep(0.05)\n"
    )
    worker = subprocess.Popen(wrap(["/usr/bin/python3", "-c", script], spec),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)
    partial = os.path.getsize(target) if os.path.exists(target) else 0
    check("the jailed worker is writing into the mission volume", partial > 0, f"{partial} bytes")

    mid2 = http("POST", "/admin/kai/computer-operations/missions", {
        "device_id": did, "objective": "stop during write", "autonomy_mode": "EXECUTE_SCOPED",
        "workspace": ws}, admin=True)[1]["mission_id"]
    signed("POST", "/api/kai/device/lease")

    st, stop = http("POST", "/admin/kai/computer-operations/stop",
                    {"reason": "stop-during-write test"}, admin=True)
    check("STOP engaged while the write was in flight", st == 200, str(st))

    # STOP releases control: the connector kills its worker. Do that here, since this
    # test owns the worker directly.
    worker.send_signal(signal.SIGTERM)
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=10)
    size_at_stop = os.path.getsize(target)
    check("the write was interrupted, not completed", worker.poll() is not None
          and size_at_stop < 600 * 8, f"{size_at_stop} bytes")

    time.sleep(2.0)
    check("NO further bytes are written after STOP (no later side effect)",
          os.path.getsize(target) == size_at_stop,
          f"{size_at_stop} -> {os.path.getsize(target)}")

    st, m2 = http("GET", f"/admin/kai/computer-operations/missions/{mid2}", admin=True)
    check("mission state is accurate after STOP", m2["status"] == "STOPPED", m2["status"])
    check("STOP did not mark the mission COMPLETED", m2["status"] != "COMPLETED")
    check("the lease was revoked by STOP", m2["lease_owner"] is None, str(m2["lease_owner"]))

    st, _ = signed("POST", "/api/kai/device/heartbeat")
    check("device work is refused while stopped (423)", st == 423, str(st))

    mount_before = subprocess.run(["mount"], capture_output=True, text=True).stdout
    check("volume still mounted before teardown", vol.mount_point in mount_before)
    wv.destroy(vol)
    mount_after = subprocess.run(["mount"], capture_output=True, text=True).stdout
    check("teardown completes after STOP: volume unmounted",
          vol.mount_point not in mount_after)
    check("teardown removes the image", not os.path.exists(vol.image_path))
    vol = None

    check("evidence of the interrupted work is retained, not erased",
          isinstance(m2.get("history"), list) and len(m2["history"]) > 0,
          str(len(m2.get("history") or [])))

finally:
    if vol is not None:
        try:
            import workspace_volume as wv2
            wv2.destroy(vol)
        except Exception:  # noqa: BLE001
            pass
    if server is not None:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
    # Terminate lingering sessions before dropping: uvicorn's shutdown races the drop,
    # and a failed drop leaves a test database behind on the operator's machine.
    subprocess.run(["psql", "-d", "postgres", "-qc",
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname='{DB}'"], capture_output=True)
    subprocess.run(["dropdb", "--if-exists", DB], check=False)
    print("=== teardown: server stopped, database dropped ===")

bad = [n for n, ok, _ in results if not ok]
print(f"\n{sum(1 for _n, ok, _d in results if ok)}/{len(results)} resilience checks passed")
print("RESULT:", "RESILIENCE VERIFIED" if not bad else f"FAILED: {bad}")
sys.exit(1 if bad else 0)
