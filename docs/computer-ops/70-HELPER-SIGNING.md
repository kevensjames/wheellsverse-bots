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


---

# Signing requirement audit — Developer ID vs Apple Development

**Question:** does this local deployment actually need a *Developer ID Application*
certificate, or does an *Apple Development* certificate give a designated requirement
stable enough for TCC to persist?

**No credential was requested, created, imported or exported to answer this.** The
finding below is derived from designated requirements read off binaries already present
on this machine.

## The mechanism: TCC keys on the designated requirement

macOS records a TCC grant against a binary's **designated requirement** (DR), not its
path. Whether a grant survives a rebuild is therefore decided entirely by what the DR
pins. Measured on this machine:

| Binary | Designated requirement | Survives rebuild? |
|---|---|---|
| `/Applications/Claude.app` (Developer ID) | `identifier "com.anthropic.claudefordesktop" and anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = Q6L2SF6YDW` | **Yes** — pins bundle id + Team ID (OU) |
| `/System/Applications/Calculator.app` (Apple) | `identifier "com.apple.calculator" and anchor apple` | Yes (Apple-anchored) |
| **our helper (ad-hoc)** | `cdhash H"0b833b4f23980dd869d7b2a57d8f3f4c67a308ff"` | **No** — pins THIS build's hash |

That last row is the whole blocker, stated as evidence rather than assertion: an ad-hoc
DR is a content hash, so every rebuild produces a different DR and any TCC grant made
against the previous one silently stops matching.

## What each certificate type gives

**Developer ID Application** — DR pins `subject.OU` = Team ID. Rebuilds keep the DR, and
so does *certificate renewal*, because the OU is the team, not the individual leaf. Also
notarizable, which matters only if the helper is ever downloaded. Requires the paid Apple
Developer Program.

**Apple Development** — DR pins `certificate leaf[subject.CN] = "Apple Development: NAME (ID)"`.
Rebuilds keep the DR, so **TCC persistence across rebuilds does work**. Available with a
free Apple ID through Xcode. Two caveats:

1. *Renewal.* The DR pins the leaf CN. If a renewed certificate carries an identical CN
   the DR still matches; if the CN changes, the grant breaks and must be re-granted. This
   is the one thing this audit could NOT determine from the outside, so it is a
   verification step below rather than a claim.
2. *Gatekeeper.* An Apple Development signature is not notarized, so a **quarantined**
   copy would be blocked. A helper built and run locally is never quarantined (no
   `com.apple.quarantine` attribute), so Gatekeeper is not triggered for this deployment.
   The moment the helper is copied off this machine and downloaded back, that changes.

## Finding

For a helper that is **built on the operator's machine and never distributed**, an
**Apple Development certificate is sufficient** to give a stable designated requirement,
and therefore sufficient for TCC to persist across rebuilds. Developer ID is required
only if the helper will ever leave this machine, and is preferable regardless because its
DR survives certificate renewal.

This is a *finding, not a recommendation to skip Developer ID*: the cheaper path works for
the local case, and the operator should choose knowing that a Developer-ID DR is the more
durable of the two.

## Exact operator commands

Nothing here may be run by KAI. Each step is the operator's.

```sh
# 1. See what identities exist (this machine currently reports "0 valid identities found")
security find-identity -v -p codesigning

# 2. Package the binary as an app bundle with the required identifier
#    (CFBundleIdentifier MUST be exactly com.wheellsverse.kai.desktopbridge)

# 3. Sign with hardened runtime
codesign --force --options runtime --timestamp \
         --sign "<IDENTITY FROM STEP 1>" \
         /path/to/KaiDesktopBridge.app

# 4. Read back the designated requirement -- this is the acceptance criterion
codesign -d -r- /path/to/KaiDesktopBridge.app
```

### Verification criteria — all must hold before any TCC grant

| # | Criterion | Command / expected |
|---|---|---|
| 1 | Identifier is exactly the bundle id | `codesign -dvv …` → `Identifier=com.wheellsverse.kai.desktopbridge` |
| 2 | Signature is NOT ad-hoc | `codesign -dvv …` → `Signature=…` must not contain `adhoc` |
| 3 | Team ID present | `codesign -dvv …` → `TeamIdentifier=<10 chars>`, not `not set` |
| 4 | DR does NOT pin a cdhash | `codesign -d -r- …` → must contain `anchor apple generic`, must NOT be `cdhash H"…"` |
| 5 | DR is stable across a rebuild | rebuild, re-sign, re-run step 4 → DR string byte-identical |
| 6 | Hardened runtime enabled | `codesign -dvv …` → `flags=…(runtime)` |
| 7 | Gatekeeper (only if it will ever be downloaded) | `spctl -a -vvv …` → `accepted`; requires notarization |
| 8 | Helper self-reports an acceptable identity | `echo '{"id":"1","verb":"desktop.probe"}' \| ./KaiDesktopBridge` → `identity_acceptable: true` |
| 9 | Gate suite passes against the SIGNED bundle | `python3 ops/computer-ops/helper/test_helper_gate.py <path>` → 17/17 |

**Criterion 5 is the one that decides Apple Development vs Developer ID for renewal.**
Re-run it after the certificate is renewed: if the DR changed, the TCC grant will need to
be re-issued, and Developer ID is the better choice going forward.

Only when 1–6, 8 and 9 hold may Screen Recording and Accessibility be granted, and only
to the signed bundle. Never to Terminal, Claude Code, `python3`, `node`, or the harness.
