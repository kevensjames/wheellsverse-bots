# SOL member-app tests

Regression tests for the buildless, multi-file SOL member app (`frontend/sol/app/`).
The `.test.mjs` files and `static-checks.mjs` run with **zero dependencies**; the browser journeys need Playwright.

## Run

```bash
# Pure Node — no install, run these on every change:
node tests/sol-frontend/static-checks.mjs   # syntax + global-scope collisions
node tests/sol-frontend/guard.test.mjs       # SolGuard unit + concurrency
node tests/sol-frontend/route-abort.test.mjs # P3 money-safety: mutations never cancelled
node tests/sol-frontend/logout.test.mjs      # member sign-out: refresh revoked, no late token kept
node tests/sol-frontend/admin-logout.test.mjs # admin sign-out: refresh revoked, no silent refresh after
node tests/sol-frontend/session-tabs.test.mjs # several tabs: sign-out, refresh races, other users, back/forward cache
node tests/sol-frontend/login.test.mjs        # landing sign-in: a replaced session is recorded and revoked

# Browser journeys — needs Playwright (a dev-only tool; the app stays buildless):
npm i -D playwright && npx playwright install chromium
node tests/sol-frontend/journeys.mjs
```

## What each covers

| File | Deps | Covers |
|------|------|--------|
| `static-checks.mjs` | none | Reads the module load order from `app.html`; per-file `node --check`; **concatenation parse** (the critical guard for a shared-global-scope split — two files declaring the same top-level `let`/`const`/`class` parse alone but collide at load); duplicate top-level symbol scan; `core/session.js` is loaded first by `app.html` and `index.html`, and stored member tokens are deleted only by `logout()` (and replaced by a sign-in). |
| `guard.test.mjs` | none | Loads the real `core/guard.js` in a `vm` sandbox and asserts every `SolGuard` semantic: synchronous acquire, duplicate-drop, idempotent release, `run()`/`runFor()` release-in-`finally` on success + rejection + sync-throw, and per-record concurrency (record A never blocks record B). |
| `logout.test.mjs` | none | Loads the real `core/router.js` and `core/api.js` in a `vm` sandbox (`API` and `token` injected) with a scripted fetch (synthetic tokens). Sign-out clears both tokens, sends one `POST /auth/logout` with exactly `{refresh_token}` before redirecting, and survives a failing or slow revoke. A refresh in flight (in this tab or another tab sharing `localStorage`) stores nothing afterwards; the session it created is revoked when the refresh answers within the 3 s bound. `init()` keeps the session and tries again after a 5xx, 429, network error or a refresh that could not be done right now; any other failure goes to the sign-in page without deleting anything. Does not prove server-side revocation. |
| `admin-logout.test.mjs` | none | Loads the inline script of `admin.html` in a `vm` sandbox (`sessionStorage`, stub DOM). Admin sign-out clears the access and refresh tokens at once and revokes the refresh session (keepalive); no later 401 or in-flight refresh signs the admin back in, and a request from an earlier session (ended by sign-out, expiry or a new sign-in) is never refreshed or re-sent under the next one. A refresh that fails with 429, 5xx or a network error keeps the session; a sign-out also ends a duplicated tab's copy of the session (`BroadcastChannel` stub). Does not prove server-side revocation. |
| `session-tabs.test.mjs` | none | Loads the real `core/session.js` (when present), `core/state.js`, `core/router.js` and `core/api.js` once per tab in `vm` sandboxes sharing one mock browser and a mock backend that rotates refresh tokens on receipt. By default every tab sees every write at once (one synchronous Map); `lag: true` models Chromium's per-renderer copies, where another tab's writes arrive later and a tab's own write can land last. Sign-ins run the real `finishAuth()` of `index.html` on a newly loaded landing page (`rawSignIn` writes the two tokens only, like the landing page before this branch); pages share a `BroadcastChannel` stub; fetch honours `AbortSignal`. Covers what a newly opened tab accepts after these races, re-sends under another user's session or after a sign-out, two tabs refreshing at once (with the Web Locks stub, and without it), transient refresh failures, sign-out propagation, the back/forward cache and loading-time races. A model only: it does not prove server-side revocation or Firefox/Safari behaviour, and real cross-process timing is covered by the separate Chromium checks. |
| `login.test.mjs` | none | Loads the real `finishAuth()` of `index.html` (and `core/session.js`) in a `vm` sandbox. A sign-in that replaces a stored session records a sign-out for open app tabs, announces it on the `sol-auth` channel and revokes the replaced session (keepalive); every sign-in ends with the commit tag the app checks. |
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
