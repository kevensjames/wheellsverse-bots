import json, subprocess, sys
BIN = sys.argv[1]
def call(req, env=None):
    p = subprocess.run([BIN], input=json.dumps(req)+"\n", capture_output=True, text=True,
                       timeout=20, env=env)
    line = (p.stdout or "").strip().splitlines()
    return json.loads(line[-1]) if line else {"ok": False, "reason": "no output"}

P, F = [], []
def check(n, c, d=""):
    (P if c else F).append(n); print(f"  {'ok ' if c else 'FAIL'} {n}" + (f"  ({d})" if d and not c else ""))

base = {"id":"1","missionId":"m1","deviceId":"d1","allowedApps":["Safari"]}

r = call({"id":"p","verb":"desktop.probe"})
check("probe answers without TCC", r["ok"], str(r))
check("probe reports its bundle identity", "bundle_id" in (r.get("data") or {}), str(r.get("data")))
check("probe reports identity is NOT acceptable (unsigned build)",
      (r.get("data") or {}).get("identity_acceptable") == "false", str(r.get("data")))
check("probe reports accessibility not granted",
      (r.get("data") or {}).get("accessibility_granted") == "false")
check("probe names the required bundle id",
      (r.get("data") or {}).get("required_bundle_id") == "com.wheellsverse.kai.desktopbridge")

r = call({**base, "verb":"desktop.list_windows"})
check("a real verb is REFUSED under an unacceptable identity", not r["ok"], str(r)[:120])
check("refusal explains the TCC-identity reasoning", "identity" in (r.get("reason") or "").lower())

r = call({**base, "verb":"desktop.run_shell"})
check("unknown verb refused (closed vocabulary)", not r["ok"] and "unknown verb" in r["reason"])
for v in ("desktop.applescript","desktop.exec","desktop.read_file","desktop.click_at"):
    r = call({**base, "verb":v})
    check(f"no {v} verb exists", not r["ok"] and "unknown verb" in r["reason"])

r = call({"id":"s","verb":"desktop.stop"})
check("STOP always works, needs no identity or TCC", r["ok"], str(r))

# With the identity satisfied via env, the gate's later rungs must still hold.
import os
env = {**os.environ, "KAI_BRIDGE_BUNDLE_ID": "com.wheellsverse.kai.desktopbridge"}
r = call({**base, "verb":"desktop.list_windows"}, env=env)
check("with identity accepted, Accessibility is still required",
      not r["ok"] and "PERMISSION_NOT_GRANTED" in (r.get("reason") or ""), str(r)[:140])
r = call({**base, "verb":"desktop.type_text", "text":"hello",
          "observationToken":"nope"}, env=env)
check("interaction without approval is refused",
      not r["ok"] and ("APPROVAL_REQUIRED" in r["reason"] or "PERMISSION_NOT_GRANTED" in r["reason"]),
      str(r)[:140])
r = call({**base, "verb":"desktop.list_windows", "allowedApps":[]}, env=env)
check("empty app allowlist denies (default deny)",
      not r["ok"], str(r)[:120])
r = call({"id":"x","verb":"desktop.list_windows","allowedApps":["Safari"]}, env=env)
check("missing mission/device binding refused",
      not r["ok"] and "binding" in r["reason"], str(r)[:120])

print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
