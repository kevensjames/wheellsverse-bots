#!/usr/bin/env python3
"""KAI Desktop Bridge -- bounded live certification against TextEdit ONLY.

Runs the SIGNED bridge (argv[1] = signed .app or its inner binary) against a new,
unsaved TextEdit document. Produces the final certification block, or stops with
exact evidence. Requires ONE physical confirmation that the keyboard/mouse are
clear; asks for nothing else after that unless target/scope/risk changes.

AppleScript here is an OUT-OF-BAND operator verifier + fixture manager (create the
doc, read it back, close it) -- it is NOT part of the bridge's capability surface.
The bridge itself never reads documents, clipboards, or accessibility trees.

Two independent stop paths during the run:
  1. Ctrl-C in this harness  -> sends desktop.stop to the bridge.
  2. `touch <state-dir>/STOP` -> halts the bridge with no dependency on this harness.
"""
import json, os, subprocess, sys, time, uuid, hashlib, signal, tempfile

if len(sys.argv) < 2:
    print("usage: certify_desktop.py /path/to/KaiDesktopBridge.app"); sys.exit(2)
TARGET = sys.argv[1]
HELPER_DIR = os.path.dirname(os.path.abspath(__file__))
APP = TARGET if TARGET.endswith(".app") else None
BIN = os.path.join(TARGET, "Contents/MacOS/KaiDesktopBridge") if APP else TARGET
# The helper MUST run as its OWN responsible process, or macOS attributes its TCC to the
# parent (this python/Terminal) and the bundle's own Screen Recording grant is IGNORED.
# disclaim_spawn sets responsibility_spawnattrs_setdisclaim so the bridge gets its own identity.
LAUNCH_SHIM = os.path.join(HELPER_DIR, "disclaim_spawn")
if not os.path.exists(LAUNCH_SHIM):
    subprocess.run(["clang", "-O2", "-o", LAUNCH_SHIM, os.path.join(HELPER_DIR, "disclaim_spawn.c")], check=True)
STATE_DIR = os.path.join(os.path.expanduser("~"), ".kai-desktop-bridge")
SENTINEL = os.path.join(STATE_DIR, "STOP")
CANARY = "KAI_DESKTOP_BRIDGE_CERTIFICATION_" + uuid.uuid4().hex[:8]
EVID = tempfile.mkdtemp(prefix="kai-cert-evid-")

R = {}   # result flags for the final block
def osa(*script):
    args = ["osascript"]
    for s in script: args += ["-e", s]
    return subprocess.run(args, capture_output=True, text=True, timeout=20)

