# KAI Computer Operations — Requirements / Evidence Matrix

Status vocabulary (mission §12):
**IMPLEMENTED** · **TESTED_LOCALLY** · **DEVICE_CONTROL_VERIFIED** ·
**HOLDING_PANEL_VERIFIED** · **HOSTED_DEPLOYMENT_VERIFIED** · **BLOCKED / NOT_CERTIFIED**

Branch `feat/kai-computer-operations`, base `origin/production` @ `073c9a4`.
Nothing is deployed. Production is untouched.

**Phases 6-9 update (session 2).** The containment model was rebuilt: a deny-list of
named plugins was replaced by a kernel jail plus an immutable allow-list, because a
deny-list fails open on anything upstream adds -- and had already failed once. Device
principals, dispatch contracts and the two platform defects are done. Phases 10-12
(panel, bridge executable identity, certification) are NOT done; see the tail of this
file.

## §1 Inspect before changing anything

| Requirement | Status | Evidence |
|---|---|---|
| Record repo, branch, HEAD, dirty files | TESTED_LOCALLY | `00-DISCOVERY.md` §6 |
| Actual host OS/arch/memory/disk/runtimes | TESTED_LOCALLY | `00-DISCOVERY.md` §1–2, probed |
| Distinguish dev host / local server / target desktop | TESTED_LOCALLY | Verified same machine (Mac mini M4, Aqua session live). Not assumed |
| Pin exact upstream commit; license, lockfile, install scripts, network, credentials | TESTED_LOCALLY | `00-DISCOVERY.md` §5, `10-EVIDENCE.md` E1, E6 |
| Do not invent SDK methods / routes / flags | TESTED_LOCALLY | Every method used is exercised in E3; wire shapes read from the vendored ACP SDK |
| Preserve unrelated changes; isolated branch/worktree | TESTED_LOCALLY | Separate worktree; `feat/kai-freellmapi` untouched; no SOL files changed |

## §2 Architecture

| Requirement | Status | Evidence |
|---|---|---|
| Reuse Capability Fabric, ModelRouter, missions, evidence, identity, approvals, Feature Registry, Presence | **NOT STARTED** | Reuse map produced (24 components, exact paths) but no backend code written |
| A Holding Command / B backend / C connector / D worker / E bridge boundaries | PARTIAL | C, D, E implemented. A and B not started |
| Harness must not receive unrestricted desktop privileges | TESTED_LOCALLY | Harness has no desktop capability, and the shell that could reach `screencapture`/`osascript` is removed and asserted |
| Narrow maintained adapter, not UI scraping | TESTED_LOCALLY | ACP v1, a documented automation protocol. No scraping |

## §3 Local installation

| Requirement | Status | Evidence |
|---|---|---|
| Install pinned harness OUTSIDE production source | TESTED_LOCALLY | `/Users/jhonwheeler/kai-harness-runtime` |
| Determine node/pnpm from pinned source; documented build; preserve lockfile | TESTED_LOCALLY | `pnpm@11.7.0`, node `^22.19.0`; `--frozen-lockfile`; E1 |
| Inspect installation hooks before running them | TESTED_LOCALLY | 5 lifecycle scripts / 292 packages reviewed BEFORE install; E1 |
| Bind upstream UI to loopback only / no unauthenticated UI or exec endpoint | TESTED_LOCALLY | The web UI is never started. ACP is stdio; **no listening socket at all** |
| Service definition for the actual OS; separate background service from desktop helper | IMPLEMENTED | `runtime/com.wheellsverse.kai-harness.plist.template` — LaunchAgent (not Daemon) because TCC grants require a user session |
| start/stop/status/restart/upgrade/uninstall | IMPLEMENTED | `runtime/kai-harness-ctl.sh`; `status` output captured |
| Do not enable persistent startup without operator approval | TESTED_LOCALLY | Template deliberately not loaded; `launchctl list \| grep kai-harness` → 0 |
| No privileged containers, docker socket, home mounts, sudo, disabled security | TESTED_LOCALLY | None used. Runs as the unprivileged user |
| Backups and rollback to previous pinned version | IMPLEMENTED | `upgrade` records a rollback point (commit + lockfile) before changing anything |

