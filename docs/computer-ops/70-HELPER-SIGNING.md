# Desktop Helper — Build and Signing State

**Status: BLOCKED_CODESIGNING_IDENTITY.** The helper is built and its gate is tested, but
it cannot be signed on this machine, so no TCC grant may be requested.

## Why signing gates this and not something else

macOS attributes a TCC grant (Screen Recording, Accessibility) to the **executable**, not
to the script it runs. Granting Screen Recording to `/usr/bin/python3` grants it to every
Python script on the machine — now and in future, including anything an attacker drops
there later. The same is true of `node`, `bash`, Terminal, Claude Code and the harness
process.

An **ad-hoc** signature is not a stable identity either: its code-directory hash changes
on every rebuild, so a grant made against today's build silently stops applying tomorrow.
The natural response to that — re-granting, or granting something broader that "stays
working" — is precisely the outcome to avoid. An over-broad grant that works is worse than
a narrow one that is missing.

So the helper refuses to act unless it presents `com.wheellsverse.kai.desktopbridge`, and
this build cannot.

## Build artefact (measured)

| Field | Value |
|---|---|
| Source | `ops/computer-ops/helper/Sources/KaiDesktopBridge/main.swift` (Swift 6.3.3) |
| Binary | `ops/computer-ops/helper/.build/release/KaiDesktopBridge` |
| Type | Mach-O 64-bit executable arm64 |
| Size | 145,888 bytes |
| SHA-256 | `bd7428675b591daf9a526c74e695e7e60d783d914748dedb3352d38f836d2713` |
| Required bundle id | `com.wheellsverse.kai.desktopbridge` |
| Actual identifier | `KaiDesktopBridge` (SwiftPM default — NOT the bundle id) |
| Signature | `adhoc, linker-signed` (`flags=0x20002`) |
| Entitlements | none |
| Notarization | `spctl: rejected` |
| Signing identities available | **0 valid identities found** |
| Team ID | none — no Developer ID or Apple Development certificate on this machine |

## What the helper does today

Its gate is complete and tested (17/17, `test_helper_gate.py`) with **no TCC granted**:

- closed verb vocabulary — `desktop.{probe,list_windows,observe_window,focus_window,
  click_accessibility_element,type_text,press_shortcut,launch_approved_application,stop}`.
  There is no shell verb, no AppleScript verb, no raw-coordinate verb and no file verb;
  unknown verbs are refused rather than passed through.
- STOP outranks everything and needs neither identity nor TCC.
- Ordered gate: STOP → identity → mission/device binding → desktop probe → TCC probe →
  app allowlist (default deny) → approval → fresh observation → staleness → title change →
  sensitive-window check → focus-change (user intervention) → rate limit.
- Observation tokens expire in 8s and bind window id, app, title-at-observation and the
  frontmost app, so "click the thing I saw" cannot act on a screen that has since changed.
- Sensitive windows (password managers, Keychain, System Settings, Messages/Mail) and
  sensitive titles (2FA, recovery codes, banking, payment, immigration, healthcare) are
  **blocked, not masked** — masking cannot be guaranteed across window moves and Spaces.
- Actions are rate-limited to 20/min independently of anything upstream.

**Execution is deliberately withheld.** Even when the whole gate passes, a mutating verb
returns `GATE_PASSED_EXECUTION_WITHHELD` in this unsigned build. The effecting code lands
with the signed build; shipping it now would create a binary that performs desktop actions
under an identity that changes on every rebuild.

## What an operator must decide before this can proceed

1. Obtain an Apple **Developer ID Application** certificate (a paid Apple Developer
   account). Nothing here can create one.
2. Package the binary as a `.app` with `CFBundleIdentifier = com.wheellsverse.kai.desktopbridge`.
3. Sign with hardened runtime, then notarize and staple.
4. Only then grant, in System Settings → Privacy & Security:
   - **Accessibility** — for window observation and interaction
   - **Screen Recording** — only if window capture is later enabled
5. Re-run `test_helper_gate.py` against the signed bundle before any desktop verb is used.

Do not grant TCC to Terminal, Claude Code, `python3`, `node` or the harness. If the helper
asks for a grant under any identity other than the bundle id above, refuse it.
