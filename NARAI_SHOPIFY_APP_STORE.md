# NarAI × Shopify App — Submission Checklist

Everything required to ship the NarAI Product Engine to the Shopify App Store.

---

## 1. Current State (code-complete phases)

| Phase | Status | Files |
|-------|--------|-------|
| 1 — DB schema | ✅ SQL file ready (paste in Supabase) | `supabase_shopify_multitenant.sql` |
| 2 — OAuth flow | ✅ Deployed | `narai/api/routes/shopify_oauth.py` |
| 3 — Webhooks (HMAC + GDPR) | ✅ Deployed | `narai/api/routes/shopify_webhooks.py`, `narai/core/shopify_mt/webhooks.py` |
| 4 — Multi-tenant pipeline | ✅ Deployed | `narai/core/shopify_mt/products.py`, `client.py` |
| 5 — Stripe billing + plan gating | ✅ Deployed | `narai/core/shopify_mt/billing.py`, `narai/api/routes/shopify_billing.py` |
| 6 — Admin dashboard | ✅ Deployed | `frontend/admin/shopify.html`, `narai/api/routes/shopify_admin.py` |
| 7 — App Store submission | 📋 This doc | *(this file)* |

---

## 2. Environment Variables (Railway)

Already set by automation:
- `APP_URL=https://app.wheellsverse.com`
- `MERCHANT_TOKEN_KEY=<Fernet>`
- `SHOPIFY_OAUTH_STATE_KEY=<random>`
- `SHOPIFY_SCOPES=read_products,write_products,read_orders,read_inventory,write_inventory`

**Still needed (user action):**
- `SHOPIFY_API_KEY` — from Shopify Partner dashboard after creating the app
- `SHOPIFY_API_SECRET` — same
- `STRIPE_PRICE_MERCHANT_STARTER=price_...`
- `STRIPE_PRICE_MERCHANT_PRO=price_...`
- `STRIPE_PRICE_MERCHANT_ELITE=price_...`
- `STRIPE_MERCHANT_WEBHOOK_SECRET=whsec_...` (create a dedicated Stripe webhook endpoint for `/shopify/billing/webhook`)

---

## 3. Shopify Partner Setup (one-time)

1. Sign up at https://partners.shopify.com (free).
2. Apps → Create app → Custom (private) to test first.
3. App setup:
   - **App URL:** `https://app.wheellsverse.com/admin/shopify`
   - **Allowed redirection URLs:**
     - `https://app.wheellsverse.com/shopify/callback`
   - **Embedded in Shopify admin:** No (standalone for now — Phase 2 can revisit with App Bridge)
4. Save → copy **Client ID** → Railway: `SHOPIFY_API_KEY`.
5. Copy **Client secret** → Railway: `SHOPIFY_API_SECRET`.
6. Redeploy `railway up --service wheellsverse-v2`.

---

## 4. Stripe Setup (one-time)

1. Dashboard → Products → create 3 products with recurring prices:
   - **NarAI Starter** — $19/mo
   - **NarAI Pro** — $49/mo
   - **NarAI Elite** — $149/mo
2. Copy each `price_...` ID → Railway env vars (see § 2).
3. Developers → Webhooks → Add endpoint:
   - URL: `https://app.wheellsverse.com/shopify/billing/webhook`
   - Events: `checkout.session.completed`, `customer.subscription.deleted`,
     `invoice.paid`, `invoice.payment_failed`
   - Copy signing secret → `STRIPE_MERCHANT_WEBHOOK_SECRET`.

---

## 5. Testing Checklist (before App Store review)

- [ ] Install flow works on a Shopify development store
- [ ] Uninstall webhook fires and sets `uninstalled_at` in `merchants`
- [ ] HMAC verification rejects forged webhook payloads (test with `curl -H 'X-Shopify-Hmac-Sha256: bad'`)
- [ ] Access tokens are encrypted at rest (query the DB directly — should be Fernet ciphertext, not plain)
- [ ] GDPR webhooks (`customers/data_request`, `customers/redact`, `shop/redact`) return 200 and log an event
- [ ] Installing 2 dev stores does not leak data between them (create a product on store A, verify it does not appear on store B)
- [ ] Free-tier merchant is blocked from Pro-tier features (quality gate + `require_plan` decorator)
- [ ] Stripe Checkout upgrade updates `plan_tier` within 5 seconds of `checkout.session.completed`
- [ ] `invoice.payment_failed` logs a `billing.failed` event
- [ ] Quality gate blocks products with < 4 images / < 300 char description / bad price

