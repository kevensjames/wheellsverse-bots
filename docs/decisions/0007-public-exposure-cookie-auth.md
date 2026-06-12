# 0007 — Public exposure (cookie auth + signup/login/pricing UI)

Date: 2026-05-26
Stage: 6
Status: code-complete; deployment + Stripe LIVE keys + Cloudflare Tunnel are operator-side
Phase: B precursor — NAI is now packaged as a paid product. Deploy decision is the operator's.

## What Stage 6 is

The first five stages built the engine (memory, router, tools, API+UI, daemonization). Stage 6 turns it into a **product** — somebody who isn't the operator can land on a page, sign up, pay, and chat. No agent-architecture lift. No new LLM features. Just the wrapping that lets external users in safely.

Two surfaces:
1. **Cookie auth** — replaces the Stage 4 query-param JWT (`?token=`) on the SSE endpoint with HttpOnly cookies. JWTs no longer travel through the URL bar, browser history, or referer headers.
2. **Marketing pages** — `signup.html`, `login.html`, `pricing.html` under `/nai-ui/`. The existing `/nai-ui/` chat page is the destination after signup/login.

## Decisions

1. **HttpOnly cookies, not localStorage.** Storing a JWT in `localStorage` (as Stage 4 did) means any XSS on `/nai-ui/*` exfils the token. HttpOnly cookies are unreadable from JavaScript — XSS still hurts, but it can't steal long-lived auth.
2. **`SameSite=Lax`, not `Strict`.** Lax lets SSE on the same origin work without ceremony and lets users follow a `/nai-ui/signup.html` link from email/Twitter without the cookie being stripped. Strict would break those flows. CSRF is still blocked for cross-origin POSTs because Lax doesn't send cookies on cross-origin form submissions.
3. **`Secure` flag gated on `APP_ENV`.** In production cookies are HTTPS-only; in `development`/`local`/`test` we drop `Secure` so localhost flows work without TLS. Hardcoding `Secure=True` would silently break local dev.
4. **Two cookies, different paths.** `nai_access` is `path=/` (every endpoint sees it). `nai_refresh` is `path=/auth` (only the auth router sees it). If the access cookie leaks via, say, an XSS in a third-party widget on the chat page, the refresh cookie isn't in the same blast radius.
5. **Cookie body is the existing JWT.** No new auth primitive — the cookie just transports the same access/refresh JWTs that the bearer flow already issues. `decode_token()` doesn't care whether the token arrived in a header or a cookie. Smaller change surface, fewer ways to subtly break it.
6. **`/auth/signup` and `/auth/login` still return the JSON `TokenResponse`** with both tokens in the body, **and** set cookies. API clients (Stage 4 contract) keep working; browser UIs now have a cookie option. Same response, two delivery channels.
7. **`get_current_user` accepts either cookie or Bearer header.** Bearer is preferred (machine-deterministic when both are present). The cookie path covers browser-driven calls to `/auth/me`, `/billing/*`, `/nai/chat`, etc. Migrating one dependency means every protected endpoint becomes cookie-aware automatically.
8. **`OAuth2PasswordBearer(auto_error=False)`** so the absence of an Authorization header isn't an instant 401 — the cookie path is allowed to satisfy the request. Swagger UI's "Authorize" button still works because the scheme stays registered.
9. **SSE keeps a `?token=` fallback (deprecated, with logging).** Cutting the legacy path on the same release as adding the cookie path risks breaking any open browser session that still has localStorage-JWT-using `chat.js`. Logger emits `WARNING SSE auth used deprecated ?token= query param` on every fallback. When `grep WARNING …deprecated ?token=` returns zero hits across a few days of logs, the fallback gets deleted.
10. **`/auth/logout` issues `Set-Cookie` with `Max-Age=0`** (via `response.delete_cookie`) for both cookies. Server-side token revocation is *not* added in this stage — JWTs remain stateless. If/when revocation becomes important, a `token_revocations` table keyed by `jti` is the smallest viable design. Out of scope here.
11. **`/auth/refresh` accepts either cookie OR JSON body.** The cookie path is the browser flow (zero JS needed — the cookie auto-arrives because the request hits `/auth/refresh`). The body path keeps API-client refresh working unchanged.
12. **Marketing pages are vanilla HTML/CSS/JS, not a SPA.** Three pages with two shared scripts (`auth.js`, `pricing.js`) costs nothing to host, has no build step, doesn't add a dependency that needs CVE-tracking, and matches the existing single-file `chat.js` style.
13. **Pricing → Stripe is "POST then redirect".** Subscribe button → `POST /billing/checkout {plan_code}` → backend returns `{checkout_url}` from `stripe_service.create_checkout_session` → `window.location = checkout_url`. The frontend never touches a Stripe SDK or publishable key. All Stripe SDK calls stay on the backend (Stage 5 contract preserved).
14. **"Resume after signup" via `localStorage`.** If an unauthenticated user clicks Subscribe, we set `localStorage.nai_pending_plan = "pro"`, redirect to `/signup.html?next=/nai-ui/pricing.html`, and when the pricing page loads again with auth in place, `pricing.js` auto-fires checkout for the remembered plan. No server state needed for the handoff.
15. **`/nai/chat/stream` accepts cookies AND falls back to `?token=`.** The cookie path is the canonical Stage 6 flow; the query-param path is what (12) describes as the deprecated bridge.
16. **`chat.js` calls `requireAuthOrRedirect("/nai-ui/login.html")` on load.** If the cookie is missing/expired, the user lands on login instead of seeing the chat UI with an instantly-failing SSE.

