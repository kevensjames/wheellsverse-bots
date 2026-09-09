#!/usr/bin/env python3
"""Adversarial + positive protocol suite for KAI Desktop Bridge.

Drives the -DKAI_TEST_HARNESS build (capability probes stubbed, effects no-op'd,
live window model driven by env + test.* control verbs) so every guard in the
decision chain is reachable and every adversarial case is deterministic — with
NO real desktop effects and NO signing. The production build contains none of
this path. One case (permission-not-granted) runs the PRODUCTION binary, whose
real AXIsProcessTrusted() is false when unsigned/ungranted.

Usage: test_bridge_adversarial.py <test-harness-binary> [production-binary]
"""
import json, os, subprocess, sys, tempfile, time, uuid, shutil

BID = "com.wheellsverse.kai.desktopbridge"
WINDOWS = [{"windowId": 42, "pid": 1000, "app": "TextEdit",
            "bundleId": "com.apple.TextEdit", "title": "Untitled",
            "bounds": {"x": 100, "y": 100, "w": 600, "h": 400},
            "sensitive": False, "onscreen": True}]

TEST_BIN = sys.argv[1]
PROD_BIN = sys.argv[2] if len(sys.argv) > 2 else None
TMP = tempfile.mkdtemp(prefix="kai-bridge-adv-")

def uid(): return uuid.uuid4().hex

class Bridge:
    def __init__(self, binpath=TEST_BIN, statedir=None, env_extra=None, windows=None, frontmost=None):
        env = dict(os.environ)
        env["KAI_BRIDGE_BUNDLE_ID"] = BID
        if binpath == TEST_BIN:
            env["KAI_TEST_STATE_DIR"] = statedir or os.path.join(TMP, uid())
            os.makedirs(env["KAI_TEST_STATE_DIR"], exist_ok=True)
            env["KAI_TEST_WINDOWS"] = json.dumps(windows if windows is not None else WINDOWS)
            env["KAI_TEST_FRONTMOST"] = frontmost if frontmost is not None else "com.apple.TextEdit"
        if env_extra: env.update(env_extra)
        self.p = subprocess.Popen([binpath], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1, env=env)
    def call(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n"); self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())
    def raw(self, s):
        self.p.stdin.write(s + "\n"); self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())
    def close(self):
        try: self.p.stdin.close()
        except Exception: pass
        try: self.p.wait(timeout=5)
        except Exception: self.p.kill()

def req(verb, approved=True, **kw):
    now = time.time()
    r = {"id": uid(), "verb": verb, "correlationId": uid(), "principal": "KAI",
         "createdAt": now, "expiresAt": now + 30, "nonce": uid(),
         "confirmationRequired": True,
         "allowedApps": ["TextEdit"], "allowedBundleIds": ["com.apple.TextEdit"]}
    if approved: r["policyDecision"] = "APPROVED"
    r.update(kw); return r

def observe(b, windowId=42):
    return b.call(req("desktop.observe_window", windowId=windowId))

PASS, FAIL = 0, 0
def bool_check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok   {name}")
    else: FAIL += 1; print(f"  FAIL {name}: {detail}")

def check(name, resp, want_ok, need=None):
    global PASS, FAIL
    ok = resp.get("ok"); reason = resp.get("reason", "") or ""
    good = (ok == want_ok) and (need is None or need.lower() in reason.lower())
    if good: PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}: ok={ok} want={want_ok} reason={reason!r} need={need!r}")

# ---------- positive controls (non-vacuous: the gate must ALLOW valid actions) ----------
print("[positive controls]")
b = Bridge()
r = b.call(req("desktop.probe")); check("probe ok", r, True)
r = b.call(req("desktop.list_windows")); check("list_windows ok", r, True)
o = observe(b); check("observe ok", o, True)
tok = o.get("observationToken")
check("type ok", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled",
      text="KAI_CANARY_123")), True)
o = observe(b); tok = o["observationToken"]
check("shortcut cmd+a ok", b.call(req("desktop.press_shortcut", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, shortcut="cmd+a")), True)
o = observe(b); tok = o["observationToken"]
check("click inside ok", b.call(req("desktop.click_point", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, clickX=300, clickY=200)), True)
o = observe(b); tok = o["observationToken"]
check("focus ok", b.call(req("desktop.focus_window", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000)), True)
check("launch approved ok", b.call(req("desktop.launch_approved_application",
      targetBundleId="com.apple.TextEdit")), True)
