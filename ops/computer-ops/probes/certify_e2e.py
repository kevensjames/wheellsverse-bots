"""End-to-end local certification: panel API -> live HTTP -> database -> real connector
-> kernel jail -> pinned harness -> local model.

Nothing here is mocked. It starts a real uvicorn server against a disposable Postgres,
enrolls a real device through the real connector binary (which stores its key in the
Keychain and signs every request), and runs a real mission that ends at a local model
inside the Seatbelt jail on its own APFS volume.

A unit-test count is not certification. This is the path an operator would actually take.

    python3 ops/computer-ops/probes/certify_e2e.py
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
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
CONNECTOR = os.path.join(HERE, "..", "connector", "kai_connector.py")
sys.path.insert(0, os.path.join(HERE, "..", "connector"))
sys.path.insert(0, BACKEND)

DB = f"kai_e2e_{uuid.uuid4().hex[:8]}"
PORT = 8731
BASE = f"http://127.0.0.1:{PORT}"
ADMIN = "e2e-admin-token"
WS = f"/tmp/kai-e2e-repo-{uuid.uuid4().hex[:6]}"

ENV = {**os.environ,
       "DATABASE_URL": f"postgresql://localhost:5432/{DB}",
       "APP_ENV": "test", "SECRET_KEY": "e2e", "SESSION_SIGNING_SECRET": "e2e",
       "API_KEY": ADMIN, "ADMIN_TOKEN": ADMIN,
       "KAI_COMPUTER_OPS_ENABLED": "true",
       "OPERATOR_SESSION_ENABLED": "false"}

results: list[tuple[str, bool, str]] = []
EVIDENCE: list[dict] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    EVIDENCE.append({"check": name, "pass": bool(ok), "detail": str(detail)[:300],
                     "at": datetime.now(timezone.utc).isoformat()})
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
            return e.code, {"_raw": raw[:200].decode(errors="replace")}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


server = None
try:
    print(f"=== disposable database {DB}, server on {PORT} ===")
    subprocess.run(["createdb", DB], check=True)
    m = subprocess.run(["alembic", "upgrade", "0008_add_kai_devices"], cwd=BACKEND,
                       env=ENV, capture_output=True, text=True, timeout=300)
    check("migrations applied through 0008", m.returncode == 0,
          m.stderr.strip().splitlines()[-1][:100] if m.returncode else "")

    os.makedirs(WS, exist_ok=True)
    with open(os.path.join(WS, "README.md"), "w") as fh:
        fh.write("# synthetic test repository\n\nOne file. Nothing real.\n")

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--host", "127.0.0.1"],
        cwd=BACKEND, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        code, _ = http("GET", "/health")
        if code == 200:
            break
        time.sleep(0.5)
    code, health = http("GET", "/health")
    check("live server healthy", code == 200 and health.get("status") in ("ok", "degraded"),
          f"{code} {health.get('status')}")
    check("computer_operations subsystem READY",
          health.get("subsystems", {}).get("computer_operations", {}).get("state") == "READY",
          json.dumps(health.get("subsystems", {}).get("computer_operations", {})))

    # ---- 27. anonymous access to every admin JSON route -------------------
    print("\n--- anonymous access ---")
    anon_leaks = []
    for p in ("/admin/kai/computer-operations/devices",
              "/admin/kai/computer-operations/missions",
              "/admin/kai/computer-operations/runtime",
              "/admin/capabilities"):
        c, b = http("GET", p)
        if c == 200 and b and b != {}:
            anon_leaks.append((p, c))
    c, _ = http("POST", "/admin/kai/computer-operations/stop", {})
    if c == 200:
        anon_leaks.append(("/stop", c))
    check("anonymous sensitive admin responses = 0", not anon_leaks, str(anon_leaks))

    # ---- 1-2. enroll, and prove it grants nothing -------------------------
    print("\n--- enrollment ---")
    c, enr = http("POST", "/admin/kai/computer-operations/devices/enroll",
                  {"device_name": "E2E Test Mac"}, admin=True)
    check("operator created an enrollment", c == 200, str(c))
    pairing = enr["pairing_code"]

    r = subprocess.run([sys.executable, CONNECTOR, "enroll", "--pairing-code", pairing,
                        "--base-url", BASE], capture_output=True, text=True, timeout=120)
    check("real connector completed enrollment", r.returncode == 0,
          (r.stderr or r.stdout).strip()[-160:])
    fp = ""
    for line in r.stdout.splitlines():
        if "FINGERPRINT:" in line:
            fp = line.split("FINGERPRINT:")[1].strip()
    check("connector printed a fingerprint to compare", bool(fp), fp)

    c, devs = http("GET", "/admin/kai/computer-operations/devices", admin=True)
    dev = devs["devices"][0]
    device_id = dev["device_id"]
    check("device is PENDING_CONFIRMATION", dev["status"] == "PENDING_CONFIRMATION", dev["status"])
    check("enrollment granted NO scopes", dev["granted_scopes"] == [], str(dev["granted_scopes"]))
    check("panel fingerprint matches the device's own", dev["fingerprint"] == fp,
          f"{dev['fingerprint']} vs {fp}")

    c, _ = http("POST", f"/admin/kai/computer-operations/devices/{device_id}/confirm",
                {"fingerprint": "AAAA-BBBB-CCCC-DDDD"}, admin=True)
    check("wrong fingerprint refused", c == 400, str(c))
    c, conf = http("POST", f"/admin/kai/computer-operations/devices/{device_id}/confirm",
                   {"fingerprint": fp}, admin=True)
    check("operator confirmed the real fingerprint", c == 200, str(c))
    check("confirmation grants baseline only, no elevated scope",
          conf["elevated_granted"] == [], str(conf["granted_scopes"]))

    # ---- 3-4. narrow scope, then an OBSERVE mission -----------------------
    print("\n--- mission ---")
    c, _ = http("POST", f"/admin/kai/computer-operations/devices/{device_id}/scopes/grant",
                {"scopes": ["computer.workspace.read"]}, admin=True)
    check("narrow workspace.read granted", c == 200, str(c))

    c, bad = http("POST", "/admin/kai/computer-operations/missions",
                  {"device_id": device_id, "objective": "x", "autonomy_mode": "EXECUTE_SCOPED",
                   "workspace": WS}, admin=True)
    check("EXECUTE_SCOPED refused without workspace.write", c == 403, str(c))

    c, mission = http("POST", "/admin/kai/computer-operations/missions",
                      {"device_id": device_id,
                       "objective": "Reply with exactly the word: E2E_OBSERVE_OK",
                       "autonomy_mode": "OBSERVE", "workspace": WS,
                       "max_duration_seconds": 300}, admin=True)
    check("OBSERVE mission created from the panel API", c == 200, str(c))
    mid = mission["mission_id"]

    # ---- 5-6. the REAL connector executes it ------------------------------
    print("\n--- real connector execution (jail + harness + local model) ---")
    t0 = time.time()
    r = subprocess.run([sys.executable, CONNECTOR, "run", "--once", "--interval", "1"],
                       capture_output=True, text=True, timeout=600, env=ENV)
    elapsed = time.time() - t0
    check("connector ran the mission without error", r.returncode == 0,
          (r.stderr or "")[-200:])
    check("connector passed the containment gate", "gate passed" in r.stdout, r.stdout[-160:])
    check("connector destroyed the mission volume", "volume destroyed" in r.stdout)
    print(f"      (connector run took {elapsed:.1f}s)")

    c, full = http("GET", f"/admin/kai/computer-operations/missions/{mid}", admin=True)
    check("mission progressed past QUEUED", full["status"] != "QUEUED", full["status"])
    check("attestation digest recorded against the mission",
          bool(full.get("attestation_digest")), str(full.get("attestation_digest"))[:20])
    check("evidence returned to the panel", len(full.get("evidence") or []) >= 1,
          str(len(full.get("evidence") or [])))
    check("worker did NOT mark the mission COMPLETED", full["status"] != "COMPLETED",
          full["status"])
    check("panel shows KAI has not verified completion",
          full["kai_verified_complete"] is False)

    # ---- 29. teardown ----------------------------------------------------
    mounts = subprocess.run(["mount"], capture_output=True, text=True).stdout
    check("no mission volume left mounted after the run", "KAI-" + mid not in mounts)
    check("no harness worker left running",
          subprocess.run(["pgrep", "-f", "dsh --profile acp"],
                         capture_output=True).returncode != 0)

    # ---- 12. replay a signed device request ------------------------------
    print("\n--- adversarial ---")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa
    sys.path.insert(0, BACKEND)
    from app.services.holding.device_auth import sign_request  # noqa: E402
    import kai_connector as kc  # noqa: E402

    key = kc.keychain_load(device_id)
    ts = datetime.now(timezone.utc)
    nonce = secrets.token_hex(16)
    body = b"{}"
    sig = sign_request(key, method="POST", path="/api/kai/device/heartbeat", body=body,
                       timestamp=ts, nonce=nonce, device_id=device_id)
    hdrs = {"Content-Type": "application/json", "X-KAI-Device-Id": device_id,
            "X-KAI-Timestamp": str(int(ts.timestamp())), "X-KAI-Nonce": nonce,
            "X-KAI-Signature": sig}

    def raw_post(path, headers, data=b"{}"):
        req = urllib.request.Request(BASE + path, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as r_:
                return r_.status
        except urllib.error.HTTPError as e:
            return e.code

    check("first signed request accepted", raw_post("/api/kai/device/heartbeat", hdrs) == 200)
    check("replayed signed request refused",
          raw_post("/api/kai/device/heartbeat", hdrs) == 401)

    # ---- 15/16. STOP -----------------------------------------------------
    c, stop = http("POST", "/admin/kai/computer-operations/stop", {"reason": "e2e"}, admin=True)
    check("STOP engaged from the panel API", c == 200, str(c))
    ts2 = datetime.now(timezone.utc); n2 = secrets.token_hex(16)
    h2 = {**hdrs, "X-KAI-Timestamp": str(int(ts2.timestamp())), "X-KAI-Nonce": n2,
          "X-KAI-Signature": sign_request(key, method="POST", path="/api/kai/device/heartbeat",
                                          body=body, timestamp=ts2, nonce=n2, device_id=device_id)}
    check("device refused while STOPPED (423)", raw_post("/api/kai/device/heartbeat", h2) == 423)
    r2 = subprocess.run([sys.executable, CONNECTOR, "run", "--once", "--interval", "1",
                         "--max-seconds", "6"], capture_output=True, text=True, timeout=120, env=ENV)
    check("connector stands down under STOP", "STOP engaged" in r2.stdout, r2.stdout[-120:])
    http("POST", "/admin/kai/computer-operations/stop/release", {}, admin=True)

    # ---- 13. revoke ------------------------------------------------------
    http("POST", f"/admin/kai/computer-operations/devices/{device_id}/revoke",
         {"reason": "e2e"}, admin=True)
    ts3 = datetime.now(timezone.utc); n3 = secrets.token_hex(16)
    h3 = {**hdrs, "X-KAI-Timestamp": str(int(ts3.timestamp())), "X-KAI-Nonce": n3,
          "X-KAI-Signature": sign_request(key, method="POST", path="/api/kai/device/heartbeat",
                                          body=body, timestamp=ts3, nonce=n3, device_id=device_id)}
    check("revoked device refused (403)", raw_post("/api/kai/device/heartbeat", h3) == 403)

    c, rt = http("GET", "/admin/kai/computer-operations/runtime", admin=True)
    check("runtime reports REVOKED once every device is revoked",
          rt["feature_state"] == "REVOKED", rt["feature_state"])
    check("local-only model routing reported", rt["model"]["policy"] == "LOCAL_ONLY"
          and rt["model"]["execution_location"] == "LOCAL")
    check("containment caveat present in API truth",
          rt["containment"]["caveat"] == "NOT A HYPERVISOR BOUNDARY")

finally:
    if server is not None:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
    subprocess.run(["dropdb", "--if-exists", DB], check=False)
    shutil.rmtree(WS, ignore_errors=True)
    try:
        state = os.path.expanduser("~/.kai-connector/device.json")
        if os.path.exists(state):
            did = json.load(open(state))["device_id"]
            subprocess.run(["security", "delete-generic-password", "-s",
                            "com.wheellsverse.kai.device", "-a", did],
                           capture_output=True)
            os.remove(state)
    except Exception:  # noqa: BLE001
        pass
    print("=== teardown complete: db dropped, keychain entry removed, workspace deleted ===")

out = os.path.join(HERE, "..", "..", "..", "docs", "computer-ops", "e2e-evidence.json")
try:
    with open(os.path.abspath(out), "w") as fh:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                   "checks": EVIDENCE}, fh, indent=2)
except Exception:  # noqa: BLE001
    pass

bad = [n for n, ok, _ in results if not ok]
print(f"\n{sum(1 for _n, ok, _d in results if ok)}/{len(results)} certification checks passed")
print("RESULT:", "E2E CERTIFIED" if not bad else f"FAILED: {bad}")
sys.exit(1 if bad else 0)
