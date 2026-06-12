# Stage 6 — Operator-side TODOs

Stage 6 ships code-complete: cookie auth, signup/login/pricing UI, Stripe-checkout wiring, verifier hooks, decision log 0007. **None of it is "live"** until the work in this file is done — the work below is operator-side because it touches real money, real domains, or real machines.

This is a runbook, not a status report. Tick items off when done.

---

## 1. Provision a real test Postgres ✅ DONE (2026-05-26)

Completed locally on the build host. Result:

```bash
brew install postgresql@17                # pg16 swapped: pgvector only ships for 17/18
brew install pgvector
initdb /opt/homebrew/var/postgresql@17 -U $USER
brew services start postgresql@17
createdb -U postgres -O postgres wheellsverse_test
psql -d wheellsverse_test -c "CREATE EXTENSION pgcrypto; CREATE EXTENSION vector;"
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/wheellsverse_test"
cd backend && pytest tests/test_cookie_auth.py -v --tb=short
# Result: 13 passed
```

While running the sweep, the test DB exposed **two pre-existing schema-drift bugs** that production must address (test-side workaround already shipped in `backend/tests/conftest.py`):

1. **`conversations.user_id` / `messages.user_id` / `llm_call_log.user_id` FK to `profiles.id`** — inherited from NarAI v1's Supabase `auth.users → profiles` trigger. But the SQLAlchemy `User` model owns the `users` table, and `/auth/signup` writes there, not `profiles`. So a fresh signup user has no `profiles` row and any conversation/message/log insert violates the FK. Today this only works in production because legacy NarAI v1 had populated `profiles` for the existing users. New signups will hit this on first chat/persist call.
   - **Operator fix (Phase B):** either (a) ALTER the FK target to `users.id` (preferred — single source of truth), or (b) add a Supabase trigger that auto-creates a `profiles` row whenever a `users` row is inserted.
2. **`llm_call_log` has no SQLAlchemy model** — Alembic migration 0004 creates it; `spend_tracker.py` writes via raw SQL. This isn't a runtime bug but it means new dev environments can't bootstrap a test DB from `Base.metadata.create_all()` alone. **Operator fix (low priority):** add an `LLMCallLog` SQLAlchemy model mirroring the Alembic schema so the test layer doesn't need a shadow declaration.

---

## 2. Stripe: switch from test → live

**Why:** Stage 5 wired the checkout flow with test keys. Stage 6 marketing pages POST to `/billing/checkout` regardless of key mode, so flipping to live keys is purely env-side.

**Steps:**

1. Stripe Dashboard → Developers → API keys → reveal **live** secret key. Paste into `wvkey set STRIPE_SECRET_KEY ...` (vault). Update `backend/.env` to read from vault.
2. Stripe Dashboard → Products → create **Pro** and **Elite** recurring prices. Copy the `price_...` IDs.
3. Set `STRIPE_PRICE_PRO=price_xxx` and `STRIPE_PRICE_ELITE=price_yyy` in `backend/.env`.
4. Stripe Dashboard → Webhooks → add endpoint `https://YOUR_DOMAIN/billing/webhook`. Subscribe to `checkout.session.completed`. Copy signing secret → `STRIPE_WEBHOOK_SECRET`.
5. Set `STRIPE_SUCCESS_URL=https://YOUR_DOMAIN/nai-ui/?subscribed=1` and `STRIPE_CANCEL_URL=https://YOUR_DOMAIN/nai-ui/pricing.html?canceled=1`.
6. Restart NAI: `launchctl unload ~/Library/LaunchAgents/com.wheellsverse.nai.plist && launchctl load ...`

**Validate:** From a new browser, sign up → /nai-ui/pricing.html → Subscribe to Pro → should land on `checkout.stripe.com` with the live price displayed.

---

## 3. Cloudflare Tunnel from public domain → 127.0.0.1:8001

**Why:** NAI binds to `127.0.0.1:8001` only (Stage 5 decision). Cloudflare Tunnel exposes that without opening a port on the Mac mini.

**Steps:**

1. `brew install cloudflared`
2. `cloudflared tunnel login`
3. `cloudflared tunnel create wheellsverse-nai` (note the UUID)
4. `~/.cloudflared/config.yml`:

   ```yaml
   tunnel: <UUID>
   credentials-file: /Users/jhonwheeler/.cloudflared/<UUID>.json
   ingress:
     - hostname: narai.wheellsverse.com
       service: http://127.0.0.1:8001
     - service: http_status:404
   ```

5. `cloudflared tunnel route dns wheellsverse-nai narai.wheellsverse.com`
6. `cloudflared service install` — runs the tunnel as a launchd-managed daemon
7. Verify: `curl -I https://narai.wheellsverse.com/health` returns `200`.

---

## 4. Flip `APP_ENV=production`

**Why:** The cookie helper gates the `Secure` flag on `APP_ENV`. Anything other than `development|dev|local|test` enables `Secure`, which means cookies are sent over HTTPS only. After step 3 you're on HTTPS — set `APP_ENV=production` in `backend/.env`. Restart NAI.

**Validate:**

```bash
curl -i -X POST https://narai.wheellsverse.com/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"YOU","password":"YOU"}' | grep -i "set-cookie"
```

Expected: `Set-Cookie: nai_access=...; HttpOnly; Secure; SameSite=Lax; Path=/`.

---

## 5. Update `CORS_ORIGINS`

**Why:** Defaults are localhost dev URLs. Add the production domain so browser fetches aren't blocked by CORS.

`backend/.env`:

```
CORS_ORIGINS=https://narai.wheellsverse.com
```

