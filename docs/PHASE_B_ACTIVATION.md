# Phase B activation — public-launch runbook

**Pre-reqs (all confirmed earlier this week):**

- Stage 6 + Path X code-complete, 157/157 tests PASS, decision logs `0007-0009` locked.
- All four leaked `.env` secrets rotated and verified dead (`SUPABASE_SECRET_KEY`, DB password, `JWT_SECRET_KEY` → `ADMIN_TOKEN`, `SUPABASE_PUBLISHABLE_KEY`).
- Real-Supabase prod smoke test passed (`scripts/path_x_smoke.sh` → signup → trigger → chat → persist → cleanup, all 6 steps green).
- NAI daemon serves at `127.0.0.1:8001` under launchd; reboot-survival proven.

**This runbook ships everything from "the app works on 127.0.0.1" to "anyone with the public URL can sign up, pay, and chat." Five steps, in this order. The order matters — `APP_ENV=production` before HTTPS-front would break login cookies (`Secure` flag requires HTTPS).**

---

## §3 — Cloudflare Tunnel (do this FIRST so HTTPS exists)

Why first: every other step downstream assumes a real HTTPS hostname.

```bash
# Install if not present
brew install cloudflared
cloudflared --version

# One-time browser login (links cloudflared to your Cloudflare account)
cloudflared tunnel login
# A browser opens — pick the zone (the domain whose tunnel you're creating)

# Create the tunnel (writes ~/.cloudflared/<UUID>.json)
cloudflared tunnel create wheellsverse-nai
# Note the UUID it prints — you'll need it in the config.

# Point a public hostname at the tunnel
cloudflared tunnel route dns wheellsverse-nai narai.wheellsverse.com
```

Write `~/.cloudflared/config.yml`:

```yaml
tunnel: <PASTE THE UUID FROM cloudflared tunnel create>
credentials-file: /Users/jhonwheeler/.cloudflared/<UUID>.json

ingress:
  - hostname: narai.wheellsverse.com
    service: http://127.0.0.1:8001
  - service: http_status:404
```

Install as a system service so it auto-starts on reboot:

```bash
sudo cloudflared service install
sudo launchctl kickstart -k system/com.cloudflare.cloudflared 2>/dev/null \
  || sudo brew services restart cloudflared

# Verify
curl -I https://narai.wheellsverse.com/health
# Expect: HTTP/2 200
```

Done when: `curl -I https://narai.wheellsverse.com/health` returns `HTTP/2 200` with a real TLS handshake (no `-k` flag needed).

---

## §4 — `APP_ENV=production`

Why now (and not before §3): the cookie helper at `app/dependencies/cookie_auth.py:_cookie_secure()` gates the `Secure` cookie flag on `APP_ENV`. In production it auto-sets `Secure`, which the browser will refuse to honor over plain HTTP (so all your login cookies would silently fail to set). The security-headers middleware at `app/middleware/security_headers.py` does the same for `Strict-Transport-Security`. Both are no-ops in dev; both require real HTTPS in prod, which §3 just gave you.

```bash
cd /Users/jhonwheeler/wheellsverse_bots
# Replace APP_ENV in backend/.env (single-line sed substitution; values stay
# on disk only — never echoed to terminal).
if grep -q '^APP_ENV=' backend/.env; then
  sed -i.bak.appenv 's/^APP_ENV=.*/APP_ENV=production/' backend/.env
  rm -f backend/.env.bak.appenv     # bak file isn't needed; gitignored anyway
else
  printf '\nAPP_ENV=production\n' >> backend/.env
fi
chmod 600 backend/.env

# Verify the line is set without echoing surrounding content
grep '^APP_ENV=' backend/.env

# Restart NAI so the change takes effect
launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai
sleep 3

# Confirm HSTS now appears (it's absent in dev)
curl -sI https://narai.wheellsverse.com/health | grep -i strict-transport
# Expect: strict-transport-security: max-age=31536000; includeSubDomains
```

Done when: the `strict-transport-security` header appears on every response from the public URL.

---

## §5 — `CORS_ORIGINS` to production domain

Why: the FastAPI `CORSMiddleware` defaults to `localhost`; without this, fetches from the production domain get blocked by the browser's CORS check.

```bash
cd /Users/jhonwheeler/wheellsverse_bots
# Set the comma-separated list (the config.py parser handles commas).
# Substitute your real domain — narai.wheellsverse.com is the §3 example.
NEW_ORIGINS="https://narai.wheellsverse.com"
if grep -q '^CORS_ORIGINS=' backend/.env; then
  python3 -c "
import os
key = 'CORS_ORIGINS'
val = '$NEW_ORIGINS'
lines = open('backend/.env').readlines()
with open('backend/.env','w') as f:
    for L in lines:
        f.write(f'{key}={val}\n' if L.startswith(f'{key}=') else L)
"
else
  printf '\nCORS_ORIGINS=%s\n' "$NEW_ORIGINS" >> backend/.env
fi
chmod 600 backend/.env
grep '^CORS_ORIGINS=' backend/.env

launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai
sleep 3

# Smoke: preflight from the prod domain must be allowed
curl -sI -X OPTIONS https://narai.wheellsverse.com/auth/login \
  -H "Origin: https://narai.wheellsverse.com" \
  -H "Access-Control-Request-Method: POST" \
  | grep -i 'access-control-allow-origin'
# Expect: access-control-allow-origin: https://narai.wheellsverse.com
```

Done when: the preflight response includes `Access-Control-Allow-Origin` matching your prod domain.

---

## §2 — Stripe test → live keys