## §4 Model configuration

| Requirement | Status | Evidence |
|---|---|---|
| LOCAL_ONLY against an approved local endpoint | TESTED_LOCALLY | E3: full ACP round trip answered by local `qwen2.5:7b` |
| CLOUD_APPROVED with explicit egress consent | **NOT STARTED** | No overlay written |
| Do not silently fall back local → cloud | TESTED_LOCALLY | Structural: cloud adapter disabled in the same overlay; settings-override path closed; race retries the SAME route and raises `MODEL_UNAVAILABLE` |
| Show actual provider, model, endpoint category, execution location | IMPLEMENTED | Attestation records them; no panel to display them yet |
| Separate status for harness execution vs local inference | IMPLEMENTED | Distinct fields in the attestation/capability reports; not yet surfaced |
| Report MODEL_UNAVAILABLE truthfully | TESTED_LOCALLY | `session_new()` raises it rather than substituting a provider |
| No large model download without inspection and approval | TESTED_LOCALLY | Nothing downloaded; existing local models used |

## §5 Secure local-device connection

| Requirement | Status |
|---|---|
| Authenticated outbound connection from connector to backend | **NOT STARTED** — reuse target identified (`holding_worker_jobs`) |
| Device pairing, owner verification, unique revocable identity | **BLOCKED** — no enrollment primitive exists on this branch; requires operator policy |
| Short-lived device-bound task grants; expiry, nonce/replay, idempotency | **NOT STARTED** — reuse target identified (`action_confirmation`, migration `0007`) |
| Never execute stale queued commands after reconnect | **NOT STARTED** |
| Browser must not connect to localhost; no router ports | TESTED_LOCALLY — ACP is stdio; nothing listens |

## §6 Computer-control capabilities

| Capability | Status |
|---|---|
| Inspect enrolled-device health | IMPLEMENTED (bridge `probe` / `capability_report`) |
| Search/read approved folders | PARTIAL — harness `tool-fs`/`tool-fs-search` confined by `fs-sandbox` + workspace root |
| Create/edit files in approved task workspaces | TESTED_LOCALLY — EXECUTE_SCOPED composes `workspace-write`; write refused in read-only modes (observed) |
| Run authorized development commands in isolation | **DELIBERATELY NOT via the harness.** Harness shell removed after it was measured bypassing approvals. Must be a KAI capability with server-owned argv |
| Launch approved applications | IMPLEMENTED (`launch_app`, returns REQUIRE_APPROVAL) — not executed |
| Browser automation in dedicated profiles | **NOT STARTED**; note the existing KAI browser package is dead code in deployed App B (no `playwright` in backend requirements) |
| Capture approved screen/window content | IMPLEMENTED, **BLOCKED** on TCC grant |
| Interact with approved windows via accessibility | IMPLEMENTED (`list_windows`), **BLOCKED** on TCC grant |
| Run tests and prepare evidence | **NOT STARTED** |
| Connect existing voice I/O to the same mission path | **NOT STARTED** |
| Report desktop unavailable when no interactive desktop | TESTED_LOCALLY — `DESKTOP_UNAVAILABLE` vs `PERMISSION_NOT_GRANTED` are distinct, probed states |
| Do not bypass permission dialogs / collect passwords / read password managers | TESTED_LOCALLY — 13/13 gate checks incl. sensitive-app block and credential-path denial |

## §7 Practical autonomy