Restart NAI.

---

## 6. Public smoke test from a clean browser

This is the gate that decides "Stage 6 is live, not just deployed."

1. **New incognito window** (no cookies, no localStorage).
2. Visit `https://narai.wheellsverse.com/nai-ui/pricing.html`.
3. Click **Subscribe to Pro** → expect redirect to `/nai-ui/signup.html?next=...`.
4. Create an account with a real-ish email + 8+ char password → expect redirect to `/nai-ui/` (the chat page).
5. Expected: chat page loads. DevTools → Network: `Cookie: nai_access=...; nai_refresh=...` on `/auth/me`.
6. Click **Pricing** in the chat header → expect chat page persistence (cookie still there).
7. Click **Subscribe to Pro** again → expect immediate redirect to `checkout.stripe.com` (the "resume after signup" path).
8. Pay with a real card (test mode is over — this is live). Stripe redirects back to `/nai-ui/?subscribed=1`.
9. Verify `GET /billing/subscription` returns `status: active` with the right `plan_code`.
10. Click **Log out** → expect redirect to login page. Visit `/nai-ui/` directly → expect bounce back to login (cookies cleared).

If all 10 pass: **Stage 6 is live.** Tag the repo `stage-6-live`.

If step 7 redirects to signup again (i.e. cookie didn't survive the round-trip), check `SameSite` + `Secure` + your domain config. Lax + Secure on a same-origin GET should work.

---

## 7-X. Path X — Supabase Auth alignment (DONE 2026-05-28)

The schema-drift bug surfaced during operator-TODO §1 turned out to be much
bigger than a missing trigger — Stage 6 had reinvented self-managed JWT auth
against a `public.users` table that doesn't exist in prod. See decision log
[0008-path-x-supabase-auth.md](decisions/0008-path-x-supabase-auth.md) for
the full story.

**Status:** code-complete + 155 tests PASS + Stage 6 verifier 49/49 (path-X
checks added).

**Operator action required:**
1. ~~**Rotate `sb_secret_*` immediately**~~ **DONE 2026-05-28** — old key
   `sha256_prefix=499e5b97f415` was revoked server-side by Supabase
   ("Unregistered API key" on probe); new key `sha256_prefix=204e005f5221`
   pasted into `backend/.env` via `scripts/rotate_supabase_secret.sh`
   (hidden-stdin read, never echoed to chat). Live admin probe authenticated
   successfully. **NEXT:** restart the NAI daemon so it picks up the new env:
   ```bash
   launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai
   ```
2. **Smoke-test against real Supabase** (not the in-memory test fake):
   ```bash
   curl -X POST http://127.0.0.1:8001/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email":"pathx-test@example.com","password":"TestPass123!"}'
   ```
   Then verify the trigger fired:
   ```bash
   psql "$DIRECT_DATABASE_URL" -c \
     "SELECT email FROM profiles WHERE email='pathx-test@example.com';"
   ```
   Then send a chat as that user. If `/nai/chat` returns a conversation_id
   (not a 500), Path X is live in prod. Clean up the test user from the
   Supabase Auth dashboard afterwards.

---

## 7. Deferred design questions (NOT blockers)

Things to think about once Stage 6 is live and you have real user behavior to look at:

- **Remember-me:** currently `/auth/logout` clears both cookies. If users complain about being kicked out every refresh-token lifetime (7 days), add a "Stay logged in" checkbox on login that issues a longer refresh cookie.
- **Email verification gate:** `User.is_verified` exists but isn't enforced. Decide whether free users need a confirmed email before they can chat / subscribe.
- **CSRF for `/auth/logout`:** Lax cookies stop cross-origin POST CSRF, so logout-CSRF doesn't actually log anyone out maliciously, but if you want defense-in-depth, add a CSRF token round-trip on auth-mutating routes.
- **Drop the SSE `?token=` fallback:** once `grep "deprecated ?token=" backend.log` returns zero hits for ~1 week, delete the fallback in `app/dependencies/stream_auth.py`.
- ~~**Rate limiting on `/auth/login` + `/auth/signup`:** the current code has no throttle. Once you're public, a tiny `slowapi` decorator is the smallest fix.~~ **DONE 2026-05-26** — `slowapi` Limiter wired in `app/core/rate_limit.py`, decorators on signup (5/min), login (10/min), refresh (20/min); tests at `tests/test_auth_rate_limit.py` (3/3 PASS). For multi-worker uvicorn, switch to `storage_uri="redis://..."` so counters stay consistent across workers.
- ~~**Security headers** (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy)~~ **DONE 2026-05-26** — `SecurityHeadersMiddleware` in `app/middleware/security_headers.py`, mounted outermost so it covers every response (including 429s, SSE, static HTML). HSTS auto-enables when `APP_ENV` is non-dev. CSP is strict — `script-src 'self'` with no `'unsafe-inline'`; the prior inline `<script>` blocks in `signup.html`/`login.html` were moved to `signup-init.js`/`login-init.js`. 7 tests in `tests/test_security_headers.py` (7/7 PASS). The `'preload'` HSTS directive is deliberately omitted — operator adds it after confirming HSTS works for a few weeks and submitting to <https://hstspreload.org>.

---

## 8. What this document does NOT cover

- Email delivery (transactional welcome email, password-reset link). Not built yet; not a Stage 6 deliverable.
- Customer-portal UX (using `/billing/portal` to cancel/change plan). Endpoint exists but no UI link; add when needed.
- Admin dashboard for viewing users / revenue. Stage 5's `admin_data` router has the read side; UI is operator-side.
