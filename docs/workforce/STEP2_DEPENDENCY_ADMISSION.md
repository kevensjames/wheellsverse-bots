# Phase-5A Step 2 — Governed Angular Dependency Admission, Build & Test

**Status:** `WORKFORCE_UI_DARK_BUILT_AND_TESTED_LOCALLY` (dependency-admitted, built,
tested in a disposable governed sandbox). Nothing merged, pushed, deployed, or
activated. All 319 characters remain `INERT`.

## Toolchain (provisioned sandbox-only; pinned compatibility honored)

The only host Node was **v22.22.2**, one patch below the pinned floor
(`engines.node = ^22.22.3 || ^24.15.0 || >=26.0.0`, whose comment forbids building
on 22.22.2). Per owner decision, **Node 22.22.3** (pin option 1, minimal) was
provisioned **sandbox-only** from the official distribution and verified:

| Field | Value |
|---|---|
| source_url | `https://nodejs.org/dist/v22.22.3/node-v22.22.3-darwin-arm64.tar.gz` |
| sha256 (official == local) | `0da7ff74ef8611328c8212f17943368713a2ad953fb7d89a8c8a0eae87c23207` (verified + `shasum -c` OK) |
| node / npm | **v22.22.3** / **10.9.8** |
| install path | disposable sandbox only — NOT `~/.local/share/mise`, NOT global, no sudo (real mise unchanged) |

`package.json` `engines` was **not** relaxed. mise's own installer was not used (its
GPG step failed on the long sandbox path); the archive was downloaded + SHASUMS256-
verified manually — more auditable and fully sandbox-isolated.

## Isolation

Disposable sandbox outside the repo/Istanbul/soak/prod; all commands ran under a
**scrubbed empty env** (`env -i` + minimal PATH + sandbox-local `HOME`/`TMPDIR`/npm
cache/userconfig). No production/Railway/Stripe/Supabase/Cloudflare/GitHub/model/
browser/device creds; no inherited app `.env`; no global npm; no sudo; registry
access limited to `registry.npmjs.org`; karma test server bound to `localhost` only.

## Dependency admission

- **package.json**: 21 direct deps, **all exact** (no wildcard/range/`latest`/git/
  local/tarball). Every direct dep resolved **exactly** to its pin (zero drift).
  **package.json is byte-identical to committed `ea1c2293`** (net-zero change).
- **Lockfile**: generated deterministically; **`npm ci --ignore-scripts` reproduces**
  it cleanly. `package-lock.json` sha256 **`c644da596de1c00ae7781aa3d3191efec402958f65357a2812d75e28b72cecf4`**, 613 package nodes.
- **Sources**: 100% `registry.npmjs.org`; **0 git/local/non-registry**; **100% carry
  integrity hashes**.
- **Transitive**: ~490 installed packages (613 lockfile nodes incl. nested peers).
- **Lifecycle scripts**: installed with `--ignore-scripts`. 38 packages declare
  install/postinstall/prepare; the native ones (`esbuild` postinstall, `@parcel/watcher`,
  `lmdb`, `msgpackr-extract` install) did NOT run — and the build did **not** require
  them: esbuild ships its prebuilt `@esbuild/darwin-arm64` binary as an optional dep
  (no script needed), and `@parcel/watcher`/`lmdb` are dev-server/disk-cache optionals.
  **No STOP was needed for a lifecycle script.**
- **Licenses** (per the lockfile, all 612 components): MIT ×525, ISC ×39, BSD-3 ×13,
  MPL-2.0 ×12, BSD-2 ×11, Apache-2.0 ×9, CC-BY-4.0 ×1, BlueOak-1.0.0 ×1, 0BSD ×1.
  **No GPL/AGPL/unknown/proprietary.** Mostly permissive; the **12 MPL-2.0**
  (weak file-level copyleft — lightningcss + its platform binaries), the **1
  CC-BY-4.0** (attribution — caniuse-lite), and the **1 BlueOak-1.0.0** are all
  **dev/build tooling and NOT in the shipped browser bundle** (whose prod deps are
  MIT/Apache-2.0/0BSD only), so no copyleft/attribution obligation reaches the
  shipped artifact.