b.close()

# ---------- adversarial: envelope / auth ----------
print("[envelope / auth]")
b = Bridge(env_extra={"KAI_BRIDGE_BUNDLE_ID": "com.evil.app"})
check("forged caller (identity mismatch)", b.call(req("desktop.list_windows")), False, "refusing to act as")
b.close()

b = Bridge()
check("unknown action", b.call(req("desktop.nuke_everything")), False, "unknown verb")
b.close()

b = Bridge()
check("malformed request", b.raw("this is not json {{{"), False, "malformed")
b.close()

b = Bridge()
o = observe(b); tok = o["observationToken"]
check("unsigned/no-approval", b.call(req("desktop.type_text", approved=False, observationToken=tok,
      windowId=42, targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")),
      False, "APPROVAL_REQUIRED")
b.close()

b = Bridge()
now = time.time()
check("expired request", b.call(req("desktop.type_text", observationToken="x", windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x",
      createdAt=now-100, expiresAt=now-50)), False, "expired")
b.close()

b = Bridge()
o = observe(b); tok = o["observationToken"]
n = uid()
r1 = b.call(req("desktop.type_text", observationToken=tok, windowId=42, targetBundleId="com.apple.TextEdit",
      targetPid=1000, expectedTitle="Untitled", text="one", nonce=n))
check("replay setup (first ok)", r1, True)
check("replayed nonce refused", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="two", nonce=n)),
      False, "replay")
b.close()

# ---------- adversarial: target binding ----------
print("[target binding]")
b = Bridge(); o = observe(b); tok = o["observationToken"]
check("wrong bundle id", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.Safari", targetPid=1000, text="x")), False, "bundle id does not match")
b.close()
b = Bridge(); o = observe(b); tok = o["observationToken"]
check("wrong pid", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=9999, text="x")), False, "pid does not match")
b.close()
b = Bridge(); o = observe(b); tok = o["observationToken"]
check("wrong window", b.call(req("desktop.type_text", observationToken=tok, windowId=777,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "does not cover")
b.close()
b = Bridge()
check("no observation", b.call(req("desktop.type_text", windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "fresh observation")
b.close()

# ---------- adversarial: live desktop changed since observation ----------
print("[live change since observation]")
b = Bridge(); o = observe(b); tok = o["observationToken"]
changed = [dict(WINDOWS[0], title="Now Something Else")]
b.call({"id": uid(), "verb": "test.set_windows", "windows": json.dumps(changed)})
check("title changed", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "title changed")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
moved = [dict(WINDOWS[0], bounds={"x": 100, "y": 100, "w": 900, "h": 400})]
b.call({"id": uid(), "verb": "test.set_windows", "windows": json.dumps(moved)})
check("geometry changed", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "geometry changed")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
reused = [dict(WINDOWS[0], pid=2000)]
b.call({"id": uid(), "verb": "test.set_windows", "windows": json.dumps(reused)})
check("window id reused by other process", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "reused")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
b.call({"id": uid(), "verb": "test.set_windows", "windows": json.dumps([])})
check("target disappeared/app exit", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "disappeared")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
b.call({"id": uid(), "verb": "test.set_frontmost_window", "frontmostWindow": 999})
check("focus stolen before input", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "not frontmost")
b.close()

# ---------- adversarial: sensitive / privacy / bounds ----------
print("[sensitive / privacy / bounds]")
b = Bridge(); o = observe(b); tok = o["observationToken"]
b.call({"id": uid(), "verb": "test.set_secure", "secure": True})
check("secure/password field", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "secure")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
check("credential-like text refused", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled",
      text="my bank password is hunter2")), False, "credential")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
check("oversized input", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="A"*2000)),
      False, "cap")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
check("forbidden shortcut", b.call(req("desktop.press_shortcut", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, shortcut="cmd+s")), False, "allowlist")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
check("click outside window", b.call(req("desktop.click_point", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, clickX=99999, clickY=5)), False, "outside")
b.close()