Why ordered after §3-§5: Stripe webhooks need a public HTTPS endpoint to deliver to, and your CORS rules need to be settled so the Stripe checkout redirects work.

**Pre-reqs in the Stripe dashboard:**

1. Activate live mode on the account (Dashboard → toggle from "Test mode" to "Live mode").
2. Developers → API keys → reveal the **live** Secret key (`rk_live_…` or `sk_live_…`).
3. Products → create the live Pro and Elite recurring prices. Copy their `price_…` IDs.
4. Developers → Webhooks → add a live endpoint at `https://narai.wheellsverse.com/billing/webhook`. Subscribe to event: `checkout.session.completed`. Copy the signing secret (`whsec_…`).
5. Also update `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL` to point at the prod domain (steps below).

Run the paste script (hidden stdin, never echoes secrets, refuses test keys, runs a live `/v1/balance` probe to confirm the key authenticates):

```bash
cd /Users/jhonwheeler/wheellsverse_bots
./scripts/configure_stripe_live.sh
# Prompts for: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_PRO, STRIPE_PRICE_ELITE
```

Also update the redirect URLs:

```bash
python3 - <<PY
import sys
updates = {
    "STRIPE_SUCCESS_URL": "https://narai.wheellsverse.com/nai-ui/?subscribed=1",
    "STRIPE_CANCEL_URL":  "https://narai.wheellsverse.com/nai-ui/pricing.html?canceled=1",
    "BILLING_PUBLIC_UPGRADE_URL": "https://narai.wheellsverse.com/nai-ui/pricing.html",
}
seen = {k: False for k in updates}
with open("backend/.env") as f:
    lines = f.readlines()
with open("backend/.env","w") as f:
    for L in lines:
        wrote = False
        for k, v in updates.items():
            if L.startswith(f"{k}="):
                f.write(f"{k}={v}\n"); seen[k] = True; wrote = True; break
        if not wrote:
            f.write(L)
    for k, v in updates.items():
        if not seen[k]:
            f.write(f"{k}={v}\n")
PY

chmod 600 backend/.env
launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai
```

Done when: `configure_stripe_live.sh` prints `Stripe LIVE API accepted the secret key (balance object returned)`.

---

## §6 — Public-browser end-to-end smoke (the launch gate)

This is the test that decides "Stage 6 + Path X is live for real users," not just operationally configured.

In a **clean incognito window** (no cookies, no localStorage from any prior dev session), in this exact order:

1. Visit `https://narai.wheellsverse.com/nai-ui/pricing.html`.
2. Click **Subscribe to Pro**. Expect: redirected to `/nai-ui/signup.html?next=/nai-ui/pricing.html`.
3. Sign up with a throwaway email + 10+ char password. Expect: 201, redirected to `/nai-ui/`.
4. Chat page loads. DevTools → Application → Cookies → `https://narai.wheellsverse.com` should show `nai_access` and `nai_refresh` with **`Secure: true`, `HttpOnly: true`, `SameSite: Lax`**.
5. Click **Pricing** in the header → land on pricing.html with cookies still attached.
6. Click **Subscribe to Pro** again. This time (because `nai_pending_plan` was set on the first attempt + you're now logged in), expect immediate redirect to `checkout.stripe.com`.
7. Pay with a real card (this is live mode). Stripe redirects back to `/nai-ui/?subscribed=1`.
8. `GET /billing/subscription` (DevTools or curl with cookie) should return `status: "active"` with the right `plan_code`.
9. Send a chat from the chat page. Expect: a real AI response, persisted (refresh the page → conversation still there).
10. Click **Log out** → land on login.html. Visit `/nai-ui/` directly → bounced back to login (cookies cleared).

Then **clean up the test user** via the Supabase Auth dashboard (or with the same `c.auth.admin.delete_user(id)` pattern used in `scripts/path_x_smoke.sh` step 5 — adapt the email filter).

If all ten steps pass: tag the repo `stage-6-live`:

```bash
git tag -a stage-6-live -m "Stage 6 + Path X live in production after the four-secret rotation"
git push origin stage-6-live   # if a remote is configured
```

---

## Rollback plan (if any step fails)

Every step in §3-§5 is a single env-file edit; revert by restoring the relevant `backend/.env.bak.*` backup:

```bash
# General pattern (substitute the right backup)
cp backend/.env.bak.<which-rotation> backend/.env
chmod 600 backend/.env
launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai
```

§3 Cloudflare Tunnel can be paused without rollback:

```bash
sudo brew services stop cloudflared
# Public URL goes down; NAI still works on 127.0.0.1:8001
```

§2 Stripe is reversible by restoring the prior `backend/.env.bak.stripe-*`. Any live transactions that already happened stay on Stripe's books — no DB rollback needed for those.

---

## What this runbook does NOT cover

- **Email deliverability** for Supabase Auth's verification + password-reset flows. We set `email_confirm=True` in `create_user`, which skips the verification email. If you flip that off and need real email delivery, configure Supabase Auth's SMTP settings.
- **Custom Stripe Customer Portal branding** (Stripe dashboard → Settings → Billing → Customer portal).
- **Cloudflare WAF rules** to rate-limit the public surface beyond the slowapi in-process limits. Cloudflare's free tier supports this; add IP-based rate-limit rules in the Cloudflare dashboard.
- **Sentry / OpenTelemetry / log shipping** off the Mac mini. NAI logs to `~/Library/Logs/wheellsverse/nai.stderr.log` only.
- **Domain registration + DNS pointing to Cloudflare** — assumed already done if §3's tunnel route command succeeds.

These are all "nice to have" for a single-operator paid SaaS; not blockers for the first paying user.