| Requirement | Status | Evidence |
|---|---|---|
| OBSERVE / ASSIST / EXECUTE_SCOPED modes | TESTED_LOCALLY | All three composed and attested 25/25 each |
| APPROVAL_REQUIRED for consequential actions | PARTIAL | Bridge returns `REQUIRE_APPROVAL`; KAI-side minting not wired |
| Bind approval to device/action/target/params/scope/expiry; invalidate on change | **NOT STARTED** | Reuse target identified and verified to exist |
| Never approve through the automation being approved | IMPLEMENTED (design) | No bridge verb can click an approval; `interpret_confirmation()` already refuses voice/gesture |
| Do not weaken controls to make a demo succeed | HELD | The bash bypass was fixed rather than accepted, at the cost of removing the shell |

## §8 Holding Command panel

**NOT STARTED.** No panel, route, or navigation entry added. Note for whoever builds it:
`admin_holding.py`'s docstring claims GET-only while the module already defines 14 POST
routes — the genuinely read-only surfaces that must not become a console are the 13
Command-OS GETs and `/admin/capabilities*`.

## §6b Containment model (session 2)

| Requirement | Status | Evidence |
|---|---|---|
| Immutable per-mode plugin allow-list | TESTED_LOCALLY | `connector/allowlist.py`, 63 permitted (id, package) pairs |
| Enumerate the effective composed plugin graph at startup | TESTED_LOCALLY | `parse_entries()` over `dsh --dump-config` |
| Fail closed on unknown / redefined / non-allowlisted / missing | TESTED_LOCALLY | 12/12 negative checks; live injection into the real composition refused |
| Composition digest attested after every patch merge | TESTED_LOCALLY | `composition_digest()`; stable across missions, changes on any composition change |
| Reject on-disk settings overriding routing/credentials/sandbox/workspace/approval/tools/network | TESTED_LOCALLY | settings seam disabled and asserted; it was measured to override LLM routing |
| Prove `danger-full-access` structurally unreachable | TESTED_LOCALLY | absent from every composed mode (`verify_modes.py`) |
| Shell / PowerShell / process exec / unrestricted file access / web tools unavailable in all modes | TESTED_LOCALLY | asserted in the allow-list AND enforced by the jail independently |
| Negative test: fake shell/network plugin rejected at startup | TESTED_LOCALLY | `verify_gate.py` injects one into the real composition; refused |
| Symlink, canonicalisation, hardlink, env expansion, workspace replacement | TESTED_LOCALLY | 21/21 in `verify_jail.py`, all behavioural |
| Behavioural tests of reachable execution paths, not named-plugin assertions | TESTED_LOCALLY | every check performs a real operation and observes the kernel |
| Outer execution boundary; worker has no general internet | TESTED_LOCALLY | Seatbelt jail: external egress denied, only the approved model endpoint reachable, proven against a live listener on another loopback port |
| Worker limited to workspace / broker / approved model / IPC | TESTED_LOCALLY | writes confined to named subtrees of a per-mission APFS volume |
| Evaluate safest practical containment on this host | TESTED_LOCALLY | Seatbelt chosen; docker daemon not running, VM needs an operator decision. `jail.wrap()` is the swap seam |
| Desktop helper outside the harness worker, typed verbs only | IMPLEMENTED | bridge is a sibling, unreachable from the jail (its binaries are exec-denied) |

## §7 Device identity and enrollment (session 2)

