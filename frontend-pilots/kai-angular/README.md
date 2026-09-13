# KAI Angular pilot — DARK

A scoped, hand-authored Angular 22 (standalone) workspace skeleton. It realizes
the governed-frontend capability family from
[`docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md`](../../docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md)
as a concrete pilot app — **dark and undeployed.** Its pinned dependency tree
has since been admitted and the app built + unit-tested **inside the governed
sandbox** (Step 2); a locked `package-lock.json` is committed and the SBOM /
audit / build / test evidence lives under
[`docs/workforce/step2-evidence/`](../../docs/workforce/step2-evidence/). Even so,
nothing is deployed or enabled, the capabilities stay **INERT**, and
`node_modules/` and `dist/` are deliberately **not** committed.

## Supported-version baseline

Pinned to **Angular 22.1.x** (the active supported release as of 2026-09; v20–21
are LTS, ≤19 are unsupported), which requires **TypeScript 6.0.x**, rxjs 7.8.x,
zone.js 0.16.x, and **Node `^22.22.3 || ^24.15.0 || >=26`**. Versions were taken
from the npm registry + the v22 workspace schematic, not guessed. The current dev
host runs node 22.22.2 — one patch **below** Angular 22's floor — which is another
reason the build must run in the governed sandbox on a conformant Node, not here.
The build/serve/test targets use the modern `@angular/build` builder.

## What "dark" means here (read before running anything)

- **The dependency tree is admitted but not vendored here.** A locked
  `package-lock.json` pins the full, exact tree; `node_modules/` and `dist/` are
  **not** committed (repository hygiene). The install pulls a large third-party
  tree, which the spec treats as a **supply-chain admission event** that must run
  **inside the governed sandbox with deny-by-default egress + SBOM +
  secret/malware/license scan** — machinery that is not wired on a developer
  host. That admission was performed in Step 2: `npm ci` + `ng build` + `ng test`
  ran inside the governed sandbox on the pinned Node, and the SBOM / audit /
  build / test evidence is committed under `docs/workforce/step2-evidence/`. Do
  not re-run `npm ci` / `ng build` on a developer host — re-admission belongs in
  the sandbox.
- The scaffold/build/test/preview/publish steps map to the capabilities
  `kai.frontend.scaffold/build/test/preview/publish.v1`, which live in the
  backend **Capability Exchange registry as INERT** (declared, no adapter
  bound, cannot execute). See `backend/app/services/capability_exchange.py`.
- Nothing here deploys, and nothing here touches the browser-ops soak. This is
  local dev source only.

## What it is

- `src/app/app.component.ts` — a single standalone root component: a dark shell
  that renders the frontend capability manifest and each capability's lifecycle
  (all `INERT` in Stage 1) — an honest UI that shows *declared, not executable*.
- `src/app/capability-manifest.ts` — a typed mirror of the five
  `kai.frontend.*` capabilities, so the pilot's own UI cannot claim a capability
  is runnable when the backend registry says it is inert.
- Standard Angular workspace config (`angular.json`, `tsconfig*.json`) with a
  **bundle-size budget** — the spec names the bundle budget as build evidence.
  (No `karma.conf.js`: the v22 `@angular/build:karma` builder is config-less.)

## When it is authorized to run (a later, separately-approved mission)

Inside the sandbox: `ng new`-equivalent install (pinned, locked, allowlisted
registry, SBOM + scan) → `ng build` (bundle budget = evidence) → unit + e2e
(e2e driven by the governed browser runtime) → preview (browser-runtime
screenshot + route map) → **publish only behind a named + fresh bound
single-use approval + evidence + rollback**. Until then the capabilities stay
inert and this stays uninstalled.
