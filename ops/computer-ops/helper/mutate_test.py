#!/usr/bin/env python3
"""Mutation testing for the KAI Desktop Bridge gate.

Neuter each major guard in turn, rebuild the -DKAI_TEST_HARNESS binary, run the
adversarial suite, and require it to FAIL (mutant killed). A SURVIVOR = a guard
removable with no test noticing = a coverage gap. Restores main.swift
byte-identically afterward (verified by sha256).
"""
import hashlib, subprocess, sys, os

SRC = "Sources/KaiDesktopBridge/main.swift"
BIN = ".build/release/KaiDesktopBridge"

MUTANTS = [
    ("identity check", 'if verb != .probe && !identityAcceptable() {', 'if verb != .probe && false {'),
    ("approval required", 'if (req.policyDecision ?? "") != "APPROVED" {', 'if (req.policyDecision ?? "") != "APPROVED" && false {'),
    ("request expiry", 'if let exp = req.expiresAt, now > exp { return deny(req, "request expired", category: "expired") }',
     'if let exp = req.expiresAt, false { return deny(req, "request expired", category: "expired") }'),
    ("expiresAt required", 'if verb.mutating && req.expiresAt == nil {', 'if false && req.expiresAt == nil {'),
    ("nonce replay", 'if consumedNonces[n] != nil { return deny(req, "nonce replay/duplicate refused", category: "replay") }',
     'if false { return deny(req, "nonce replay/duplicate refused", category: "replay") }'),
    ("focused-window binding", 'if let fwb = focusedWindowBounds(), !boundsApproximatelyEqual(fwb, obs.bounds) {',
     'if let fwb = focusedWindowBounds(), false && !boundsApproximatelyEqual(fwb, obs.bounds) {'),
    ("reset guards operator STOP",
     'if FileManager.default.fileExists(atPath: STOP_SENTINEL) {\n            return deny(req, "operator STOP sentinel present; clear it out-of-band (rm the STOP file); " +',
     'if false {\n            return deny(req, "operator STOP sentinel present; clear it out-of-band (rm the STOP file); " +'),
    ("operator allowlist", 'if let op = operatorAllowlist() {', 'if let op = operatorAllowlist(), false {'),
    ("title-change", 'if live.title != obs.title { return deny(req, "window title changed since observation", category: "stale") }',
     'if false { return deny(req, "window title changed since observation", category: "stale") }'),
    ("geometry-change", 'guard let liveBounds = windowBounds(obs.windowId), liveBounds == obs.bounds else {',
     'guard let liveBounds = windowBounds(obs.windowId), liveBounds == liveBounds else {'),
    ("pid/window reuse", 'if live.pid != obs.pid {   // kCGWindowOwnerPID is stable; same pid => same process (bundle-id derivation flakes)', 'if false {   // kCGWindowOwnerPID is stable; same pid => same process (bundle-id derivation flakes)'),
    ("frontmost window guard", 'if frontmostWindowId() != obs.windowId {\n                return deny(req, "target window is not frontmost; refusing background action", category: "focus")', 'if false {\n                return deny(req, "target window is not frontmost; refusing background action", category: "focus")'),
    ("secure field (type)", 'if focusedElementIsSecureOrUnknown() {', 'if false {'),
    ("click point-inside", 'if !obs.bounds.contains(point) { return deny(req, "click point outside target window",',
     'if false { return deny(req, "click point outside target window",'),
    ("type length cap", 'if t.count > MAX_TYPE_CHARS { return deny(req, "text exceeds \\(MAX_TYPE_CHARS)-char cap",',
     'if false { return deny(req, "text exceeds \\(MAX_TYPE_CHARS)-char cap",'),
    ("shortcut allowlist", 'guard let sc = req.shortcut, ALLOWED_SHORTCUTS[sc] != nil else {',
     'guard let sc = req.shortcut, true || ALLOWED_SHORTCUTS[sc] != nil else {'),
    ("STOP active", 'if stopEngaged() && verb != .probe {', 'if false && verb != .probe {'),
    ("audit fail-closed",
     '            return deny(req, "AUDIT_UNAVAILABLE: cannot persist audit record; refusing to act",\n                        category: "audit")',
     '            _ = deny(req, "AUDIT_UNAVAILABLE: cannot persist audit record; refusing to act",\n                        category: "audit")'),
    ("multi-controller", 'if !haveController, Verb(rawValue: req.verb)?.mutating == true {', 'if false, Verb(rawValue: req.verb)?.mutating == true {'),
    ("sensitive-app observe", 'if win.sensitive { return deny(req, "sensitive window: capture/observe blocked, not masked",',
     'if false { return deny(req, "sensitive window: capture/observe blocked, not masked",'),
    ("evidence path confinement", '.appendingPathComponent((cap as NSString).lastPathComponent)).standardizedFileURL.path',
     '.appendingPathComponent(cap)).standardizedFileURL.path'),
]
orig = open(SRC).read()
orig_sha = hashlib.sha256(orig.encode()).hexdigest()

def build():
    r = subprocess.run(["swift", "build", "-c", "release", "-Xswiftc", "-DKAI_TEST_HARNESS"],
                       capture_output=True, text=True)
    return r.returncode == 0

def run_suite():
    r = subprocess.run(["python3", "test_bridge_adversarial.py", BIN], capture_output=True, text=True)
    return r.returncode  # 0 = all passed (survivor if mutated), nonzero = a case failed (killed)


killed, survived, skipped = [], [], []
for name, find, repl in MUTANTS:
    n = orig.count(find)
    if n != 1:
        skipped.append((name, f"anchor matched {n}x")); continue
    open(SRC, "w").write(orig.replace(find, repl))
    if not build():
        killed.append((name, "did not compile (mutant rejected)"))
    else:
        rc = run_suite()
        (killed if rc != 0 else survived).append((name, "suite failed" if rc != 0 else "SUITE STILL PASSED"))
    open(SRC, "w").write(orig)  # restore pristine

# final restore verification
open(SRC, "w").write(orig)
final_sha = hashlib.sha256(open(SRC).read().encode()).hexdigest()
build()  # leave a valid test binary in place

print("\n=== MUTATION RESULTS ===")
for name, why in killed:    print(f"  KILLED   {name}  ({why})")
for name, why in survived:  print(f"  SURVIVED {name}  ({why})  <-- COVERAGE GAP")
for name, why in skipped:   print(f"  SKIPPED  {name}  ({why})")
print(f"\nkilled={len(killed)} survived={len(survived)} skipped={len(skipped)}")
print(f"main.swift restore byte-identical: {orig_sha == final_sha}  ({final_sha[:16]}...)")
sys.exit(1 if (survived or skipped) else 0)
