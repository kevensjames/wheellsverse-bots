# KAI Angular pilot — DARK

A scoped, hand-authored Angular 17 (standalone) workspace skeleton. It realizes
the governed-frontend capability family from
[`docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md`](../../docs/kai-frontend/ANGULAR_CAPABILITY_SPEC.md)
as a concrete pilot app — **dark, uninstalled, unbuilt, undeployed.**

## What "dark" means here (read before running anything)

- **Nothing is installed.** There is no `node_modules/`, no `package-lock.json`.
  The `package.json` *declares* pinned, exact dependency versions — it does not
  fetch them. Installing pulls a large third-party dependency tree, which the
  spec treats as a **supply-chain admission event** that must run **inside the
  governed sandbox with deny-by-default egress + SBOM + secret/malware/license
  scan** — machinery that is not wired on a developer host. So `npm ci` / `ng
  build` are **deferred to the governed mission**, not run here.
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
- Standard Angular workspace config (`angular.json`, `tsconfig*.json`,
  `karma.conf.js`) with a **bundle-size budget** — the spec names the bundle
  budget as build evidence.

## When it is authorized to run (a later, separately-approved mission)

Inside the sandbox: `ng new`-equivalent install (pinned, locked, allowlisted
registry, SBOM + scan) → `ng build` (bundle budget = evidence) → unit + e2e
(e2e driven by the governed browser runtime) → preview (browser-runtime
screenshot + route map) → **publish only behind a named + fresh bound
single-use approval + evidence + rollback**. Until then the capabilities stay
inert and this stays uninstalled.