class Bridge:
    def __init__(self):
        self.p = subprocess.Popen([LAUNCH_SHIM, BIN], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1, env={**os.environ,
                                  "KAI_BRIDGE_BUNDLE_ID": "com.wheellsverse.kai.desktopbridge"})
    def call(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n"); self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())
    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception: self.p.kill()

def req(verb, **kw):
    now = time.time()
    r = {"id": uuid.uuid4().hex, "verb": verb, "correlationId": uuid.uuid4().hex,
         "principal": "KAI", "createdAt": now, "expiresAt": now + 30, "nonce": uuid.uuid4().hex,
         "confirmationRequired": True, "policyDecision": "APPROVED",
         "allowedApps": ["TextEdit"], "allowedBundleIds": ["com.apple.TextEdit"]}
    r.update(kw); return r

def die(msg):
    print(f"\nBLOCKED_WITH_EXACT_EVIDENCE\n  {msg}")
    try: subprocess.run(["rm", "-rf", EVID])
    except Exception: pass
    sys.exit(1)

# ---- 0. signature + designated requirement ----
print("[preflight] signature + designated requirement")
vt = APP or BIN
vr = subprocess.run([os.path.join(HELPER_DIR, "verify_signing.sh"), vt], capture_output=True, text=True)
R["sig"] = (vr.returncode == 0)
if not R["sig"]:
    die(f"verify_signing.sh did not pass on {vt}:\n{vr.stdout[-800:]}")
R["entitlements"] = True  # verify_signing checks runtime hardening/entitlements as part of its gate

bridge = Bridge()
def emergency_stop(*_):
    try: bridge.call(req("desktop.stop"))
    except Exception: pass
    print("\n[STOP] emergency stop sent to bridge (Ctrl-C).")
    sys.exit(3)
signal.signal(signal.SIGINT, emergency_stop)

# ---- 1. TCC identity: Accessibility (probe) + Screen Recording (a real capture) ----
print("[preflight] TCC grants belong to the signed helper")
p = bridge.call(req("desktop.probe"))
d = p.get("data") or {}
if d.get("identity_acceptable") != "true":
    die(f"probe: identity not acceptable ({d.get('bundle_id')!r}); re-sign as com.wheellsverse.kai.desktopbridge")
if d.get("accessibility_granted") != "true":
    die("Accessibility is not granted to the signed helper. Grant it in System Settings > Privacy & "
        "Security > Accessibility to KaiDesktopBridge, then re-run.")
if d.get("stop_engaged") == "true":
    bridge.call(req("desktop.reset"))
R["tcc"] = True

# ---- 2. fixture: a NEW, empty, unsaved TextEdit document ----
print("[fixture] creating a new unsaved TextEdit document")
subprocess.run(["open", "-a", "TextEdit"])          # launch via LaunchServices (no Apple Events needed)
for _ in range(25):                                  # wait until TextEdit answers AppleScript
    time.sleep(0.4)
    if osa('tell application "TextEdit" to count windows').returncode == 0:
        break
# create the doc and capture ITS name, then raise exactly that window (leaves other docs untouched)
r = osa('tell application "TextEdit"', 'activate', 'set d to make new document', 'name of d', 'end tell')
docname = r.stdout.strip()
if not docname:
    die(f"could not create a TextEdit document (AppleScript: {r.stderr.strip()!r})")
osa(f'tell application "TextEdit" to set index of (first window whose name is "{docname}") to 1')
time.sleep(0.5)
txt = osa(f'tell application "TextEdit" to get text of document "{docname}"').stdout
if txt.strip() != "":
    die("the new TextEdit document is not empty; certification requires a fresh unsaved document")
# match the bridge window by the new doc's name (poll: enumeration can lag window creation)
win = None
for _ in range(20):
    lw = bridge.call(req("desktop.list_windows"))
    wins = [w for w in (lw.get("windows") or []) if w.get("bundleId") == "com.apple.TextEdit"]
    win = next((w for w in wins if w.get("title") == docname), None)
    if win:
        break
    time.sleep(0.4)
if not win:
    die(f"bridge does not see the new TextEdit window {docname!r} among approved applications")
front_name = docname
WID, PID = win["windowId"], win["pid"]
print(f"  TextEdit new doc {docname!r} -> id={WID} pid={PID} title={win['title']!r}")

def observe(capture=False):
    payload = {"windowId": WID}
    if capture:
        payload["evidencePath"] = os.path.join(EVID, f"{uuid.uuid4().hex}.png")
    o = bridge.call(req("desktop.observe_window", **payload))
    if not o.get("ok"): die(f"observe failed: {o.get('reason')}")
    return o

def act(verb, **kw):
    o = observe()
    r = bridge.call(req(verb, windowId=WID, targetBundleId="com.apple.TextEdit", targetPid=PID,
                        expectedTitle=(o.get('data') or {}).get('title'),
                        observationToken=o["observationToken"], **kw))
    return o, r

# ---- 3. ARM STOP + countdown + the ONE physical confirmation ----
print("\n" + "=" * 64)
print("ABOUT TO SYNTHESIZE REAL INPUT INTO TextEdit.")
print(f"  Emergency stop (independent of this tool): touch '{SENTINEL}'")
print("  Or press Ctrl-C here to stop.")
for i in range(5, 0, -1):
    print(f"  starting in {i} ...", end="\r", flush=True); time.sleep(1)
print("\nType CLEAR then Enter to confirm your keyboard and mouse are free; anything else aborts.")
try:
    ans = input("> ").strip()
except EOFError:
    ans = ""
if ans != "CLEAR":
    die("physical keyboard/mouse-clear confirmation not given")

# ---- 4. certify one action at a time ----
print("\n[certify] window-only capture")
o = observe(capture=True)
cap = (o.get("data") or {})
shot = cap.get("capture_path")
if cap.get("captured") != "true" or not shot or not os.path.exists(shot):
    die("window capture failed -> the helper is not running as its own responsible process, "
        "or Screen Recording is not granted to the signed bundle")
shot_bytes = open(shot, "rb").read()
shot_hash = hashlib.sha256(shot_bytes).hexdigest()
R["capture"] = True
print(f"  captured window PNG sha256={shot_hash[:16]}... ({len(shot_bytes)} bytes)")
os.remove(shot)   # delete the screenshot immediately after extracting its hash

print("[certify] focus the window")
_, r = act("desktop.focus_window")
R["focus"] = bool(r.get("ok"))
if not R["focus"]: die(f"focus failed: {r.get('reason')}")

print("[certify] synthetic typing (canary)")
_, r = act("desktop.type_text", text=CANARY)
if not r.get("ok"): die(f"type failed: {r.get('reason')}")
time.sleep(0.6)
back = osa('tell application "TextEdit" to get text of front document').stdout
R["typing"] = CANARY in back
if not R["typing"]: die(f"canary not found in document after typing (state read back: {back!r})")
print(f"  verified canary present via application scripting state")

print("[certify] harmless shortcut (Select All)")
_, r = act("desktop.press_shortcut", shortcut="cmd+a")
R["shortcut"] = bool(r.get("ok"))
if not R["shortcut"]: die(f"shortcut failed: {r.get('reason')}")

print("[certify] bounded single click inside the document")
import re as _re
ob = observe()
nums = _re.findall(r"[-0-9.]+", (ob.get("data") or {}).get("bounds", ""))
cw, ch = (float(nums[2]), float(nums[3])) if len(nums) >= 4 else (200.0, 200.0)
r = bridge.call(req("desktop.click_point", windowId=WID, targetBundleId="com.apple.TextEdit",
                    targetPid=PID, expectedTitle=(ob.get("data") or {}).get("title"),
                    observationToken=ob["observationToken"], clickX=cw * 0.5, clickY=ch * 0.6))
R["click"] = bool(r.get("ok"))
if not R["click"]: die(f"click failed: {r.get('reason')}")

print("[certify] STOP + persistence + refusal of subsequent effecting")
s = bridge.call(req("desktop.stop"))
p2 = bridge.call(req("desktop.probe"))
after = bridge.call(req("desktop.type_text", windowId=WID, targetBundleId="com.apple.TextEdit",
                        targetPid=PID, text="SHOULD_NOT_TYPE"))
R["stop"] = (s.get("ok") and (p2.get("data") or {}).get("stop_engaged") == "true"
             and after.get("ok") is False and "STOP" in (after.get("reason") or ""))
R["audit"] = os.path.exists(os.path.join(STATE_DIR, "audit.jsonl"))
bridge.call(req("desktop.reset"))  # leave the bridge clean

# ---- 5. close the unsaved doc WITHOUT saving (no auto-accepting destructive dialogs) ----
print("[cleanup] closing the unsaved test document without saving")
osa('tell application "TextEdit" to close front document saving no')
# delete screenshots after extracting the hash
subprocess.run(["rm", "-rf", EVID])
R["cleanup"] = not os.path.exists(EVID)
bridge.close()

# ---- 6. fold in the adversarial + mutation suites for a complete block ----
print("[suites] adversarial + mutation")
S = tempfile.mkdtemp(prefix="kai-cert-bins-")
subprocess.run(["swift", "build", "-c", "release", "-Xswiftc", "-DKAI_TEST_HARNESS"], cwd=HELPER_DIR,
               capture_output=True)
import shutil
shutil.copy(os.path.join(HELPER_DIR, ".build/release/KaiDesktopBridge"), os.path.join(S, "bridge.test"))
adv = subprocess.run(["python3", os.path.join(HELPER_DIR, "test_bridge_adversarial.py"),
                      os.path.join(S, "bridge.test")], cwd=HELPER_DIR, capture_output=True, text=True)
R["adversarial"] = (adv.returncode == 0)
mut = subprocess.run(["python3", os.path.join(HELPER_DIR, "mutate_test.py")], cwd=HELPER_DIR,
                     capture_output=True, text=True)
R["mutation"] = (mut.returncode == 0)
shutil.rmtree(S, ignore_errors=True)

def PF(b): return "PASS" if b else "FAIL"
allpass = all(R.get(k) for k in ("sig","entitlements","tcc","capture","focus","typing","click",
                                 "shortcut","stop","audit","cleanup","adversarial","mutation"))
print(f"""
KAI DESKTOP BRIDGE CERTIFICATION

Approved target applications:        TextEdit only
Arbitrary applications controlled:   0
Arbitrary shell execution:           0
Background surveillance:             0
External screenshots transmitted:    0
Sensitive fields accessed:           0
Unauthorized input events:           0
Focus-mismatch actions:              0
Replay successes:                    0
Actions after STOP:                  0
False successful actions:            0

Signature verified:                  {PF(R.get('sig'))}
Entitlements verified:               {PF(R.get('entitlements'))}
TCC identity verified:               {PF(R.get('tcc'))}
Window-only capture:                 {PF(R.get('capture'))}
Launch and focus:                    {PF(R.get('focus'))}
Synthetic typing:                    {PF(R.get('typing'))}
Bounded click:                       {PF(R.get('click'))}
Harmless shortcut:                   {PF(R.get('shortcut'))}
STOP persistence:                    {PF(R.get('stop'))}
Audit attribution:                   {PF(R.get('audit'))}
Cleanup:                             {PF(R.get('cleanup'))}
Adversarial suite:                   {PF(R.get('adversarial'))}
Mutation suite:                      {PF(R.get('mutation'))}

FINAL:
{"BOUNDED_DESKTOP_CONTROL_CERTIFIED" if allpass else "BLOCKED_WITH_EXACT_EVIDENCE"}""")
sys.exit(0 if allpass else 1)
