# Behavioural gate for the KAI desktop helper. Runs against the helper binary passed as
# argv[1] -- the bare build, a packaged .app's inner executable, or a signed one -- and is
# identity-MODE-AWARE so it is correct for all three. It never grants TCC and requires none.
#
# The key property under test for a SIGNED bundle is not "identity is refused" (it won't
# be) but "an acceptable identity is still NOT sufficient" -- every consequential path
# stays closed on TCC, binding, allowlist and approval. That is what makes a stable
# signing identity safe to grant later.
import json, os, subprocess, sys
BIN = sys.argv[1]

def call(req, env=None):
    p = subprocess.run([BIN], input=json.dumps(req) + "\n", capture_output=True, text=True,
                       timeout=20, env=env)
    line = (p.stdout or "").strip().splitlines()
    return json.loads(line[-1]) if line else {"ok": False, "reason": "no output"}

P, F = [], []
def check(n, c, d=""):
    (P if c else F).append(n); print(f"  {'ok ' if c else 'FAIL'} {n}" + (f"  ({d})" if d and not c else ""))

base = {"id": "1", "missionId": "m1", "deviceId": "d1", "allowedApps": ["Safari"]}

r = call({"id": "p", "verb": "desktop.probe"})
data = r.get("data") or {}
acc = data.get("identity_acceptable")
check("probe answers without TCC", r["ok"], str(r))
check("probe reports its bundle identity", "bundle_id" in data, str(data))
check("probe reports whether its identity is acceptable", acc in ("true", "false"), str(data))
check("probe reports accessibility not granted", data.get("accessibility_granted") == "false")
check("probe names the required bundle id",
      data.get("required_bundle_id") == "com.wheellsverse.kai.desktopbridge")

# Identity-mode-aware: a real verb must be REFUSED either way, but for different reasons.
r = call({**base, "verb": "desktop.list_windows"})
if acc == "false":
    # bare / misnamed artefact: refused at the identity rung
    check("a real verb is REFUSED under an unacceptable identity", not r["ok"], str(r)[:140])
    check("refusal explains the TCC-identity reasoning",
          "identity" in (r.get("reason") or "").lower(), str(r)[:140])
else:
    # packaged / signed artefact: identity is acceptable, so it must be refused at the
    # NEXT rung -- an acceptable identity alone grants nothing.
    check("an acceptable identity does NOT by itself permit a verb", not r["ok"], str(r)[:140])
    check("refusal is now TCC/permission, not identity",
          "PERMISSION_NOT_GRANTED" in (r.get("reason") or ""), str(r)[:140])

# Closed vocabulary -- identity-independent.
r = call({**base, "verb": "desktop.run_shell"})
check("unknown verb refused (closed vocabulary)", not r["ok"] and "unknown verb" in r["reason"])
for v in ("desktop.applescript", "desktop.exec", "desktop.read_file", "desktop.click_at"):
    r = call({**base, "verb": v})
    check(f"no {v} verb exists", not r["ok"] and "unknown verb" in r["reason"])

r = call({"id": "s", "verb": "desktop.stop"})
check("STOP always works, needs no identity or TCC", r["ok"], str(r))

# With an acceptable identity (forced by env on a bare binary; inherent on a bundle) the
# later rungs must still hold. On a bundle the env is ignored but identity is already
# acceptable, so these hold in both cases.
env = {**os.environ, "KAI_BRIDGE_BUNDLE_ID": "com.wheellsverse.kai.desktopbridge"}
r = call({**base, "verb": "desktop.list_windows"}, env=env)
check("with identity accepted, Accessibility is still required",
      not r["ok"] and "PERMISSION_NOT_GRANTED" in (r.get("reason") or ""), str(r)[:140])
r = call({**base, "verb": "desktop.type_text", "text": "hello", "observationToken": "nope"}, env=env)
check("interaction without approval is refused",
      not r["ok"] and ("APPROVAL_REQUIRED" in r["reason"] or "PERMISSION_NOT_GRANTED" in r["reason"]),
      str(r)[:140])
r = call({**base, "verb": "desktop.list_windows", "allowedApps": []}, env=env)
check("empty app allowlist denies (default deny)", not r["ok"], str(r)[:140])
r = call({"id": "x", "verb": "desktop.list_windows", "allowedApps": ["Safari"]}, env=env)
check("missing mission/device binding refused",
      not r["ok"] and "binding" in r["reason"], str(r)[:140])

print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