| Requirement | Status |
|---|---|
| Dedicated machine principal / credential type | TESTED_LOCALLY - `KAI_DEVICE` / `DEVICE_BOUND_ED25519` |
| Device credential does not inherit owner permissions | TESTED_LOCALLY - role is `device`; cannot be constructed as owner |
| Owner-authenticated enrollment, one-time short-TTL pairing code | TESTED_LOCALLY - single-use, 10 min, stored hashed |
| Operator confirmation showing device name and fingerprint | TESTED_LOCALLY - grouped fingerprint, constant-time compare |
| Unique device id, public-key proof of possession | TESTED_LOCALLY - Ed25519 over a server challenge |
| Encrypted credential storage | PARTIAL - only PUBLIC keys are stored server-side; the device's private key never leaves it. Keychain storage on the device is not yet written |
| Narrow scopes; desktop/browser/workspace-write need separate activation | TESTED_LOCALLY - baseline vs elevated, each activated individually |
| Rotation, revocation, last-seen, lease expiry, replay protection | TESTED_LOCALLY - 33/33 |
| Loss/replacement recovery | PARTIAL - revoke + re-enroll works; no dedicated recovery flow |
| Audit events | PARTIAL - state transitions recorded; not yet emitted to the audit sink |
| Migration only if needed; preserve existing sessions | TESTED_LOCALLY - migration 0008, additive, chained 0007->0008, downgrade drops indexes only |

## §8 Backend dispatch (session 2)

| Requirement | Status |
|---|---|
| Reuse worker_jobs / action_confirmation / brakes / injection scanning / bridge | IMPLEMENTED - dispatch composes them; no parallel mission system |
| Typed contracts for the 15 listed operations | PARTIAL - lifecycle, lease, progress, approval, evidence, cancel, STOP, reconnect implemented as service functions; enroll/confirm/list/revoke/scope-update and history/health NOT yet, and none are wired to HTTP routes |
| Full envelope on every operation | TESTED_LOCALLY - all 14 fields present and expiry-checked |
| A worker cannot set COMPLETED | TESTED_LOCALLY - `WORKER_REPORTABLE` excludes it; verifier disagreement yields FAILED |
| Only KAI transitions to COMPLETED after independent verification | TESTED_LOCALLY - `verify_and_complete()` is the only path |
| Reconnect: discard expired leases, reject replays, no auto-resume of desktop, revalidate | TESTED_LOCALLY - defaults to no-resume; six refusal paths |
| Preserve truthful state for completed actions | TESTED_LOCALLY - STOP halts future work, evidence retained |

## §9 Privacy and containment

| Requirement | Status |
|---|---|
| Treat pages/documents/screenshots/plugins/tool output as untrusted | IMPLEMENTED (design + injection-scanner reuse identified) |
| Enforce policy outside the model and outside harness prompts | TESTED_LOCALLY — connector answers `session/request_permission`; containment is composition-level |
| Workspace isolation, network restrictions, safe path resolution, secret redaction | PARTIAL — workspace + egress-tool removal verified; container isolation unavailable (colima down) |
| Screenshots opt-in and minimally retained; block where masking cannot be guaranteed | IMPLEMENTED — capture is per-mission opt-in; sensitive apps blocked, not masked |
| Never auto-install plugins, expand scopes, rewrite policy, promote memories | TESTED_LOCALLY — `skill-filesystem`/`tool-skill` disabled and asserted |

## §10 Emergency stop and recovery

| Requirement | Status |
|---|---|
| Authenticated backend STOP | **NOT STARTED** — reuse target `brakes.stop()` verified to exist |
| Independent local stop | IMPLEMENTED — `AcpClient.close()` and `kai-harness-ctl.sh stop`; bridge `stopped` outranks every check (tested) |
| STOP cancels workers and releases desktop control | PARTIAL — `session/cancel` exercised; bridge STOP tested; not wired end to end |
| Never resume desktop actions after restart without revalidation | IMPLEMENTED (design) — per-mission child cannot survive |
| Measure stop latency across generation/shell/browser/desktop | **NOT DONE** |

## §11 Verification — the 14 required tests

