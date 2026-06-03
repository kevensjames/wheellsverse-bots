# KAI (née NAI) Launch — Handoff

**Last updated:** 2026-06-03 10:55 UTC (post-Stage-8 rebrand)
**Branch:** `feat/kdp-fillers` (7 commits ahead of main, unpushed)
**Canonical domain:** `https://kai.wheellsverse.com`
**State:** Live, paid traffic ready, fully rebranded NAI→KAI end-to-end.

## What changed since last handoff (3b76f6f)

- Stage 8 rebrand shipped (`74ee77d`): static text, Stripe products, API
  dual-mount /kai/+/nai/, UI dual-mount /kai-ui/+/nai-ui/, kai.* DNS +
  tunnel ingress, CF Page Rule 301 nai.*→kai.*, system prompt, launch
  blog post — all KAI.
- Supabase Auth email templates branded via Management API (4 subjects +
  4 bodies, all "KAI").
- Stripe webhook URL repointed nai.*/billing/webhook → kai.*/billing/webhook
  (Stripe doesn't follow 301 on POST; live-signed payload verified 200
  through the tunnel).
- Bare-domain + common typos now redirect to chat UI (`4ab5ba7`):
  `/`, `/login`, `/signup`, `/pricing` → 307 → `/kai-ui/...`
  (was: bare domain showed `{"name":"...","version":"0.1.0"}` JSON blob).
- Browser 404 → /kai-ui/ catch-all middleware (`7c2fc52`):
  /chat, /dashboard, /account, /settings, /foo, /kai-ui/anything — any
  navigation-style path (no .css/.js/.png extension, not in /kai/ /auth/
  /billing/ etc.) sent to /kai-ui/ as a 307. Asset 404s and API 404s
  stay loud.
- Decision log: `docs/decisions/0010-rename-nai-to-kai.md`
- Evidence: `evidence/stage_8_kai_rebrand_20260603T101310Z.log`
- Tests: 157/157 still pass after all of the above.

---

## TL;DR

NAI is up at https://nai.wheellsverse.com with a paid checkout flow that
actually works end-to-end now. Schema drift fixed. Webhook delivery verified
**through the tunnel** (not just localhost). Cloudflare edge tuned so it
stops 403'ing Stripe. 157/157 backend tests pass. Launch blog post drafted
locally, awaiting user review before publishing.

---

## The plan (where we started, where we are)

**Original goal:** Phase B activation runbook (§2 Stripe live, §3 CF Tunnel,
§4 APP_ENV=production, §5 CORS, §6 incognito phone smoke). The §6 smoke
test failed at 6:18 AM with the first real $29 charge — "Stream error" +
no subscription activation. That failure cascaded into the work below.

### What was wrong on 2026-06-02 morning

1. **Schema drift.** Code modeled a `Plan` table that didn't exist in prod
   Supabase. Webhook handler tried to FK against it and crashed silently.
2. **OpenAI dead.** Key was revoked; chat returned "Stream error."
3. **Webhook misconfigured.** Stripe dashboard pointed at
   `app.wheellsverse.com/api/stripe/webhook` (TG bot), not NAI.
4. **`/predictions/stats` 500.** Prod has no `predictions` table; every
   landing-page render leaked a psycopg2 traceback.
5. **`DEBUG=true` in prod.** Leaking full tracebacks on any 500.
6. **HIDDEN:** Cloudflare `browser_check` was silently 403'ing Stripe's
   webhook delivery at the edge. Even with a correctly-configured
   webhook, no events ever reached the daemon. (Discovered during
   handoff verification — would have caused every paid sub to silently
   fail to activate.)

### What I shipped (commits on `feat/kdp-fillers`)

