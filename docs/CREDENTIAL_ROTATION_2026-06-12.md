# Credential Rotation Checklist — 2026-06-12

`.env` holds **97 secret-bearing keys**, exposed in chat history → treat all as
compromised. Rotate by blast radius (top tier first). **Names only here — never
paste values into chat/docs/git.** `.env` is gitignored; keep it that way.

**Process for each:** (1) rotate/regenerate at the provider console below →
(2) paste the NEW value into `.env` → (3) when done, restart the daemon
(`launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai`) → (4) verify
`/docs` 200 + Audit tab. Tick the box as you go.

> Note: many keys (everything after the WORDPRESS_TOKEN line ~246) don't reach
> the KAI daemon (the `.env` landmine), but the legacy bots read `.env`
> directly — rotate them if those bots still run.

---

## 🔴 TIER 1 — IMMEDIATE (account takeover / live money / values shown verbatim in chat)

**Account passwords (plaintext in `.env` — a leaked password = full takeover; change AND enable 2FA):**
- [ ] `KDP_PASSWORD` (+ `KDP_EMAIL`) → Amazon account → change password + **enable 2FA** (account.amazon.com → Login & Security)
- [ ] `EMAIL_PASSWORD` → it's a Gmail **App Password** → myaccount.google.com/apppasswords → revoke "WheellsVerse" + create new; confirm 2FA on the Google account
- [ ] `TWITTER_PASSWORD` → x.com → Settings → change password + 2FA
- [ ] `FACEBOOK_PASSWORD` / `INSTAGRAM_PASSWORD` / `LINKEDIN_PASSWORD` → change + 2FA on each platform