| # | Test | Status |
|---|---|---|
| 1 | Inspect an approved test repository | NOT RUN |
| 2 | Edit a file in an isolated workspace, show diff | PARTIAL — write correctly REFUSED in read-only; EXECUTE_SCOPED path not exercised |
| 3 | Run tests and independently verify | NOT RUN |
| 4 | Open a harmless test application/window | BLOCKED (TCC) |
| 5 | Browser task against a local test site | NOT RUN |
| 6 | Show and deny a consequential-action approval | PARTIAL — bridge returns `REQUIRE_APPROVAL`; connector denies by default (`permission_handler` defaults to REJECT) |
| 7 | Interrupt a running task with STOP | PARTIAL — `session/cancel` sent and accepted; mid-generation latency not measured |
| 8 | Disconnect/reconnect without duplicate or stale execution | NOT RUN |
| 9 | Reject access outside approved paths | TESTED_LOCALLY (bridge gate; harness `fs-sandbox`) |
| 10 | Reject malicious instructions embedded in a page/document | NOT RUN — the ingestion path does not exist yet |
| 11 | Reject expired/replayed approvals | NOT RUN — minting not wired |
| 12 | Reject cross-tenant/device commands | NOT RUN |
| 13 | Demonstrate local-only mode with no cloud requests | **TESTED_LOCALLY — E3** |
| 14 | Verify dashboard navigation and real authenticated routes | NOT RUN — no panel |

### Required results

| Result | Status |
|---|---|
| Unauthorized actions: zero | **NOT YET TRUE AS ORIGINALLY SHIPPED.** One occurred during development: harness `bash` executed with zero approval requests under the first overlay. Found by measurement, fixed, re-verified. Zero since |
| Secret exposure: zero | Holds. No secret written to any file; placeholder credential only; `config.example.env` carries none |
| Duplicate consequential actions: zero | Not yet exercisable |
| False COMPLETED states: zero | Holds — no mission lifecycle implemented, and nothing claims completion |
| Policy bypass through raw harness access: zero | Holds after the `tool-bash` fix; asserted on every dispatch |
| STOP and revocation verified | PARTIAL |
| Independent outcome verification | NOT IMPLEMENTED |


---

## Session 2 additions — required tests (§12 adversarial list)

| Adversarial test | Status |
|---|---|
| Unknown execution plugin introduced | TESTED_LOCALLY (live injection refused) |
| On-disk settings redirect the model | TESTED_LOCALLY (settings seam disabled + asserted) |
| Ambient `OPENAI_API_KEY` present | PARTIAL - the placeholder `apiKeyEnv` prevents ambient adoption by construction; not yet exercised with a real ambient key set |
| Session created before route registration | TESTED_LOCALLY (bounded retry, `MODEL_UNAVAILABLE`, no provider fallback) |
| Shell plugin restored | TESTED_LOCALLY (allow-list refuses; jail denies exec independently) |
| Web/network plugin restored | TESTED_LOCALLY (allow-list refuses; jail denies egress independently) |
| Workspace symlink escapes | TESTED_LOCALLY |
| Request to read `.ssh` | TESTED_LOCALLY (kernel-denied) |
| Request to invoke `curl` / `osascript` / `screencapture` | TESTED_LOCALLY (exec-denied) |
| Prompt injection inside a page | NOT RUN - no page-ingestion path exists yet |
| Connector crashes while approval pending | PARTIAL - upstream `ask` fails closed with no answerer; not yet exercised as a crash |
| Device revoked during execution | TESTED_LOCALLY (reconnect refuses; scopes cleared) |
| STOP during generation and during a write | PARTIAL - `session/cancel` exercised; STOP propagation tested in dispatch; mid-write latency not measured |
| Expired / replayed approval | TESTED_LOCALLY |
| Stale job after reconnect | TESTED_LOCALLY |
| Cross-device job theft | TESTED_LOCALLY (every entry point) |
| Worker claims success while verifier fails | TESTED_LOCALLY (yields FAILED) |

### Acceptance criteria