b = Bridge(); o = observe(b); tok = o["observationToken"]
b.call({"id": uid(), "verb": "test.set_role_sensitive", "roleSensitive": True})
check("click on secure UI role", b.call(req("desktop.click_point", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, clickX=300, clickY=200)), False, "secure")
b.close()

b = Bridge()
check("capture without target", b.call(req("desktop.observe_window")), False, "windowId required")
b.close()

# sensitive app: observing a password manager window is blocked, not masked
b = Bridge(windows=[{"windowId": 9, "pid": 5, "app": "1Password", "bundleId": "com.1password.1password",
                     "title": "Vault", "bounds": {"x": 0, "y": 0, "w": 10, "h": 10}, "onscreen": True}])
check("sensitive app observe blocked", b.call(req("desktop.observe_window", windowId=9,
      allowedApps=["1Password"], allowedBundleIds=["com.1password.1password"])), False, "sensitive")
b.close()

# ---------- adversarial: STOP ----------
print("[STOP]")
sd = os.path.join(TMP, "stop-persist")
b = Bridge(statedir=sd)
check("STOP engages", b.call(req("desktop.stop")), True, "stopped")
check("action after STOP refused", b.call(req("desktop.type_text", windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "STOP is engaged")
b.close()
# helper restart: same state dir -> STOP still engaged
b2 = Bridge(statedir=sd)
check("STOP persists across restart", b2.call(req("desktop.type_text", windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "STOP is engaged")
check("reset clears STOP", b2.call(req("desktop.reset")), True, "reset")
p = b2.call(req("desktop.probe"))
check("probe shows stop cleared", p, True)
if p.get("data", {}).get("stop_engaged") != "false":
    print("  FAIL reset did not clear stop_engaged"); FAIL += 1
else:
    print("  ok   stop_engaged=false after reset"); PASS += 1
b2.close()

# external emergency STOP: any process touches the sentinel -> bridge halts
sd2 = os.path.join(TMP, "stop-external"); os.makedirs(sd2, exist_ok=True)
b = Bridge(statedir=sd2)
check("pre-stop action ok", observe(b), True)
open(os.path.join(sd2, "STOP"), "w").write("emergency\n")  # independent of KAI
check("external sentinel halts bridge", b.call(req("desktop.type_text", windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "STOP is engaged")
b.close()

# ---------- adversarial: multiple simultaneous controllers ----------
print("[multi-controller]")
sd3 = os.path.join(TMP, "multi"); os.makedirs(sd3, exist_ok=True)
a = Bridge(statedir=sd3)   # holds the controller lock
a.call(req("desktop.probe"))
c = Bridge(statedir=sd3)   # second controller
check("second controller refused mutating", c.call(req("desktop.type_text", windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "another controller")
c.close(); a.close()

# ---------- adversarial: audit-store failure fails closed ----------
print("[audit fail-closed]")
sd4 = os.path.join(TMP, "audit"); os.makedirs(sd4, exist_ok=True)
os.makedirs(os.path.join(sd4, "audit.jsonl"), exist_ok=True)   # make audit path unwritable (it's a dir)
b = Bridge(statedir=sd4)
o = observe(b); tok = o.get("observationToken")
check("audit unavailable -> refuse", b.call(req("desktop.type_text", observationToken=tok, windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "AUDIT_UNAVAILABLE")
b.close()

# ---------- review-fix regressions ----------
print("[review fixes]")
# HIGH-1: evidencePath is confined to the evidence dir (basename only), never the caller path
sd_ev = os.path.join(TMP, "evid"); os.makedirs(sd_ev, exist_ok=True)
b = Bridge(statedir=sd_ev)
o = b.call(req("desktop.observe_window", windowId=42, evidencePath="../../../etc/kai_evil_write.png"))
cp = (o.get("data") or {}).get("capture_path", "")
evdir = os.path.join(sd_ev, "evidence")
bool_check("evidencePath confined to evidence dir (basename only)",
           o.get("ok") is True and os.path.dirname(cp) == evdir and os.path.basename(cp) == "kai_evil_write.png", str(o)[:180])
bool_check("evidencePath traversal cannot escape", cp.startswith(evdir + "/") and "/etc/" not in cp, cp)
b.close()

# HIGH-2: an operator STOP sentinel cannot be cleared by desktop.reset
sd_op = os.path.join(TMP, "opstop"); os.makedirs(sd_op, exist_ok=True)
open(os.path.join(sd_op, "STOP"), "w").write("operator\n")   # operator emergency file
b = Bridge(statedir=sd_op)
check("reset refuses to clear operator STOP", b.call(req("desktop.reset")), False, "operator STOP sentinel present")
check("bridge still halted after attempted reset", b.call(req("desktop.type_text", windowId=42,
      targetBundleId="com.apple.TextEdit", targetPid=1000, text="x")), False, "STOP is engaged")
b.close()

# LOW-7: expiresAt is required for mutating verbs
b = Bridge(); o = observe(b); tok = o["observationToken"]
r = dict(req("desktop.type_text", observationToken=tok, windowId=42, targetBundleId="com.apple.TextEdit",
             targetPid=1000, expectedTitle="Untitled", text="x")); r.pop("expiresAt", None)
check("mutating without expiresAt refused", b.call(r), False, "expiresAt")
b.close()

# MED-4: type/click bound to the observed window's key-focused window
b = Bridge(); o = observe(b); tok = o["observationToken"]
b.call({"id": uid(), "verb": "test.set_focused_bounds", "bounds": {"x": 5000, "y": 5000, "w": 10, "h": 10}})
check("type refused when key focus is a different window", b.call(req("desktop.type_text", observationToken=tok,
      windowId=42, targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "key-focused window is not the observed")
b.close()

# MED-5: operator allowlist intersects (excludes TextEdit -> default deny)
sd_al = os.path.join(TMP, "oplist"); os.makedirs(sd_al, exist_ok=True)
open(os.path.join(sd_al, "approved-apps.json"), "w").write(json.dumps({"apps": ["Safari"], "bundleIds": ["com.apple.Safari"]}))
b = Bridge(statedir=sd_al)
check("operator allowlist excludes TextEdit -> denied", b.call(req("desktop.observe_window", windowId=42)),
      False, "no approved applications")
b.close()

# focus_window is exempt from the frontmost precondition (its job IS to establish focus);
# input verbs still require the target frontmost.
b = Bridge(env_extra={"KAI_TEST_FRONTMOST_WINDOW": "999"})
o = observe(b)                     # observed while a DIFFERENT app is frontmost
tok = o["observationToken"]
check("type refused when target not frontmost at observe", b.call(req("desktop.type_text", observationToken=tok,
      windowId=42, targetBundleId="com.apple.TextEdit", targetPid=1000, expectedTitle="Untitled", text="x")),
      False, "not frontmost")
o = observe(b); tok = o["observationToken"]
check("focus_window ALLOWED when not frontmost (establishes focus)", b.call(req("desktop.focus_window",
      observationToken=tok, windowId=42, targetBundleId="com.apple.TextEdit", targetPid=1000)), True)
b.close()

# ---------- production binary: real accessibility not granted ----------
if PROD_BIN:
    print("[production binary: permission not granted]")
    env = dict(os.environ); env["KAI_BRIDGE_BUNDLE_ID"] = BID
    p = subprocess.Popen([PROD_BIN], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, env=env)
    p.stdin.write(json.dumps(req("desktop.observe_window", windowId=42)) + "\n"); p.stdin.flush()
    resp = json.loads(p.stdout.readline())
    reason = (resp.get("reason") or "").upper()
    safe = any(x in reason for x in ("PERMISSION_NOT_GRANTED", "DESKTOP_UNAVAILABLE",
                                     "WINDOW NOT FOUND", "NO BOUNDS", "REFUSING TO ACT AS"))
    # Fail-closed: real capability probes run and the binary never returns ok on an
    # unverifiable/absent target. (On this host a CLI inherits an ancestor's Accessibility
    # grant via responsible-process attribution -- which is exactly why the shipped helper
    # must be its OWN signed bundle so TCC attributes to it, not to Terminal/python.)
    if resp.get("ok") is False and safe:
        print(f"  ok   production binary fails closed on unverifiable target ({reason.split(':')[0][:40]})"); PASS += 1
    else:
        print(f"  FAIL production binary did not fail closed: {resp}"); FAIL += 1
    try: p.stdin.close(); p.wait(timeout=5)
    except Exception: p.kill()

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n=== {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)
