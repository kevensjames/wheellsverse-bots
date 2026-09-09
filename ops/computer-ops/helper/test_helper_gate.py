# Behavioural gate for the KAI desktop helper, run by verify_signing.sh (criterion 9)
# against the artefact passed as argv[1] -- the bare build, a packaged .app's inner
# executable, or a signed one. It NEVER grants TCC and requires none, and it leaves no
# persistent state behind (any STOP it engages, it clears).
#
# The property under test for a SIGNED bundle is NOT "identity is refused" (it won't be)
# and NOT "accessibility is absent" (on some hosts a CLI inherits an ancestor's grant via
# responsible-process attribution). It is that an acceptable identity -- even WITH a TCC
# grant -- is still NOT sufficient: every consequential path stays closed on approval,
# observation binding, and the app allowlist. That is what makes a stable signing identity
# safe to grant. Each rung is asserted env-robustly: the expected refusal OR the earlier
# PERMISSION_NOT_GRANTED refusal (when this host has NOT inherited a grant) both pass.
import json, os, subprocess, sys, time, uuid
BIN = sys.argv[1]
BID = "com.wheellsverse.kai.desktopbridge"

def call(req, env=None):
    p = subprocess.run([BIN], input=json.dumps(req) + "\n", capture_output=True, text=True,
                       timeout=20, env=env)
    lines = (p.stdout or "").strip().splitlines()
    return json.loads(lines[-1]) if lines else {"ok": False, "reason": "no output"}

def req(verb, **kw):
    now = time.time()
    r = {"id": uuid.uuid4().hex, "verb": verb, "nonce": uuid.uuid4().hex,
         "createdAt": now, "expiresAt": now + 30, "allowedApps": ["Safari"]}
    r.update(kw); return r

P, F = [], []
def check(n, c, d=""):
    (P if c else F).append(n); print(f"  {'ok ' if c else 'FAIL'} {n}" + (f"  ({d})" if d and not c else ""))
def refused_with(r, *needles):
    reason = (r.get("reason") or "")
    return (r.get("ok") is False) and any(x.lower() in reason.lower() for x in needles)

env = {**os.environ, "KAI_BRIDGE_BUNDLE_ID": BID}  # forces acceptable identity on a bare binary; ignored by a bundle

# --- probe: truthful self-report, no TCC required ---
r = call(req("desktop.probe"))
data = r.get("data") or {}
acc = data.get("identity_acceptable")
check("probe answers without TCC", bool(r.get("ok")), str(r))
check("probe reports its bundle identity", "bundle_id" in data, str(data))
check("probe reports whether its identity is acceptable", acc in ("true", "false"), str(data))
check("probe reports accessibility state (true|false)",
      data.get("accessibility_granted") in ("true", "false"), str(data))
check("probe names the required bundle id", data.get("required_bundle_id") == BID, str(data))
check("probe reports stop state", data.get("stop_engaged") in ("true", "false"), str(data))

# --- closed vocabulary (identity-independent): the dangerous verbs simply do not exist ---
for v in ("desktop.run_shell", "desktop.applescript", "desktop.exec", "desktop.read_file",
          "desktop.click_at", "desktop.eval"):
    r = call(req(v))
    check(f"no {v} verb exists", refused_with(r, "unknown verb"), str(r)[:140])

# --- identity-mode-aware: a real verb is refused either way ---
if acc == "false":
    r = call(req("desktop.list_windows"))   # NO env: identity stays unacceptable, must refuse at that rung
    check("real verb REFUSED under unacceptable identity", refused_with(r, "refusing to act as"), str(r)[:140])

# --- acceptable identity is NOT sufficient: consequential paths stay closed ---
r = call(req("desktop.type_text", text="x", observationToken="nope", policyDecision="APPROVED"), env=env)
check("interaction with approval but no valid observation is refused",
      refused_with(r, "fresh observation", "observation expired", "PERMISSION_NOT_GRANTED", "DESKTOP_UNAVAILABLE"),
      str(r)[:160])

r = call(req("desktop.type_text", text="x", observationToken="nope"), env=env)  # NO approval
check("interaction without approval is refused",
      refused_with(r, "APPROVAL_REQUIRED", "PERMISSION_NOT_GRANTED", "DESKTOP_UNAVAILABLE"), str(r)[:160])

r = call(req("desktop.type_text", text="x", policyDecision="APPROVED", allowedApps=[], allowedBundleIds=[]), env=env)
check("empty app allowlist denies (default deny)",
      refused_with(r, "no approved applications", "PERMISSION_NOT_GRANTED", "DESKTOP_UNAVAILABLE"), str(r)[:160])

r = call(req("desktop.launch_approved_application", targetBundleId="com.apple.Safari",
             policyDecision="APPROVED", allowedApps=[], allowedBundleIds=[]), env=env)
check("launch with empty allowlist denied",
      refused_with(r, "no approved applications", "not in approved", "PERMISSION_NOT_GRANTED", "DESKTOP_UNAVAILABLE"),
      str(r)[:160])

# --- STOP works with no identity/TCC, and RESET restores clean state (no residue) ---
r = call(req("desktop.stop"))
check("STOP always works, needs no identity or TCC", bool(r.get("ok")), str(r))
r = call(req("desktop.probe"))
check("probe shows STOP engaged after stop", (r.get("data") or {}).get("stop_engaged") == "true", str(r)[:140])
r = call(req("desktop.reset"))
check("RESET clears STOP", bool(r.get("ok")), str(r))
r = call(req("desktop.probe"))
check("probe shows STOP cleared after reset (no residue left behind)",
      (r.get("data") or {}).get("stop_engaged") == "false", str(r)[:140])

print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)