## What did NOT change

- `app/services/billing/stripe_service.py` — Stage 5's Stripe Checkout integration was already complete.
- The auth router's signup/login/refresh response shape — `TokenResponse` is unchanged so existing API clients keep working.
- The Brain, router, tools, memory layer — Stage 6 is a deployment/auth-shape stage, not an LLM feature stage.
- The launchd plist or any daemon wiring — Stage 5's runtime contract is preserved.

## Reversible?

- Drop the cookie path: yes — revert `cookie_auth.py`, the two import changes in `auth.py` (router + dependency), the SSE dependency rename. The UI HTML/JS files become dead code but don't break the API.
- Drop the legacy `?token=` path: yes, once log telemetry confirms no callers — single delete in `stream_auth.py`.
- Replace vanilla pages with a SPA: yes — the API contract stays the same, only the static files change.
- Tighten `SameSite` to `Strict` for testing: yes — but expect emailed signup links to silently fail on first click. Have a recovery flow in mind.

## Artifacts shipped (Stage 6)

- `backend/app/dependencies/cookie_auth.py` — set/clear helpers + cookie-only + cookie-or-bearer dependencies.
- `backend/app/dependencies/auth.py` — `get_current_user` now hybrid (cookie OR Bearer).
- `backend/app/dependencies/stream_auth.py` — renamed primary fn to `get_user_for_stream`; cookie-preferred; `?token=` retained as deprecated fallback with WARNING log.
- `backend/app/routers/auth.py` — `/signup`, `/login`, `/refresh` set cookies; `/refresh` accepts cookie alone; new `/logout` clears cookies.
- `backend/app/static/nai/signup.html`, `login.html`, `pricing.html` — three new pages.
- `backend/app/static/nai/auth.js` — shared form-bind / require-auth / logout helpers.
- `backend/app/static/nai/pricing.js` — subscribe → checkout → Stripe redirect (with "resume after signup").
- `backend/app/static/nai/chat.js` — rewritten for cookie auth; localStorage JWT removed.
- `backend/app/static/nai/index.html` — header gains Pricing link + Log out button.
- `backend/app/static/nai/style.css` — additional rules for auth cards, pricing grid, header utility classes.
- `backend/tests/test_cookie_auth.py` — 13 tests (cookie issuance, attributes, /auth/me cookie+bearer, /auth/logout, /auth/refresh cookie-only, SSE cookie path, deprecated `?token=` path with warning).
- `deploy/verify_stage.sh` — new `case 6)` branch runs all the above plus DB-backed pytest when `TEST_DATABASE_URL` is reachable.

## What's deferred to the operator (Phase B activation)

These need real-world action, not code. They're tracked in `docs/STAGE_6_OPERATOR_TODO.md` (committed alongside this decision log):

1. Provision a test Postgres so `pytest tests/test_cookie_auth.py` actually runs (verifier currently `DEFERRED`s it).
2. Switch Stripe keys from test → live, set real `STRIPE_PRICE_PRO` + `STRIPE_PRICE_ELITE` price IDs.
3. Cloudflare Tunnel from `narai.wheellsverse.com` → `127.0.0.1:8001`. Bind change is operator-decision; the code is bind-agnostic.
4. Set `APP_ENV=production` so cookies become `Secure` automatically.
5. Update `STRIPE_SUCCESS_URL` + `STRIPE_CANCEL_URL` + `CORS_ORIGINS` to the production domain.
6. Public smoke test from a clean browser: signup → pricing → Stripe test checkout → return → chat works on cookie alone.
7. Decide whether `nai_refresh` should outlive logout for "remember me" — current default is "no, logout kills both cookies." Out-of-scope for this stage.

## What this stage does NOT prove

Per HONESTY rule 4 ("file existence ≠ correctness"): file presence and import-graph cleanliness are verified. End-to-end behavior (cookie flowing through real browser → real Stripe → live webhook) is **not** verified by this stage. That's the Phase B activation gate, not Stage 6.