| Criterion | Status |
|---|---|
| Unauthorized host command execution | 0 (shell removed; jail exec-denies independently) |
| Unauthorized network egress | 0 (kernel-enforced, proven against a live listener) |
| Reads outside approved scope | 0 for credential stores (kernel-denied) |
| Writes outside mission workspace | 0 (confined to named subtrees of a separate filesystem) |
| Unapproved desktop actions | 0 - no desktop verb has ever executed; TCC ungranted AND identity refused |
| Ambient credential adoption | 0 by construction; not yet adversarially exercised |
| Unknown plugins accepted | 0 |
| Settings override after attestation | 0 (seam disabled) |
| Cross-device or cross-tenant execution | 0 |
| Replayed consequential actions | 0 |
| False COMPLETED states | 0 (worker cannot set it) |
| Orphan workers after STOP | NOT MEASURED - STOP revokes leases in the dispatch layer; process-level orphan sweep not implemented |
| STOP propagation | PARTIAL |
| Device revocation | PASS |
| Crash/reconnect recovery | PARTIAL (logic tested; not exercised against a real crash) |
| Independent verification | PASS |
| Holding panel/backend truth parity | NOT APPLICABLE - no panel exists |

## Phases NOT done

- **§10 Holding Command panel — NOT STARTED.** No page, route or navigation entry. This
  is the largest remaining gap and the one most visible to an operator.
- **§11 Desktop bridge executable identity — DESIGNED, NOT BUILT.** The gate now REFUSES
  to act on the desktop under a generic interpreter identity, because granting TCC to
  `python3` would grant it to every Python script on the machine. The signed helper
  (`com.wheellsverse.kai.desktopbridge`) is specified but not built or codesigned, so
  desktop control remains unreachable by design as well as by TCC.
- **§11 typed desktop verbs** beyond the current five: `focus_window`,
  `click_accessibility_element`, `type_text`, `press_shortcut`, `stop`, plus fresh-
  observation binding, staleness rejection, rate limits, focus-change detection,
  user-intervention detection, visible activity indicator and local STOP hotkey.
- **§12 certification** as a whole: the adversarial list above is partly covered by
  targeted tests, but no end-to-end certification run exists.


---

# Session 3 — Phases 10-12 (HTTP, panel, helper, certification)

## §2 HTTP authority boundary

| Requirement | Status |
|---|---|
| Operator routes under an owner session (`require_kai_ultra`) | TESTED_LOCALLY — 15 routes at `/admin/kai/computer-operations` |
| Device routes under a KAI_DEVICE principal, separate namespace | TESTED_LOCALLY — 11 routes at `/api/kai/device` |
| Never authenticate device routes with an owner cookie / ROLE_OWNER | TESTED_LOCALLY — signature-only; no cookie path exists |
| Signature bound to method, canonical path and body digest | TESTED_LOCALLY — a signature moved to another route is refused |
| Reject unknown / revoked / unconfirmed / missing-scope / reused-nonce / expired / altered-body / wrong-device | TESTED_LOCALLY — full matrix, 63/63 HTTP + 35/35 E2E |
| A worker may never set COMPLETED | TESTED_LOCALLY — refused over real HTTP (403) |
| No raw harness config, commands or unrestricted paths exposed | TESTED_LOCALLY — no such field exists on any route model |

## §3 Catalog / execution split

| Requirement | Status |
|---|---|
| `/admin/capabilities` GET-only | TESTED_LOCALLY |
| `/admin/capability-exec` separately authenticated | TESTED_LOCALLY |
| **Anonymous sensitive admin response: 0** | TESTED_LOCALLY — every concrete `/admin` path probed anonymously, locally. NOT a claim about the deployed edge: that requires an external probe after a release |

## §4 Migration 0008

28/28 on disposable databases: upgrade, structure, types, indexes, device/nonce/code
uniqueness, pairing expiry, revocation, unrelated rows untouched, downgrade, re-upgrade.
**Downgrade is PARTIAL** — tables retained by design; documented as compatibility-
restoring, never as a schema rollback.

## §5 Local connector