| Commit | What |
|---|---|
| `5fd2cc5` | Dropped fictional `Plan` model; built `app/services/billing/tiers.py` registry; rewrote `Subscription` to match prod schema (`tier`, `stripe_subscription_id UNIQUE`, `stripe_price_id`); webhook upserts by stripe_subscription_id; profile.tier mirror for fast rate-limit reads |
| `4fcfda3` | `/predictions/stats` fail-open with zeros when prod table missing (catches `ProgrammingError`, rolls back session, doesn't poison Redis cache) |

### What I did outside git (config + external systems)

- **OpenAI key:** rotated 2 times today (most recent: `sk-proj-knc…` in
  `.env` mode 600). `chat/completions` returns 200.
- **Stripe webhook endpoint:** registered via API at
  `we_1Tdql8AmcmaDynHNUdfdQdR8` → `https://nai.wheellsverse.com/billing/webhook`,
  4 events (`checkout.session.completed`, `customer.subscription.updated/deleted`,
  `invoice.payment_failed`). Signing secret in `STRIPE_WEBHOOK_SECRET`.
- **Cloudflare zone (`wheellsverse.com`, Free plan):**
  - `always_use_https` off → **on**
  - `min_tls_version` 1.0 → **1.2** (kills POODLE/BEAST)
  - `automatic_https_rewrites` on (no change)
  - `security_level` medium (no change)
  - `ai_bots_protection` block (kept — narrowly targets GPTBot/ClaudeBot)
  - `content_bots_protection` block → **disabled** (was over-blocking
    real traffic + curl)
  - `crawler_protection` enabled → **disabled** (was 403'ing landing page)
  - `browser_check` on → **off** (was 403'ing Stripe webhook delivery)
- **`backend/.env`:** `DEBUG=true` → `DEBUG=false`
- **`$29 charge`:** refunded by operator
- **NAI daemon:** restarted 4×; currently PID 46344

---

## Verified state (snapshot at handoff)

Every check below was run during this verification pass.

### Daemon
```
launchctl list | grep nai → 46344 -15 com.wheellsverse.nai
```

### Local endpoints (127.0.0.1:8001)
| Path | Code | Note |
|---|---|---|
| `/` | 200 | version JSON |
| `/docs` | 200 | OpenAPI |
| `/predictions/stats` | 200 | zeros, fail-open active |
| `/billing/subscription` | 401 | auth gate working |
| `/billing/checkout` (no auth) | 401 | auth gate working |
| `/billing/webhook` (no sig) | 400 | sig gate working |
| `/billing/webhook` (signed) | 200 | `{"received":true}` |
| `/nai-ui/pricing.html` | 200 | Elite plan hidden |

### Tunnel endpoints (https://nai.wheellsverse.com)
| Path | Code |
|---|---|
| `/` | 200 |
| `/docs` | 200 |
| `/predictions/stats` | 200 |
| `/billing/subscription` | 401 |
| `/nai-ui/pricing.html` | 200 |
| `/nai-ui/login.html` | 200 |
| `/billing/webhook` (signed) | **200** ← critical fix |

### External APIs
- **OpenAI** `chat/completions` with current `.env` key → 200
- **Stripe** restricted key (`rk_live_*`) → write-scoped for webhook endpoints
- **Cloudflare** API token (`cfut_7Qi…`) → Zone Settings + Bot Management Edit

### Tests
```
backend/tests/ → 157 passed in 14.13s
(includes test_brain + test_memory now that OpenAI works)
```

### Security headers (live, on https://nai.wheellsverse.com/nai-ui/pricing.html)
```
strict-transport-security: max-age=31536000; includeSubDomains
content-security-policy: default-src 'self'; script-src 'self'; ...
x-frame-options: DENY
x-content-type-options: nosniff
referrer-policy: strict-origin-when-cross-origin
permissions-policy: accelerometer=(), camera=(), geolocation=(), ...
```

---

## Pending (operator + rotation)

### 1. Rotation queue (post-launch, do this when stable)

Three credentials were pasted into the chat transcript during this session.
After the launch is stable and you've confirmed no immediate fires:

- **`OPENAI_API_KEY`** = `sk-proj-knc…` — rotate at
  https://platform.openai.com/api-keys
- **`CLOUDFLARE_API_TOKEN`** (write-scoped, the second one) =
  `cfut_7QiF21W8…` — roll at dash.cloudflare.com → My Profile → API Tokens
- **`CLOUDFLARE_API_TOKEN`** (read-only, the first one) = `cfut_oMNvK2MP…`
  — same place; can just delete it (no longer needed)

Atomic swap pattern (use this for each):
```bash
cd ~/wheellsverse_bots && cp .env .env.bak.rot-$(date +%s)
.venv/bin/python -c "
import re, pathlib, os, sys
T = sys.argv[1]; p = pathlib.Path('.env')
n = re.sub(r'^OPENAI_API_KEY=.*$', 'OPENAI_API_KEY='+T, p.read_text(), flags=re.MULTILINE)
p.write_text(n); os.chmod(p, 0o600)
" NEW_KEY_HERE
launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai
```

### 2. Stripe dashboard webhook event log

The webhook is registered correctly NOW, but events Stripe sent earlier
today (before fix) were 403'd at Cloudflare. Worth checking:

1. dash.stripe.com → Developers → Webhooks → `we_1Tdql8…`
2. Look at "Recent deliveries" — any that show response 403, body
   `error code: 1010`? Those are events that need redelivery.
3. For each: click → "Resend" — the daemon will now process them
   (handler is idempotent via `stripe_subscription_id UNIQUE`).

### 3. Launch blog post

Drafted: `outputs/marketing/launch/nai_launch_founder_origin.md` (~1100 words,
founder voice, no affiliate links, single CTA to nai.wheellsverse.com).

**Two facts in the post you should sanity-check before publishing:**

- "~$4–7/mo OpenAI cost per active user" — if your actual margin is
  different, fix the number before HN sees it.
- "I haven't slept through a Telegram alert yet" — true today; ages
  badly if you sleep through one this week. Consider softening.

---

## Known issues / followups (non-blocking)

| Issue | Impact | Fix |
|---|---|---|
| `/predictions` table never migrated to prod | `/today` and `/{symbol}` are auth-only so it's invisible to landing page, but they'll 500 for any authed user | Apply the migration OR remove the routes |
| `browser_check` is OFF for whole zone | Slightly more bot noise hitting the daemon (signed/auth-gated, so no real risk) | If you want it back, add a WAF custom rule that skips BIC on `/billing/webhook` only — Free plan has 5 custom rules available |
| PyJWT `InsecureKeyLengthWarning` in test suite | Test-only — prod uses ES256/JWKS via Supabase, never HS256 | Bump the test fixture's `JWT_SECRET_KEY` to ≥32 chars |
| `app/services/billing/` is a new dir w/ no `__init__.py` content | Empty `__init__.py` was created and is committed — Python treats this as a namespace package, works fine | Leave it |
| `bots/marketing/16_blog_publisher` has affiliate-injection at base class level that bypasses the `include_affiliate=False` flag | Generated junk content + auto-fired a Telegram notification when I tried to use it for the launch post | Don't use the blog_publisher bot for own-product launches; hand-write or build a separate `own_product_publisher` |

---

## Files touched this session (not yet committed)

```
.env                                  ← 4 changes: OPENAI_API_KEY x2,
                                        STRIPE_WEBHOOK_SECRET, CLOUDFLARE_API_TOKEN x2
backend/.env                          ← DEBUG: true → false
~/.cloudflared/config.yml             ← unchanged this session (was done 2026-06-02 AM)
/Library/LaunchDaemons/com.cloudflare.cloudflared.plist
                                       ← unchanged this session
outputs/marketing/launch/nai_launch_founder_origin.md  ← new file
HANDOFF.md                            ← this file
```

Bot/blog/dashboard tree has ~80 modified files unrelated to NAI work
(autopublish runs from other days). Leave them.

---

## Resume protocol (next session, after compact)

1. `cd ~/wheellsverse_bots && git status` — confirm `HANDOFF.md` + the
   schema-drift + stats commits are visible.
2. `launchctl list | grep nai` — daemon should be alive.
3. `curl -s -o /dev/null -w "%{http_code}\n" https://nai.wheellsverse.com/`
   should return 200.
4. Read this file's "Pending" section.
5. The two memory entries to refresh:
   - `nai_phase_b_complete.md`
   - `wheellsverse_bots_repo.md`
6. The committed work is on `feat/kdp-fillers` branch ahead of `main`
   by 2 commits (the two table rows above). Not pushed.

---

## What I'm *not* going to lie about

- I claimed earlier in the session that the Stripe webhook was
  "registered + verified" after I tested it. That test only hit
  `127.0.0.1:8001/billing/webhook` — not the tunnel. The tunnel was
  403-ing Stripe the whole day. I caught this during the handoff
  verification pass and fixed it. Worth a re-test from the Stripe
  dashboard side to confirm a real Stripe-sent event lands.
- The Cloudflare hardening pass had two regressions
  (`crawler_protection` + `content_bots_protection` were too aggressive)
  that took 1 round of revert to clean up. Currently stable, but the
  fact that the same toggle phrasing in the dashboard means different
  things on different plans is a continuing risk if you tighten further.
- The launch blog post is unpublished and untested. It's plausible copy,
  but HN/Reddit have a high bar for founder voice — read it once with
  fresh eyes before posting.

---

*Built and verified 2026-06-02 → 2026-06-03 by Claude Opus 4.7 working
autonomously in Claude Code. Owner: kevens.james48029@gmail.com.*