---

## 6. App Store Submission Requirements

### Required URLs (must be live)
- **App listing page** — built on Shopify Partner dashboard (screenshots + demo video)
- **Privacy policy** — `https://wheellsverse.com/privacy` (already live)
- **Terms of service** — `https://wheellsverse.com/terms` (already live)
- **Support email** — `support@wheellsverse.com` (set up a forward)

### Required webhooks (all implemented)
- `app/uninstalled` ✅
- `customers/data_request` ✅
- `customers/redact` ✅
- `shop/redact` ✅

### Listing copy (draft — edit before submission)

> **NarAI Product Engine — AI Products with 3D Images in One Click**
>
> NarAI writes your product listings and generates 4 studio-quality 3D images per product using DALL-E 3. Stop uploading blurry phone shots. Stop writing tired descriptions. Stop losing sales to the competitor with better photos.
>
> **What you get:**
> - AI-written product titles, descriptions, and SEO copy
> - 4 angled 3D images per product (hero, lifestyle, detail, flat-lay)
> - Hard quality gate — we never ship a broken listing
> - Printify integration for print-on-demand
> - Works with any product type: digital, physical, merch, subscriptions
>
> **Pricing:**
> - Free — 10 products/month to try
> - Starter $19 — 100 products
> - Pro $49 — 1000 products + priority
> - Elite $149 — Unlimited + dedicated support

### Listing assets (need to create)
- App icon — 1200×1200 PNG
- Feature banner — 1600×900 PNG
- Screenshots — at least 3 × 1600×900 showing the admin dashboard, a generated product, the install flow
- Demo video — 30-90 seconds, optional but dramatically improves review odds

---

## 7. Submission Flow

1. Start as **Custom app** → test with 2-3 friendly merchants for 1-2 weeks
2. Fix any bugs/edge cases found
3. On Partner dashboard → Distribution → **Switch to Public**
4. Fill listing form with copy + assets from § 6
5. Submit for review → Shopify team typically responds within 7-14 days
6. After approval → app is live in the Shopify App Store → every Shopify merchant can discover and install

---

## 8. Post-Launch Monitoring

Queries to run weekly on Supabase:

```sql
-- Growth: installs this week vs last
SELECT
  date_trunc('week', installed_at) AS week,
  count(*) FILTER (WHERE uninstalled_at IS NULL) AS active_installs,
  count(*) FILTER (WHERE uninstalled_at IS NOT NULL) AS uninstalls
FROM merchants
GROUP BY 1 ORDER BY 1 DESC LIMIT 8;

-- Revenue by plan tier
SELECT plan_tier, count(*) AS merchants,
       count(*) * CASE plan_tier
         WHEN 'starter' THEN 19
         WHEN 'pro' THEN 49
         WHEN 'elite' THEN 149
         ELSE 0 END AS mrr_usd
FROM merchants
WHERE uninstalled_at IS NULL
GROUP BY 1;

-- Gate failures (what's blocking quality)
SELECT payload->>'reason' AS reason, count(*) AS hits
FROM merchant_events
WHERE event_type = 'product.gate_failed'
  AND created_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 2 DESC;
```

---

## 9. Next Iterations (Post-Launch)

Not blockers for v1 — add once you have paying merchants:
- **App Bridge embed** — embed admin UI inside Shopify admin iframe (higher conversion)
- **Merchant-specific Printify keys** — let each merchant connect their own Printify account via OAuth
- **AI product research** — scan a merchant's existing products and suggest gaps/upsells
- **Bulk operations** — generate 50 products at once from a CSV
- **Custom prompts per merchant** — let Elite merchants tune the DALL-E prompt style to match their brand