| Requirement | Status |
|---|---|
| Outbound only; no listening interface | TESTED_LOCALLY |
| Authenticates as one device, signs every request | TESTED_LOCALLY — real binary used in E2E |
| Re-enforces scope locally | IMPLEMENTED |
| Per-mission APFS volume, startup gate, jailed worker | TESTED_LOCALLY |
| Honors pause / cancellation / revocation / STOP | TESTED_LOCALLY — stands down under STOP |
| Tears down worker and volume | TESTED_LOCALLY — verified no mount, no process |
| Private key in Keychain, never in repo/env/logs | IMPLEMENTED — written via stdin, not argv |
| Rejects stale work after reconnect | TESTED_LOCALLY (dispatch layer); not exercised against a real crash |

## §6 Model endpoint

| Property | Status |
|---|---|
| Only loopback reachable; all other egress denied | TESTED_LOCALLY — kernel-enforced, proven against a live listener on another port |
| Destination cannot be changed by prompt/settings/plugin | TESTED_LOCALLY — settings seam disabled; allow-list refuses substitution |
| Non-loopback endpoint refused | TESTED_LOCALLY — `JailSpec.model_hostport()` raises |
| Unix-domain IPC preferred | NOT DONE — the pinned harness's pi-ai route takes an HTTP baseURL; loopback + jail is the documented residual |
| Request/response size and concurrency bounds | NOT DONE — time bound only (mission max duration) |

## §7 Panel — `/admin/computer-ops`

Overview, Security, Devices, Mission composer, Missions/live, Approvals, fixed STOP bar.
20/20 contract checks. Screenshots: `docs/computer-ops/screenshots/`.
Real backend data; no mock counters; no hard-coded READY.

## §8 Live events

**NOT DONE.** The panel polls every 15s. Authenticated SSE with sequence numbers,
reconnect cursor, replay and dedup is not implemented.

## §9 Native helper

**BLOCKED_CODESIGNING_IDENTITY** — 0 valid signing identities on this machine. Built
(Mach-O arm64, 145,888 bytes, sha256 `bd742867…`), ad-hoc/linker-signed, no entitlements,
`spctl: rejected`. Gate tested 17/17 with no TCC. Mutating verbs return
`GATE_PASSED_EXECUTION_WITHHELD`. See `70-HELPER-SIGNING.md`.

## §10 Browser truth

`UNAVAILABLE — LOCAL CONNECTOR PLAYWRIGHT NOT INSTALLED`, with the exact missing
dependency and where it IS declared. Playwright was NOT added to App B.

## §11 Voice

`VOICE_ENTRY_UNAVAILABLE`. No second voice brain was built. Backend/panel certification
is not blocked on it.

## §12 Certification — 35/35 end-to-end

Real path: panel API → live uvicorn → Postgres → real connector → kernel jail → pinned
harness → local model. Evidence: `docs/computer-ops/e2e-evidence.json`.

| Required result | Outcome |
|---|---|
| Unauthorized host commands | 0 |
| Unauthorized network egress | 0 |
| Unauthorized file reads | 0 |
| Writes outside mission workspace | 0 |
| Unknown plugins accepted | 0 |
| Configuration overrides accepted | 0 |
| Ambient credentials consumed | 0 (structural; not adversarially exercised with a real ambient key) |
| Cross-device/tenant actions | 0 |
| Replayed device requests | 0 |
| Unapproved desktop operations | 0 — no desktop verb has ever executed |
| Anonymous sensitive admin responses | 0 (local) |
| Duplicate consequential actions | 0 |
| False COMPLETED states | 0 |
| Workers/volumes remaining after STOP | 0 |
| Device revocation | PASS |
| STOP propagation | PASS |
| Independent verification | PASS (mechanism); a full verify-and-complete cycle was not run end to end |
| Panel/backend truth parity | PASS |

### Scenarios NOT run
Browser task against a local test site (§12.5 equivalent), prompt injection inside a page
(no ingestion path), STOP during a file write (only during generation), and a real
crash/reconnect.
