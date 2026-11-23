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
node tests/sol-frontend/account.test.mjs      # member account helpers: email-link token, consent body, guide flag, …

# Browser journeys — needs Playwright (a dev-only tool; the app stays buildless):
npm i -D playwright && npx playwright install chromium
node tests/sol-frontend/journeys.mjs
SOL_JOURNEYS_PORT=8892 node tests/sol-frontend/journeys.mjs   # another port (default 8891), e.g. beside another copy
```

Where Playwright is installed globally instead, link it next to the tests (never commit it):
`mkdir -p node_modules && ln -sfn "$(npm root -g)/playwright" node_modules/playwright`.

## What each covers

| File | Deps | Covers |
|------|------|--------|
| `static-checks.mjs` | none | Reads the module load order from `app.html`; per-file `node --check`; **concatenation parse** (the critical guard for a shared-global-scope split — two files declaring the same top-level `let`/`const`/`class` parse alone but collide at load); duplicate top-level symbol scan; `core/session.js` is loaded first by `app.html` and `index.html`, and stored member tokens are deleted only by `logout()` (and replaced by a sign-in). |
| `guard.test.mjs` | none | Loads the real `core/guard.js` in a `vm` sandbox and asserts every `SolGuard` semantic: synchronous acquire, duplicate-drop, idempotent release, `run()`/`runFor()` release-in-`finally` on success + rejection + sync-throw, and per-record concurrency (record A never blocks record B). |
| `logout.test.mjs` | none | Loads the real `core/router.js` and `core/api.js` in a `vm` sandbox (`API` and `token` injected) with a scripted fetch (synthetic tokens). Sign-out clears both tokens, sends one `POST /auth/logout` with exactly `{refresh_token}` before redirecting, and survives a failing or slow revoke. A refresh in flight (in this tab or another tab sharing `localStorage`) stores nothing afterwards; the session it created is revoked when the refresh answers within the 3 s bound. `init()` keeps the session and tries again after a 5xx, 429, network error or a refresh that could not be done right now; any other failure goes to the sign-in page without deleting anything. Does not prove server-side revocation. |
| `admin-logout.test.mjs` | none | Loads the inline script of `admin.html` in a `vm` sandbox (`sessionStorage`, stub DOM). Admin sign-out clears the access and refresh tokens at once and revokes the refresh session (keepalive); no later 401 or in-flight refresh signs the admin back in, and a request from an earlier session (ended by sign-out, expiry or a new sign-in) is never refreshed or re-sent under the next one. A refresh that fails with 429, 5xx or a network error keeps the session; a sign-out also ends a duplicated tab's copy of the session (`BroadcastChannel` stub). Does not prove server-side revocation. |
| `session-tabs.test.mjs` | none | Loads the real `core/session.js` (when present), `core/state.js`, `core/router.js` and `core/api.js` once per tab in `vm` sandboxes sharing one mock browser and a mock backend that rotates refresh tokens on receipt. By default every tab sees every write at once (one synchronous Map); `lag: true` models Chromium's per-renderer copies, where another tab's writes arrive later and a tab's own write can land last. Sign-ins run the real `finishAuth()` of `index.html` on a newly loaded landing page (`rawSignIn` writes the two tokens only, like the landing page before this branch); pages share a `BroadcastChannel` stub; fetch honours `AbortSignal`. `deliverFirst(n)` delivers part of a held write (a torn read); `holdTab(t)`/`releaseTab(t)` keep one busy tab behind while the others catch up; a tab that navigates (href, reload) loses its pending non-keepalive fetches and sends nothing more, as a page that has gone (a back/forward-cache `pageshow` brings it back); `noSessionJs` loads a tab without `core/session.js` (an older `app.html`). Covers what a newly opened tab accepts after these races, pairs written by a tab still on an earlier version, a refresh answered after the 20 s bound, re-sends under another user's session or after a sign-out, two tabs refreshing at once (with the Web Locks stub, and without it), transient refresh failures, sign-out propagation, the back/forward cache and loading-time races. A model only: it does not prove server-side revocation or Firefox/Safari behaviour. Real cross-process timing is not covered here: the real-Chromium checks used for this work are in the review packets, not in this folder. |
| `login.test.mjs` | none | Loads the real `finishAuth()` of `index.html` (and `core/session.js`) in a `vm` sandbox. A sign-in that replaces a stored session records a sign-out for open app tabs, announces it on the `sol-auth` channel and revokes the replaced session (keepalive); every sign-in ends with the commit tag the app checks. |
| `account.test.mjs` | none | Loads the real `core/account.js` (`window.SolAccount`) in a `vm` sandbox. An email link's `?token=` is read once and removed from the address bar with `history.replaceState` (other parameters and the hash kept), never stored or logged; 404 and 405 read as "not available yet" and 429 as a rate limit; the backend's password rule (8 to 128 characters, counted as code points); the outcome of the forgot, reset and verify calls by status (the forgot form shows one neutral message whatever the answer, except a 429); the sign-up body is exactly the deployed shape with consent off and exactly the PR #34 shape with it on; the three documents sign-up agrees to (terms, privacy, e-sign disclosure) and whether one changed; the first-run guide's "seen" mark is per member and never throws when storage is blocked; the notification, account-close, refusal and close-summary helpers of the Settings page. |
| `journeys.mjs` | Playwright | Starts a static server (port 8891, or `SOL_JOURNEYS_PORT`) that serves clean URLs the way Cloudflare Pages does (`/sol/verify` serves `verify.html`; the `.html` paths still work), generates the mock harness, drives real Chromium through primary member journeys A–J (dashboard, KYC, bank, discover, timeline, premium, goals, notifications, community, trust) plus dialogs (`SolDialog`), guards (`SolGuard`), **P3 request cancellation** (GETs carry the route abort signal, mutations do not, in-flight GETs abort on nav), and **P4 circle-detail** (money math, no legacy badge, design-system classes, no PII). Then the member account pages: the verify-email banner and its resend, the Settings page (profile, password reset link, two-factor enrolment and turning off, notifications, the AI assistant opt-in, data export, account closing and the sign-out after it), payout history, the first-run guide, and on the pages without a session (sign-in modal, `reset-password.html`, `verify.html`) forgot and reset password, email verification, the two-factor sign-in step and consent at sign-up (the switch is turned on by rewriting the served `index.html`; the documents shown are the ones `GET /legal/documents` returns). A wrong code or password in Settings is one request and never a `POST /auth/refresh` (the harness's refresh answers 401 after a two-factor disable); the close-account summary comes from the response; keyboard focus stays on the page after each Settings action (answers delayed 150 ms); empty status regions stay in the accessibility tree (read over CDP); the focus ring reaches 3:1 on the dark dashboard hero and Premium card. Each feature runs against the deployed base (routes of the draft PRs answer 404, so the "not available yet" paths run) and, where it differs, the draft PR shape. Request bodies are compared key for key. Accessibility checks run on every page visited: form fields have labels, buttons and links have names, exactly one `h1`, header, labelled nav and main landmarks, no positive `tabindex`, images have `alt`, the active nav item has `aria-current`, focus moves to the `h1` and the title names the page after navigation, Tab from the top reaches the skip link, then the nav, and the skip link leads into main, the focus ring is visible (3:1), reduced motion turns transitions off. Requests to deployed hosts are aborted and counted; Google Fonts get an empty stylesheet. |
| `harness.mjs` | none | Generates `frontend/sol/boot-test.html` = the current `app.html` + a query- and `AbortSignal`-aware **mock backend** injected into `<head>` (so it runs before every script and its seed data is never part of `document.body`) with realistic response shapes. Imported by `journeys.mjs`; also runnable directly. The shapes and error codes of the account routes are copied from the backend (each route cites its file and lines). Defaults are the deployed base (a draft-PR route answers 404 `{"detail":"Not Found"}`); a journey opts in with `__mock.a33 / c34 / s35` or overrides one route with `__mockSet('METHOD /path', status, body)`. `publicMockScript()` is the same mock for the pages without a session, passed to `page.addInitScript`. Every request is logged with its parsed body (`__reqLog`, and `__recordReq` where a page navigates away). |

## Known failing check: `journey C_bank_noRawId`

`journeys.mjs` checks that no raw id reaches the member markup by scanning
`document.body.innerHTML` (`journey C_bank_noRawId`, journeys.mjs:77, and
`journey I_noRawUser`, journeys.mjs:83). Both failed from 38461cf on, for two causes:

- **The harness (fixed).** `generateHarness()` put the mock `<script>` just before the
  `core/session.js` tag (harness.mjs:176-179 at bdec836; at 38461cf the `core/state.js`
  tag), and that tag is inside `<body>` (app.html:663 at e6dccc6), although the harness
  comment (harness.mjs:104 at bdec836) said the mock goes into `<head>`. The mock's `SEED` JSON holds the raw
  ids (`"u2"`, the bank id), so the scan matched the mock itself, not the member markup.
  `I_noRawUser` failed only for this reason. The mock now goes into `<head>`; a scratch
  mutation that renders `"u2"` into a community post makes `I_noRawUser` fail again, so the
  check still bites.
- **bank.js (still open).** `frontend/sol/app/pages/bank.js:82` renders the raw bank id in
  `onclick="openRemoveDialog('${id}')"` (also :81, `setPrimary`, and :92-98, the
  micro-deposit form shown for other account states). Bank linking is frozen on this
  branch, so `C_bank_noRawId` stays red until bank.js stops putting the id in the markup.

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