- **Deprecated (informational)**: `inflight@1.0.6`, `rimraf@3.0.2`, `glob@7.2.3`
  (transitive build-tool deps), `@angular/animations@22.1.6` (Angular recommends
  `animate.enter/leave`; the console imports no animations).
- **SBOM**: CycloneDX 1.5, 612 components, **license fields populated for all 612**
  (from the lockfile; distribution matches the Licenses line above),
  `docs/workforce/step2-evidence/sbom.cyclonedx.json`
  (sha256 `c182ddf8530ff918ea5f0f6f951d2b73863a3b94dcaef46dfc233eb7bee401bc`). Lockfile-
  derived because `npm sbom` refuses the **legitimate** dual-istanbul nesting (below).
  Honesty caveat (recorded in the SBOM's `metadata.properties.hashContentFormat`):
  each component `hash.content` mirrors the lockfile integrity string verbatim
  (`sha512-`+base64), **not** the hex digest CycloneDX 1.5 specifies — so this is a
  faithful lockfile-integrity mirror, not a `cyclonedx validate`-conformant document.
- **Audit**: `npm audit` = **0 vulnerabilities** (info/low/moderate/high/critical all 0).
  `docs/workforce/step2-evidence/audit-report.json`. No `npm audit fix`, no `--force`,
  no `--legacy-peer-deps` used.

### Finding (classified, not a STOP): istanbul-lib-instrument dual version

`@angular/build@22.1.8` declares `istanbul-lib-instrument@^6` as an **optional peer**
(used only under `--code-coverage`); `karma-coverage@2.2.1` (required by the
`@angular/build:karma` test builder) brings `istanbul-lib-instrument@5.2.1`. The first
`npm install` hoisted 5.2.1 and wrote a lockfile whose tree-shape `npm ci` rejected.
**Reachability:** coverage-instrumentation tooling — **dev/test only, never in the
shipped browser bundle, audit-clean.** **Resolution (no dependency change):**
`npm install --package-lock-only` normalized the lockfile to npm's ideal nested tree
(`@angular/build → 6.0.3`, `karma-coverage → 5.2.1`), after which `npm ci` reproduces
cleanly. A brief mistaken removal of `karma-coverage` was reverted — `ng test` requires
it (`@angular/build:karma` loads it at config time), so **package.json is unchanged**
and the only committed build artifact is the normalized lockfile. `npm sbom` still
refuses the dual-version nesting, so the SBOM is lockfile-derived.

## Build & test (admitted locked tree only)

- **Reproducible clean install**: `npm ci --ignore-scripts` ✓ (0 vulnerabilities).
- **Strict TypeScript** (`tsc -p tsconfig.app.json --noEmit`): exit 0 ✓.
- **Production build** (`ng build --configuration=production`): ✓ — **initial bundle
  292.19 kB raw / 81.26 kB transfer** (main 255.72 kB + polyfills 35.88 kB + styles
  595 B). The 319-character dataset is in a **lazy** chunk (383.69 kB), not the initial
  bundle (the `workforce-meta.ts` shell split works). All 5 views code-split.
- **Angular unit/honesty tests** (`ng test`, ChromeHeadless, loopback): **11/11 SUCCESS**
  (shell DARK/INERT + label; capability-pilot INERT; WorkforceService 319/INERT/
  actionsAdmitted-false/proposals-inert/provenance-honest; governed-action disabled +
  no emitter).
- **Backend + static-honesty regression**: **179 passed**.

## Compiled-bundle inspection (inertness)

- **No Angular HTTP client**: `@angular/common/http`/`HttpClient` **absent** from the bundle.
- `XMLHttpRequest`/`WebSocket` appear **only in the zone.js polyfills** (framework
  patching, not app calls); no `fetch`/`EventSource`/`sendBeacon` anywhere.
- `document.cookie` appears once — Angular's framework `DomAdapter.getCookie` method
  definition, never invoked by app code (no HttpClient/XSRF in the bundle).
- External URLs: only W3C XML namespaces (SVG/MathML/xhtml/xlink) + one `angular.dev`
  security-doc link. **No external data/API endpoints, no tracking.**
- **No secrets/env**: no `process.env`, Railway/Stripe/Supabase/key patterns.
- **Catalog fidelity (re-derived)**: the bundle's character id set is **identical to the
  catalog's 319** (0 missing, 0 extra); names present verbatim; **every status `INERT`**
  (the only "AVAILABLE" strings are the "NOT AVAILABLE" governed label); no fabricated
  records.
- **Team proposals**: present as static backend-exported data; no planning logic
  (`propose_team`/set-cover) in the bundle — the UI re-computes nothing.
- **Governed action**: compiled `disabled` property present; `ng test` confirms the
  rendered button is disabled with no event emitter.

## STOP conditions — none triggered

No lockfile-integrity failure; no unexpected registry/git/local dep; no name confusion;
no install-time credential request; no script unrelated activity (scripts disabled); no
unresolved critical vuln in the shipped bundle (0 vulns); no unexplained matrix drift
(direct deps exact; the istanbul dual-version is explained + dev/test-only); no required
lifecycle script for the build.

## Repository hygiene

Committed (one coherent Step-2 unit): the reviewed `package-lock.json`, this report,
the SBOM, `audit-report.json`, `node-provenance.txt` (sandbox path redacted),
build/test summaries, and the `.gitignore` exception admitting the lockfile.
**Never committed:** `node_modules`, `dist`, `.angular`, caches, logs, browser
profiles (all still gitignored). Sandbox (Node runtime + node_modules + dist)
deleted after the review + evidence capture.

## Independent 6-lens review (wf_be8fb90f-1bb) → findings fixed

Lenses 1 (supply-chain/lockfile reproducibility), 2 (vuln/license), 3 (compiled-bundle
inertness), 4 (build/test correctness) = **CLEAN** (independently reproduced: `npm ci`
0-vuln, deterministic lockfile, bundle has no HttpClient/network/secrets, id set ==
catalog 319 all INERT). Mutation tests: 8/9 guard mutations **CAUGHT** (missing
`disabled`, action-verb `(click)`, `@Output`, `fetch(`, `HttpClient` import, external
URL in `.scss` and in inline component CSS, any `workforce-data.ts` byte change incl.
`INERT→RUNNING`). Findings, all fixed:
- **MEDIUM (lens 5, teeth gap):** no guard enforced "the console carries no planning
  logic." Hardened over three adversarial rounds into `test_console_carries_no_team_
  planning_logic`, now a STRUCTURAL regression net: a COMPLETE per-file public-member
  allowlist over every workforce class (modifier/decorator/arrow-property-aware) + a
  fixed class-file set + bans on `.sort(`/`.slice(` (ranking/top-N) and the
  accumulation primitives `.push(`/`.reduce(`/`.splice(`/`.concat(`/`new Set|Map|Array`
  (a render console accumulates no state) + a team-construction identifier scan.
  Mutation-verified to catch every planner form surfaced across all rounds: named,
  renamed, arrow-property, `public`-modifier, new-component-method, interactive
  push/splice select, new free-function file, and planner logic hidden inside an
  allowlisted method body. **Scope (honest):** this is a regression net, not a formal
  proof — "no client-side planning" is a behavioral property a Turing-complete language
  can always re-express; the DEFINITIVE inertness assurance is the runtime `ng test`
  specs + the compiled-bundle inspection (the shipped `proposals()` returns static
  backend data; no planning algorithm is compiled into the bundle), plus code review on
  any future change. One legit `.slice` (roster `shortHash` string-truncation) was
  refactored to `.substring` so the `.slice(` ban is false-positive-free.
- **LOW (lens 6):** `node-provenance.txt` baked the absolute disposable-sandbox path →
  redacted to `<disposable-sandbox>`.
- **LOW (lens 4):** `ng-build.summary.txt` was truncated → regenerated with the full
  chunk table (shows the 319-char data in a lazy chunk, not the initial bundle).
- **LOW (lens 2):** the SBOM had no license fields → populated for all 612 from the
  lockfile (final-review follow-up corrected an earlier partial 490/612).
- **NIT (lens 6):** dangling `npm-audit.json` reference → corrected to `audit-report.json`.

## Ceiling

Nothing merged/pushed/deployed/migrated/activated; no router/worker/adapter/handler/
dispatcher/model call/tool call/external action; no Alembic revision; L3 blocking;
`KAI_BROWSER_OPS_ENABLED=false`; browser soak + Istanbul untouched; all 319 `INERT`.
