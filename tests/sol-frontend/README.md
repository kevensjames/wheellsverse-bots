# SOL member-app tests

Regression tests for the buildless, multi-file SOL member app (`frontend/sol/app/`).
Two run with **zero dependencies**; the browser journeys need Playwright.

## Run

```bash
# Pure Node — no install, run these on every change:
node tests/sol-frontend/static-checks.mjs   # syntax + global-scope collisions
node tests/sol-frontend/guard.test.mjs       # SolGuard unit + concurrency
node tests/sol-frontend/route-abort.test.mjs # P3 money-safety: mutations never cancelled
node tests/sol-frontend/logout.test.mjs      # member sign-out: refresh revoked, no late token kept
node tests/sol-frontend/admin-logout.test.mjs # admin sign-out: refresh revoked, no silent refresh after

# Browser journeys — needs Playwright (a dev-only tool; the app stays buildless):
npm i -D playwright && npx playwright install chromium
node tests/sol-frontend/journeys.mjs
```

## What each covers

| File | Deps | Covers |
|------|------|--------|
| `static-checks.mjs` | none | Reads the module load order from `app.html`; per-file `node --check`; **concatenation parse** (the critical guard for a shared-global-scope split — two files declaring the same top-level `let`/`const`/`class` parse alone but collide at load); duplicate top-level symbol scan. |
| `guard.test.mjs` | none | Loads the real `core/guard.js` in a `vm` sandbox and asserts every `SolGuard` semantic: synchronous acquire, duplicate-drop, idempotent release, `run()`/`runFor()` release-in-`finally` on success + rejection + sync-throw, and per-record concurrency (record A never blocks record B). |
| `logout.test.mjs` | none | Loads the real `core/state.js`, `core/router.js` and `core/api.js` in a `vm` sandbox with a scripted fetch (synthetic tokens). Sign-out clears both tokens, sends one `POST /auth/logout` with exactly `{refresh_token}` before redirecting, survives a failing or slow revoke, and a refresh in flight (in this tab or another tab sharing `localStorage`) never leaves a live session behind. Does not prove server-side revocation. |
| `admin-logout.test.mjs` | none | Loads the inline script of `admin.html` in a `vm` sandbox (`sessionStorage`, stub DOM). Admin sign-out clears the access and refresh tokens, revokes the refresh session, and no later 401 or in-flight refresh signs the admin back in. Does not prove server-side revocation. |
| `journeys.mjs` | Playwright | Starts a static server, generates the mock harness, drives real Chromium through primary member journeys A–J (dashboard, KYC, bank, discover, timeline, premium, goals, notifications, community, trust) plus dialogs (`SolDialog`), guards (`SolGuard`), **P3 request cancellation** (GETs carry the route abort signal, mutations do not, in-flight GETs abort on nav), and **P4 circle-detail** (money math, no legacy badge, design-system classes, no PII). |
| `harness.mjs` | none | Generates `frontend/sol/boot-test.html` = the current `app.html` + an injected query- and `AbortSignal`-aware **mock backend** with realistic response shapes. Imported by `journeys.mjs`; also runnable directly. |

## Why a mock, not the real backend

The real Sol API is a **separate repo** (deployed at `sol-api-production.up.railway.app`),
not part of this monorepo, so these journeys run against the enriched mock — which
matches the risk of a pure frontend change (the app's API calls are unchanged).
A real-backend authenticated E2E (real login, real API contract) is a valuable
future addition when that repo is available locally.

## The generated harness is not committed

`boot-test.html` is git-ignored: it embeds the internal API route map, which is
harmless locally but would be recon material if served in production. Only the
generator (`harness.mjs`) is committed. Never serve `boot-test.html` from prod.
