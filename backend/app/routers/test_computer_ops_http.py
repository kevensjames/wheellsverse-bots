"""HTTP certification for KAI Computer Operations.

Traverses the REAL routes, the REAL database and the REAL signature verification. A
unit-test count proves the service layer; this proves the authority boundary, which is
where a mistake actually costs something.

Requires a local Postgres. Creates and drops its own disposable database.

    cd backend && python3 app/routers/test_computer_ops_http.py
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

_HERE = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))

DB = f"kai_http_{uuid.uuid4().hex[:8]}"
os.environ.update({
    "DATABASE_URL": f"postgresql://localhost:5432/{DB}",
    "APP_ENV": "test", "SECRET_KEY": "t", "SESSION_SIGNING_SECRET": "t", "API_KEY": "t",
    "KAI_COMPUTER_OPS_ENABLED": "true",
})

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(f"  {'ok ' if cond else 'FAIL'} {name}" + (f"  ({detail})" if detail and not cond else ""))


subprocess.run(["createdb", DB], check=True)
try:
    r = subprocess.run(["alembic", "upgrade", "0008_add_kai_devices"],
                       cwd=os.path.dirname(os.path.dirname(os.path.dirname(_HERE))),
                       env=os.environ, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("migration failed:", r.stderr[-800:])
        raise SystemExit(1)

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers.admin_chat import require_kai_ultra
    from app.services.holding.device_auth import sign_request

    anon = TestClient(app, raise_server_exceptions=False)

    # ---------------------------------------------------------------- §3 anonymous
    print("=== anonymous access to admin JSON (required result: 0) ===")
    admin_paths = sorted({getattr(r_, "path", "") for r_ in app.routes
                          if getattr(r_, "path", "").startswith(("/admin/",))})
    concrete = [p for p in admin_paths if "{" not in p]
    # Two categories, reported separately because they are different severities and a
    # single count hides which one occurred:
    #   json_leaks  -- anonymous access to DATA. Must always be zero.
    #   shell_leaks -- anonymous access to a page SHELL. Carries no records, but discloses
    #                  the feature's existence and control vocabulary, so also zero.
    json_leaks, shell_leaks = [], []
    for p in concrete:
        for method in ("GET", "POST"):
            resp = anon.request(method, p)
            if resp.status_code != 200:
                continue
            body = resp.text.strip()
            if body in ("", "{}", "null"):
                continue
            ctype = resp.headers.get("content-type", "").split(";")[0]
            (json_leaks if "json" in ctype else shell_leaks).append((method, p, ctype))
    check(f"anonymous sensitive admin responses = 0 across {len(concrete)} concrete /admin paths",
          not json_leaks, f"{json_leaks[:3]}")
    check("no anonymous page shell served under /admin either",
          not shell_leaks, f"{shell_leaks[:3]}")

    for p in ("/admin/kai/computer-operations/devices",
              "/admin/kai/computer-operations/missions",
              "/admin/kai/computer-operations/runtime"):
        code = anon.get(p).status_code
        check(f"anonymous GET {p} refused", code in (401, 403), f"got {code}")
    code = anon.post("/admin/kai/computer-operations/stop").status_code
    check("anonymous STOP refused", code in (401, 403), f"got {code}")
    for p in ("/admin/capabilities", "/admin/capability-exec/x/invoke"):
        code = anon.request("GET" if "exec" not in p else "POST", p).status_code
        check(f"anonymous {p} refused", code in (401, 403, 404), f"got {code}")

    # ------------------------------------------------------- operator, authenticated
    app.dependency_overrides[require_kai_ultra] = lambda: None

    def as_anonymous(method: str, path: str):
        """Probe a route with NO owner auth, whatever overrides are installed.

        The owner override above is app-wide, so any "anonymous" assertion made after it
        would otherwise pass for the wrong reason -- a security test that cannot fail is
        worse than no test. This removes the override for the duration of one probe and
        verifies, on a route known to be gated, that the removal actually took effect.
        """
        saved = app.dependency_overrides.pop(require_kai_ultra, None)
        try:
            sentinel = anon.get("/admin/kai/computer-operations/devices").status_code
            assert sentinel in (401, 403), (
                f"as_anonymous() is not actually anonymous: gated route returned {sentinel}")
            return anon.request(method, path)
        finally:
            if saved is not None:
                app.dependency_overrides[require_kai_ultra] = saved
    op = TestClient(app, raise_server_exceptions=False)
    print("\n=== operator surface ===")
    check("operator can list devices", op.get(
        "/admin/kai/computer-operations/devices").status_code == 200)

    enroll = op.post("/admin/kai/computer-operations/devices/enroll",
                     json={"device_name": "Test Mac"})
    check("operator can create an enrollment", enroll.status_code == 200, enroll.text[:120])
    code = enroll.json()["pairing_code"]

    # ------------------------------------------------------------ device enrollment
    print("\n=== device enrollment ===")
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)
    dev = anon.post("/api/kai/device/enroll/complete", json={
        "pairing_code": code, "public_key": base64.b64encode(pub).decode(),
        "signature": base64.b64encode(key.sign(code.encode())).decode(),
        "os": "darwin", "arch": "arm64"})
    check("device completes enrollment with proof of possession", dev.status_code == 200,
          dev.text[:160])
    device_id = dev.json()["device_id"]
    fingerprint = dev.json()["fingerprint"]
    check("device starts PENDING_CONFIRMATION", dev.json()["status"] == "PENDING_CONFIRMATION")

    bad = anon.post("/api/kai/device/enroll/complete", json={
        "pairing_code": code, "public_key": base64.b64encode(pub).decode(),
        "signature": base64.b64encode(key.sign(code.encode())).decode()})
    check("pairing code cannot be reused", bad.status_code == 400, bad.text[:100])

    # -------------------------------------------------- signed request helper
    def signed(method: str, path: str, body: dict | None = None, *,
               k=None, did=None, ts=None, nonce=None, tamper=False):
        k = k or key
        did = did or device_id
        raw = json.dumps(body or {}).encode()
        ts = ts or datetime.now(timezone.utc)
        nonce = nonce or secrets.token_hex(16)
        sig = sign_request(k, method=method, path=path, body=raw,
                           timestamp=ts, nonce=nonce, device_id=did)
        sent = raw if not tamper else json.dumps({**(body or {}), "extra": "tampered"}).encode()
        return anon.request(method, path, content=sent, headers={
            "X-KAI-Device-Id": did, "X-KAI-Timestamp": str(int(ts.timestamp())),
            "X-KAI-Nonce": nonce, "X-KAI-Signature": sig,
            "content-type": "application/json"}), nonce

    print("\n=== device auth rejection matrix ===")
    resp, _ = signed("POST", "/api/kai/device/heartbeat")
    check("unconfirmed device is refused", resp.status_code == 403, f"{resp.status_code} {resp.text[:80]}")

    conf = op.post(f"/admin/kai/computer-operations/devices/{device_id}/confirm",
                   json={"fingerprint": "WRONG-WRONG-WRONG-WRONG"})
    check("wrong fingerprint refused at confirmation", conf.status_code == 400)
    conf = op.post(f"/admin/kai/computer-operations/devices/{device_id}/confirm",
                   json={"fingerprint": fingerprint})
    check("operator confirms the real fingerprint", conf.status_code == 200, conf.text[:120])
    check("confirmation grants baseline scopes only",
          set(conf.json()["elevated_granted"]) == set(), conf.json()["granted_scopes"])

    resp, nonce = signed("POST", "/api/kai/device/heartbeat")
    check("confirmed device heartbeat succeeds", resp.status_code == 200, resp.text[:120])

    resp2 = anon.request("POST", "/api/kai/device/heartbeat", content=b"{}", headers={
        "X-KAI-Device-Id": device_id, "X-KAI-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        "X-KAI-Nonce": nonce, "X-KAI-Signature": sign_request(
            key, method="POST", path="/api/kai/device/heartbeat", body=b"{}",
            timestamp=datetime.now(timezone.utc), nonce=nonce, device_id=device_id),
        "content-type": "application/json"})
    check("replayed nonce refused", resp2.status_code == 401, f"{resp2.status_code} {resp2.text[:80]}")

    resp, _ = signed("POST", "/api/kai/device/heartbeat", tamper=True)
    check("altered body refused", resp.status_code == 401, f"{resp.status_code}")

    resp, _ = signed("POST", "/api/kai/device/heartbeat",
                     ts=datetime.now(timezone.utc) - timedelta(minutes=10))
    check("expired timestamp refused", resp.status_code == 401, f"{resp.status_code}")

    other = Ed25519PrivateKey.generate()
    resp, _ = signed("POST", "/api/kai/device/heartbeat", k=other)
    check("forged signature refused", resp.status_code == 401, f"{resp.status_code}")

    resp, _ = signed("POST", "/api/kai/device/heartbeat", did="does-not-exist")
    check("unknown device refused", resp.status_code == 401, f"{resp.status_code}")

    resp = anon.post("/api/kai/device/heartbeat", json={})
    check("unsigned request refused", resp.status_code == 401, f"{resp.status_code}")

    # A signature for one path must not work on another.
    ts = datetime.now(timezone.utc); n = secrets.token_hex(16)
    sig = sign_request(key, method="POST", path="/api/kai/device/heartbeat", body=b"{}",
                       timestamp=ts, nonce=n, device_id=device_id)
    resp = anon.request("POST", "/api/kai/device/lease", content=b"{}", headers={
        "X-KAI-Device-Id": device_id, "X-KAI-Timestamp": str(int(ts.timestamp())),
        "X-KAI-Nonce": n, "X-KAI-Signature": sig, "content-type": "application/json"})
    check("signature bound to path (cannot be moved to another route)",
          resp.status_code == 401, f"{resp.status_code}")

    print("\n=== scopes gate device routes ===")
    resp, _ = signed("POST", "/api/kai/device/lease")
    check("lease allowed with baseline mission.receive", resp.status_code == 200, resp.text[:100])
    check("no mission queued yet", resp.json()["mission"] is None)

    # ------------------------------------------------------------------ missions
    print("\n=== mission creation guards ===")
    bad_ws = op.post("/admin/kai/computer-operations/missions", json={
        "device_id": device_id, "objective": "x", "autonomy_mode": "OBSERVE",
        "workspace": "/"})
    check("workspace '/' refused", bad_ws.status_code == 400, bad_ws.text[:100])
    for ws in (os.path.expanduser("~"), os.path.expanduser("~/.ssh"),
               os.path.expanduser("~/Library/Keychains")):
        rr = op.post("/admin/kai/computer-operations/missions", json={
            "device_id": device_id, "objective": "x", "autonomy_mode": "OBSERVE", "workspace": ws})
        check(f"workspace {ws} refused", rr.status_code == 400, rr.text[:80])

    exec_no_scope = op.post("/admin/kai/computer-operations/missions", json={
        "device_id": device_id, "objective": "edit", "autonomy_mode": "EXECUTE_SCOPED",
        "workspace": "/tmp/kai-cert-ws"})
    check("EXECUTE_SCOPED refused without workspace.write scope",
          exec_no_scope.status_code == 403, exec_no_scope.text[:120])

    os.makedirs("/tmp/kai-cert-ws", exist_ok=True)
    mk = op.post("/admin/kai/computer-operations/missions", json={
        "device_id": device_id, "objective": "inspect the workspace",
        "autonomy_mode": "OBSERVE", "workspace": "/tmp/kai-cert-ws"})
    check("OBSERVE mission created", mk.status_code == 200, mk.text[:160])
    mid = mk.json()["mission_id"]
    check("mission starts QUEUED", mk.json()["status"] == "QUEUED")
    check("worker claim and KAI verdict are separate fields",
          mk.json()["worker_claimed_success"] is False and
          mk.json()["kai_verified_complete"] is False)

    resp, _ = signed("POST", "/api/kai/device/lease")
    check("device leases its mission", resp.json()["mission"] is not None, resp.text[:120])
    check("leased mission is the one created",
          resp.json()["mission"]["mission_id"] == mid)

    print("\n=== a worker cannot self-complete ===")
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/progress",
                     {"status": "COMPLETED"})
    check("worker reporting COMPLETED is refused over HTTP", resp.status_code == 403,
          f"{resp.status_code} {resp.text[:120]}")
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/progress", {"status": "RUNNING"})
    check("worker may report RUNNING", resp.status_code == 200, resp.text[:100])

    print("\n=== cross-device isolation ===")
    e2 = op.post("/admin/kai/computer-operations/devices/enroll", json={"device_name": "Other"})
    c2 = e2.json()["pairing_code"]
    k2 = Ed25519PrivateKey.generate()
    p2 = k2.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    d2 = anon.post("/api/kai/device/enroll/complete", json={
        "pairing_code": c2, "public_key": base64.b64encode(p2).decode(),
        "signature": base64.b64encode(k2.sign(c2.encode())).decode()}).json()
    op.post(f"/admin/kai/computer-operations/devices/{d2['device_id']}/confirm",
            json={"fingerprint": d2["fingerprint"]})
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/progress", {"status": "RUNNING"},
                     k=k2, did=d2["device_id"])
    check("another device cannot report on this mission", resp.status_code == 403,
          f"{resp.status_code} {resp.text[:100]}")

    print("\n=== approvals ===")
    params = {"path": "/tmp/kai-cert-ws/a.txt"}
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/permission",
                     {"action": "write_file", "target": "a.txt", "params": params})
    check("device may request permission", resp.status_code == 200, resp.text[:120])
    aid = resp.json()["approval_id"]
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/permission/{aid}/consume",
                     {"action": "write_file", "target": "a.txt", "params": params})
    check("unapproved approval cannot be consumed", resp.status_code == 403)
    ap = op.post(f"/admin/kai/computer-operations/missions/{mid}/approvals/{aid}",
                 json={"approved": True})
    check("operator approves", ap.status_code == 200, ap.text[:120])
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/permission/{aid}/consume",
                     {"action": "write_file", "target": "DIFFERENT.txt", "params": params})
    check("changed target refused at consumption", resp.status_code == 403)
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/permission/{aid}/consume",
                     {"action": "write_file", "target": "a.txt",
                      "params": {**params, "mode": "append"}})
    check("changed parameters refused at consumption", resp.status_code == 403)
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/permission/{aid}/consume",
                     {"action": "write_file", "target": "a.txt", "params": params})
    check("exact approval consumes once", resp.status_code == 200, resp.text[:120])
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid}/permission/{aid}/consume",
                     {"action": "write_file", "target": "a.txt", "params": params})
    check("second consumption refused (replay)", resp.status_code == 403)

    print("\n=== STOP ===")
    stop = op.post("/admin/kai/computer-operations/stop", json={"reason": "cert"})
    check("operator STOP succeeds", stop.status_code == 200, stop.text[:120])
    check("STOP reports stopped missions", mid in stop.json()["stopped_missions"], stop.text[:160])
    resp, _ = signed("POST", "/api/kai/device/heartbeat")
    check("device requests refused while STOPPED (423)", resp.status_code == 423,
          f"{resp.status_code}")
    rel = op.post("/admin/kai/computer-operations/stop/release", json={})
    check("operator can release STOP", rel.status_code == 200)
    resp, _ = signed("POST", "/api/kai/device/heartbeat")
    check("device works again after release", resp.status_code == 200)

    print("\n=== revocation ===")
    op.post(f"/admin/kai/computer-operations/devices/{device_id}/revoke",
            json={"reason": "cert"})
    resp, _ = signed("POST", "/api/kai/device/heartbeat")
    check("revoked device refused", resp.status_code == 403, f"{resp.status_code}")


    print("\n=== SSE + bounded replay over real HTTP ===")
    ev_url = f"/admin/kai/computer-operations/missions/{mid}/events"
    c_anon = as_anonymous("GET", ev_url).status_code
    check("anonymous replay refused", c_anon in (401, 403), str(c_anon))
    c_anon = as_anonymous(
        "GET", f"/admin/kai/computer-operations/missions/{mid}/stream").status_code
    check("anonymous SSE stream refused", c_anon in (401, 403), str(c_anon))

    r = op.get(ev_url)
    check("owner can read the replay endpoint", r.status_code == 200, r.text[:120])
    body = r.json()
    seqs = [e["seq"] for e in body["events"]]
    check("sequence numbers are strictly increasing",
          seqs == sorted(seqs) and len(set(seqs)) == len(seqs), str(seqs[:8]))
    check("replay reports a cursor and the latest sequence",
          "cursor" in body and "latest_seq" in body, str(list(body)))
    check("replay carries a snapshot so a client is never blank",
          "status" in (body.get("snapshot") or {}), str(body.get("snapshot"))[:120])
    check("snapshot separates worker claim from KAI verdict",
          {"worker_claimed_success", "kai_verified_complete"} <= set(body["snapshot"]))

    if seqs:
        r2 = op.get(ev_url + f"?after={seqs[-1]}")
        check("a cursor at the head returns no repeats", r2.json()["events"] == [],
              str(r2.json()["events"])[:80])
        mid_cursor = seqs[len(seqs) // 2]
        r3 = op.get(ev_url + f"?after={mid_cursor}")
        check("a mid cursor returns only newer events",
              all(e["seq"] > mid_cursor for e in r3.json()["events"]),
              str([e["seq"] for e in r3.json()["events"]][:6]))

    r4 = op.get(ev_url + "?limit=1")
    check("an explicit limit is honoured", len(r4.json()["events"]) <= 1)
    check("truncation is reported when the window is exceeded",
          r4.json()["truncated"] is True or len(seqs) <= 1, str(r4.json()["truncated"]))

    blob = json.dumps(op.get(ev_url).json())
    for secret in ("X-KAI-Signature", "pairing_code", "private"):
        check(f"replay carries no {secret}", secret not in blob)

    r5 = op.get("/admin/kai/computer-operations/missions/does-not-exist/events")
    check("replay for an unknown mission is 404", r5.status_code == 404, str(r5.status_code))

    print("\n=== runtime truth ===")
    rt = op.get("/admin/kai/computer-operations/runtime").json()
    check("containment is labelled honestly",
          rt["containment"]["caveat"] == "NOT A HYPERVISOR BOUNDARY", rt["containment"])
    check("harness pin reported", rt["harness"]["pinned_sha"].startswith("c389f96"))
    check("model policy is LOCAL_ONLY", rt["model"]["policy"] == "LOCAL_ONLY")
    check("model execution location is LOCAL", rt["model"]["execution_location"] == "LOCAL")
    check("browser reports UNAVAILABLE truthfully", rt["browser"]["state"] == "UNAVAILABLE")
    check("voice reports VOICE_ENTRY_UNAVAILABLE",
          rt["voice"]["state"] == "VOICE_ENTRY_UNAVAILABLE")
    check("desktop reports NOT_VERIFIED", rt["desktop"]["state"] == "DESKTOP_CONTROL_NOT_VERIFIED")
    # A second device is still ACTIVE at this point, so READY here is TRUTHFUL, not a
    # hard-coded label -- it required an active device, a built harness at the pin, and a
    # probed-reachable loopback model. Prove that by removing the last usable device.
    check("READY is reported only while a usable device exists",
          rt["feature_state"] == "READY" and rt["usable_device_count"] == 1,
          f"{rt['feature_state']} usable={rt.get('usable_device_count')}")
    op.post(f"/admin/kai/computer-operations/devices/{d2['device_id']}/revoke",
            json={"reason": "cert"})
    rt2 = op.get("/admin/kai/computer-operations/runtime").json()
    check("with every device revoked the state is REVOKED, not READY",
          rt2["feature_state"] == "REVOKED", rt2["feature_state"])
    check("a revoked device's stale heartbeat does not keep the connector READY",
          rt2["connector_state"] == "OFFLINE" and rt2["usable_device_count"] == 0,
          f"{rt2['connector_state']} usable={rt2['usable_device_count']}")
    check("degradation reason is specific",
          "revoked" in (rt2.get("degradation_reason") or "").lower(),
          rt2.get("degradation_reason"))

    # Runs LAST: it enrolls a fresh device, which would otherwise change the
    # preconditions of the runtime assertions above (they require every device revoked).
    print("\n=== enforced limits over real HTTP ===")
    # Re-enroll a usable device: the one above was revoked by the revocation test.
    e3 = op.post("/admin/kai/computer-operations/devices/enroll", json={"device_name": "Limits"})
    c3 = e3.json()["pairing_code"]
    k3 = Ed25519PrivateKey.generate()
    p3 = k3.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    d3 = anon.post("/api/kai/device/enroll/complete", json={
        "pairing_code": c3, "public_key": base64.b64encode(p3).decode(),
        "signature": base64.b64encode(k3.sign(c3.encode())).decode()}).json()
    op.post(f"/admin/kai/computer-operations/devices/{d3['device_id']}/confirm",
            json={"fingerprint": d3["fingerprint"]})

    from app.services.holding.computer_ops_limits import (MAX_EVIDENCE_BYTES,
                                                          MAX_REQUEST_BYTES)
    big = {"blob": "x" * (MAX_REQUEST_BYTES + 2048)}
    resp, _ = signed("POST", "/api/kai/device/heartbeat", big, k=k3, did=d3["device_id"])
    check("oversized device request refused with 413", resp.status_code == 413,
          f"{resp.status_code} {resp.text[:100]}")

    mk2 = op.post("/admin/kai/computer-operations/missions", json={
        "device_id": d3["device_id"], "objective": "limits", "autonomy_mode": "OBSERVE",
        "workspace": "/tmp/kai-cert-ws", "max_duration_seconds": 99999})
    check("limits mission created", mk2.status_code == 200, f"{mk2.status_code} {mk2.text[:200]}")
    check("mission duration is clamped server-side, not honoured as requested",
          mk2.status_code == 200 and mk2.json().get("spec", {}).get("max_duration_seconds", 99999) <= 3600,
          str(mk2.json())[:200])
    mid2 = mk2.json().get("mission_id", "")

    resp, _ = signed("POST", "/api/kai/device/lease", k=k3, did=d3["device_id"])
    check("first lease succeeds", resp.status_code == 200 and resp.json()["mission"], resp.text[:100])
    # A second queued mission must NOT be leasable while one is in flight.
    op.post("/admin/kai/computer-operations/missions", json={
        "device_id": d3["device_id"], "objective": "second", "autonomy_mode": "OBSERVE",
        "workspace": "/tmp/kai-cert-ws"})
    resp, _ = signed("POST", "/api/kai/device/lease", k=k3, did=d3["device_id"])
    check("concurrent lease refused with 429 (back-pressure)", resp.status_code == 429,
          f"{resp.status_code} {resp.text[:120]}")
    check("429 carries Retry-After so a client waits", "retry-after" in
          {h.lower() for h in resp.headers}, str(dict(resp.headers))[:120])

    ev = {"kind": "blob", "data": "y" * (MAX_EVIDENCE_BYTES + 1024)}
    resp, _ = signed("POST", f"/api/kai/device/missions/{mid2}/evidence", ev,
                     k=k3, did=d3["device_id"])
    check("oversized evidence refused with 413", resp.status_code == 413,
          f"{resp.status_code} {resp.text[:100]}")

    sweep = op.post("/admin/kai/computer-operations/missions/sweep")
    check("overdue sweep endpoint answers", sweep.status_code == 200, sweep.text[:100])


finally:
    app_mod = sys.modules.get("app.main")
    if app_mod is not None:
        app_mod.app.dependency_overrides.clear()
    subprocess.run(["dropdb", "--if-exists", DB], check=False)

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", FAILED)
sys.exit(1 if FAILED else 0)