**Live money:**
- [ ] `STRIPE_SECRET_KEY` (it's `rk_live_…` — LIVE) + `STRIPE_WEBHOOK_SECRET` → dashboard.stripe.com → Developers → API keys (roll the restricted key) + Webhooks (roll signing secret)

**Billable LLM keys (values shown):**
- [ ] `OPENAI_API_KEY` → platform.openai.com/api-keys (revoke + create)
- [ ] `ANTHROPIC_API_KEY` → console.anthropic.com → Settings → API Keys

---

## 🟠 TIER 2 — HIGH (commerce/publishing/social API creds; values shown early in chat)

- [ ] `GUMROAD_ACCESS_TOKEN` / `GUMROAD_APP_ID` / `GUMROAD_APP_SECRET` → app.gumroad.com/settings/advanced
- [ ] `PAYHIP_API_KEY` → payhip.com/settings (API)
- [ ] `ETSY_KEYSTRING` / `ETSY_SHARED_SECRET` / `ETSY_ACCESS_TOKEN` / `ETSY_REFRESH_TOKEN` → etsy.com/developers → your app
- [ ] `IMPACT_ACCOUNT_SID` / `IMPACT_API_PASSWORD` → impact.com → API settings
- [ ] `CANVA_CLIENT_ID` / `CANVA_CLIENT_SECRET` → canva.com/developers → your app
- [ ] `TWITTER_API_KEY` / `TWITTER_API_SECRET` / `TWITTER_BEARER_TOKEN` / `TWITTER_ACCESS_TOKEN` / `TWITTER_ACCESS_SECRET` → developer.x.com → app → regenerate keys + tokens

---

## 🟡 TIER 3 — MEDIUM (other integration tokens — rotate at each provider)

- [ ] **Shopify**: `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` / `SHOPIFY_ACCESS_TOKEN` / `SHOPIFY_ACCESS_TOKEN_SECONDARY` → Shopify admin → Apps/dev
- [ ] **BigCommerce**: `BIGCOMMERCE_*` (CLIENT_ID/SECRET/ACCESS_TOKEN/STORE_* /STORE_HASH) → BC dev portal
- [ ] **Whop**: `WHOP_API_KEY` / `WHOP_APP_ID`
- [ ] **Google OAuth**: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_PLACES_API_KEY` / `YOUTUBE_CLIENT_SECRET_FILE` → console.cloud.google.com → Credentials
- [ ] **Meta family**: `META_APP_ID` / `META_APP_SECRET` / `FACEBOOK_PAGE_TOKEN` / `INSTAGRAM_PAGE_TOKEN` / `SHOP_FACEBOOK_PAGE_TOKEN` / `SHOP_INSTAGRAM_PAGE_TOKEN` / `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_VERIFY_TOKEN` / `THREADS_ACCESS_TOKEN` → developers.facebook.com → app
- [ ] **LinkedIn**: `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` / `LINKEDIN_ACCESS_TOKEN`
- [ ] **Pinterest**: `PINTEREST_APP_ID` / `PINTEREST_APP_SECRET` / `PINTEREST_ACCESS_TOKEN`
- [ ] **TikTok**: `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` / `TIKTOK_ACCESS_TOKEN` / `TIKTOK_REFRESH_TOKEN`
- [ ] **Notion**: `NOTION_TOKEN` → notion.so/my-integrations
- [ ] **Telegram**: `TELEGRAM_BOT_TOKEN` (+ `TELEGRAM_WEBHOOK_SECRET`) → @BotFather → /revoke (NB: KAI alerts use this — update + restart after)
- [ ] **Discord**: `DISCORD_BOT_TOKEN` / `DISCORD_PUBLIC_KEY` → discord.com/developers
- [ ] **Cloudflare**: `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_AI_TOKEN` / `CLOUDFLARE_INFRA_TOKEN` → dash.cloudflare.com → My Profile → API Tokens
- [ ] **Supabase**: `SUPABASE_API_TOKEN` → supabase.com → Account → Access Tokens (NB: distinct from the DB creds in `backend/.env`)
- [ ] **Media/AI**: `ELEVENLABS_API_KEY` / `HEYGEN_API_KEY` / `RUNWAYML_API_KEY` / `PIKA_API_KEY` / `LEONARDO_API_KEY`
- [ ] **Email/leads**: `RESEND_API_KEY` / `HUNTER_API_KEY` / `CONVERTKIT_API_KEY` / `CONVERTKIT_API_SECRET`
- [ ] **Publishing/stores**: `MEDIUM_TOKEN` / `GHOST_ADMIN_KEY` / `WORDPRESS_TOKEN` / `WORDPRESS_APP_PASSWORD` / `WORDPRESS_APP_PASS` / `WOOCOMMERCE_CONSUMER_KEY` / `WOOCOMMERCE_CONSUMER_SECRET` / `TEACHABLE_API_KEY` / `THINKIFIC_API_KEY`
- [ ] **Print-on-demand**: `PRINTFUL_API_KEY` / `PRINTIFY_API_KEY`
- [ ] **Composio**: `COMPOSIO_API_KEY`

---

## 🔵 TIER 4 — INTERNAL SECRETS (you generate these — rotate carefully)

These are app-internal; rotating means generating a new random value + updating `.env`:
- [ ] `NARAI_JWT_SECRET` → ⚠️ rotating **logs out every NarAI user** (invalidates all JWTs). Expected; do it deliberately.
- [ ] `NARAI_STORAGE_KEY` (encryption key — ⚠️ if it decrypts stored data, rotating may orphan that data; check before rotating)
- [ ] `NARAI_PASSWORD_HASH` (your NarAI login — re-hash a new password)
- [ ] `STORE_DOWNLOAD_SECRET`, `ADMIN_TOKEN` (dashboard token — rotating means re-entering it in the dashboard)
- [ ] `API_KEY` (generic — identify what it's for before rotating)

---

## After rotating
1. Update each NEW value in `.env` (keep it gitignored; no `.env.bak` left on disk).
2. `launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai` → verify `/docs` 200 + Audit tab (9/9, 0 issues).
3. Consider a secrets manager going forward — the repo already has a `wvkey` AES-256-GCM vault tool (`tools/wvkey/`) per project memory; migrating `.env` into it would stop plaintext sprawl.
4. **Prevention:** never paste `.env` contents into a chat — share names, not values.
