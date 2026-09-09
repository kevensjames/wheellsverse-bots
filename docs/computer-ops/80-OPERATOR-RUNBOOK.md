# KAI Desktop Bridge — Operator Runbook (signing → TCC → desktop certification)

Sequential steps to move from the accepted checkpoint to a verified, TCC-granted desktop
helper. Each step names its owner. **Do not skip the gate in step 4:** it is the only
thing that decides whether TCC may be granted, and it fails closed.

Current state: signing identities on this machine = 0, so today you can complete steps
1–2's build/package and will stop at step 3 until you have an Apple identity.

---

## Step 1 — Build and package the helper  (you can run this now)

```sh
cd /Users/jhonwheeler/wheellsverse-kai-compute/ops/computer-ops/helper
swift build -c release
./make_app_bundle.sh
# -> dist/KaiDesktopBridge.app  (CFBundleIdentifier com.wheellsverse.kai.desktopbridge, UNSIGNED)
```

Sanity-check the unsigned bundle is correctly BLOCKED (this is the expected answer, not a
problem):

```sh
./verify_signing.sh dist/KaiDesktopBridge.app   # RESULT: BLOCKED, exit 1
```

## Step 2 — Obtain an Apple signing identity  (operator; requires an Apple account)

Two options; the gate accepts either, but they differ in durability:

- **Apple Development** — free with any Apple ID via Xcode. Sufficient for a helper built
  here and never downloaded. Its designated requirement pins the certificate leaf CN, so
  re-verify after any certificate renewal (gate criterion 5 below).
- **Developer ID Application** — paid Apple Developer Program. Preferred long term: its DR
  pins the Team ID, so it survives certificate renewal, and it can be notarized if the
  helper is ever distributed.

Confirm it landed:

```sh
security find-identity -v -p codesigning     # must list one identity; currently lists 0
```

Never substitute ad-hoc signing. The gate rejects it because an ad-hoc DR is this build's
content hash and changes on every rebuild.

## Step 3 — Sign the bundle  (operator)

```sh
cd /Users/jhonwheeler/wheellsverse-kai-compute/ops/computer-ops/helper
codesign --force --options runtime --timestamp \
         --sign "<IDENTITY NAME FROM STEP 2>" \
         dist/KaiDesktopBridge.app
```

`--options runtime` (hardened runtime) is required by the gate; `--timestamp` is required
for later notarization if you ever choose Developer ID + distribution.

## Step 4 — Pass the signing gate  (the acceptance test; must exit 0)

```sh
./verify_signing.sh dist/KaiDesktopBridge.app
```

This is the single gate that authorizes TCC. It checks nine things; the ones that matter:

1. identifier is exactly `com.wheellsverse.kai.desktopbridge`
2. signature is not ad-hoc
3. Team ID present
4. designated requirement is certificate-anchored, **not** a cdhash
5. **DR is stable across a rebuild** — rebuild, re-package, re-sign, re-run; the DR string
   must be byte-identical. This is the check that tells you whether your identity survives
   rebuilds/renewal. If it changes, prefer Developer ID.
6. hardened runtime enabled
7. Gatekeeper (only decisive if the helper will ever be downloaded)
8. the helper self-reports an acceptable identity
9. the behavioural gate suite passes against this exact artefact

**Do not proceed to step 5 unless this exits 0.**

## Step 5 — Grant TCC to the signed bundle ONLY  (operator; System Settings)

System Settings → Privacy & Security →
- **Accessibility** — for window observation and interaction
- **Screen Recording** — only if you will use window capture

Grant to `dist/KaiDesktopBridge.app` (or wherever you install it) and to nothing else.
**Never** grant to Terminal, Claude Code, `python3`, `node`, or the harness. Confirm:

```sh
printf '{"id":"1","verb":"desktop.probe"}\n' \
  | dist/KaiDesktopBridge.app/Contents/MacOS/KaiDesktopBridge
# expect: accessibility_granted:true (and screen recording if granted)
```

## Step 6 — Scoped desktop-control certification  (two prerequisites, then a cert run)

There are TWO things gating this, in order:

**6a. A verified signed helper (steps 3–4) AND a TCC grant (step 5).** Until then, every
mutating verb is refused, correctly.

**6b. The desktop-effecting code is intentionally NOT written yet.** The current helper
returns `GATE_PASSED_EXECUTION_WITHHELD` even when the full gate passes — it validates and
refuses rather than acting, because shipping code that drives the mouse/keyboard/screen
under an identity that changes every rebuild would be exactly wrong. The effecting
increment (screencapture, AXUIElement observation, CGEvent input) is the next CODING task,
and it should be done AFTER 6a so it can be certified against a real grant instead of blind.

When you have completed 6a, hand the signed `.app` path back and the effecting code +
scoped desktop-control certification is the next increment: it will drive, under
EXECUTE_SCOPED with fresh bound approvals, only the typed verbs against an allowlisted test
application, with STOP, fresh-observation binding, sensitive-window blocking and evidence —
and prove each on the real desktop.

## Step 7 — Staging  (requires your SEPARATE authorization)

Do not deploy to staging as part of desktop work. When you authorize it, follow
`docs/computer-ops/60-STAGING-PLAN.md`: flags off first, external anonymous probes of the
auth/limits/SSE surfaces, `verify_signing.sh` against the staging helper artefact, then
enable. Production stays untouched until both the desktop and staging certifications pass.

---

## Quick reference

| Want | Command |
|---|---|
| Build + package | `swift build -c release && ./make_app_bundle.sh` |
| Check signing state | `security find-identity -v -p codesigning` |
| Sign | `codesign --force --options runtime --timestamp --sign "<ID>" dist/KaiDesktopBridge.app` |
| **Acceptance gate** | `./verify_signing.sh dist/KaiDesktopBridge.app` (exit 0 = may grant TCC) |
| Confirm TCC | probe the binary; `accessibility_granted:true` |
| Emergency | STOP in the panel; `desktop.stop` verb; both need no TCC and no signature |
