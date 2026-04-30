#!/usr/bin/env bash
# Commit the overnight session work in 5 logical batches.
#
# Run from repo root:
#   bash scripts/commit_overnight_batches.sh
#
# Each batch leaves the staging area clean before the next; if any batch fails
# (Opsera gate, hook error, etc.) the script stops so you can fix and resume.
#
# After running, the only remaining dirty files should be:
#   - 14 core/ files + 29 bots/ files + 8 frontend/blog/ files for the
#     Robinhood→Webull migration (batch #6 — your decision)
#   - Runtime data (data/, narai/data/) — gitignored as appropriate
#   - A handful of new files I left out intentionally (review with `git status`)
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Make sure nothing is staged that we don't want
git reset > /dev/null

run_commit() {
  local title="$1"; local body="$2"; shift 2
  echo "═══════════════════════════════════════════════════════════════"
  echo "▶ $title"
  echo "═══════════════════════════════════════════════════════════════"
  git add -- "$@"
  git status --short | head -20
  git commit -m "$title" -m "$body" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  echo
}

# ── Batch 1: affiliate registry expansion ───────────────────────────────────
run_commit \
  "feat(affiliates): expand /go partner registry to 20 programs" \
"Adds webull, m1finance, public, doordash, uber, cashapp, onepay,
capitalone, creditone, amazon_prime/kindle/audible/music/fresh/kids/
business/photos/halo/rx/gaming/pets/wedding, convertkit, jasper,
bluehost, fiverr, clickbank, appsumo, shareasale, partnerstack, cj
to core.click_tracker._affiliate_urls(). Updates affiliate keyword
rules in core.monetization to match.

Without this commit, /go/<slug> for any of these partners returns 404
in production." \
  core/click_tracker.py core/monetization.py

# ── Batch 2: TG private-group subscription end-to-end ───────────────────────
run_commit \
  "feat(insider): TG private-group subscription end-to-end" \
"Stripe-paid subscription gates access to a private Telegram channel.
Built on the existing NarAI Telegram bot + /api/stripe/webhook.

  • core/api.py — webhook dispatch + /subscribe/* + /insider routes
                  + new public-route allowlist entries
  • narai/integrations/telegram_subscription.py — SQLite state machine
  • narai/integrations/telegram.py — /start <token> deep-link branch
  • narai/integrations/scheduler_promo.py — APScheduler cron, fires
        weekly promo + daily morning briefing + midday signals + Sun review
  • narai/integrations/subscriber_content.py — assemblers using the
        existing forecaster + yfinance for watchlist content
  • narai/api/routes/telegram_subscription.py — /api/v2/.../checkout
  • narai/api/routes/insider_admin.py — lead capture + admin endpoints
  • frontend/pricing.html — Insider tier card + JS
  • frontend/insider.html — focused landing + lead-capture form
  • frontend/subscribe_success.html — XSS-safe deep-link redirect
  • frontend/subscribe_cancelled.html
  • frontend/blog/latest-in-crypto-news.html — fix /go/webullg1 404

Tests: 18 new (12 subscription state machine + 6 admin auth/lead capture);
also adds tests/test_bots_smoke.py (144 bots) and
tests/test_affiliate_slugs.py (CI guard catching unregistered /go slugs).

Setup: see narai/integrations/TG_PRIVATE_GROUP_SETUP.md." \
  core/api.py \
  narai/integrations/telegram_subscription.py \
  narai/integrations/telegram.py \
  narai/integrations/scheduler_promo.py \
  narai/integrations/subscriber_content.py \
  narai/integrations/__init__.py \
  narai/integrations/TG_PRIVATE_GROUP_SETUP.md \
  narai/api/routes/telegram.py \
  narai/api/routes/telegram_subscription.py \
  narai/api/routes/insider_admin.py \
  narai/tests/test_telegram.py \
  narai/tests/test_telegram_subscription.py \
  narai/tests/test_insider_admin.py \
  frontend/pricing.html \
  frontend/insider.html \
  frontend/subscribe_success.html \
  frontend/subscribe_cancelled.html \
  frontend/blog/latest-in-crypto-news.html \
  tests/test_bots_smoke.py \
  tests/test_affiliate_slugs.py \
  scripts/setup_stripe_test_mode.py \
  .gitignore .env.example

# ── Batch 3: KDP launch automation ──────────────────────────────────────────
run_commit \
  "feat(kdp): paperback launch automation modules + scripts" \
"core/kdp_launch.py and core/kdp_paperback.py — programmatic helpers
for the daily KDP publishing flow. The accompanying scripts in
scripts/ wire them into a launchd-friendly cron." \
  core/kdp_launch.py core/kdp_paperback.py \
  scripts/build_prompt_bible_pdf.py \
  scripts/com.wheellsverse.kdp.daily.plist \
  scripts/daily_kdp_publish.py \
  scripts/fix_all_descriptions.py \
  scripts/fix_kdp_titles.py \
  scripts/fix_remaining_titles.py \
  scripts/upload_books_to_kdp.py \
  scripts/generate_app_store_assets.py

# ── Batch 4: Shopify store setup + delivery ─────────────────────────────────
# Only commit if these files exist and have content; otherwise skip.
if [[ -s core/store_setup.py && -s core/store_delivery.py ]]; then
  run_commit \
    "feat(store): Shopify store setup + delivery helpers" \
"core/store_setup.py — programmatic store creation / configuration.
core/store_delivery.py — order delivery automation.
shopify.app.toml — Shopify CLI config." \
    core/store_setup.py core/store_delivery.py shopify.app.toml
fi

# ── Batch 5: Sentry init ────────────────────────────────────────────────────
if [[ -s core/sentry_init.py ]]; then
  run_commit \
    "feat(observability): Sentry hook init module" \
"core/sentry_init.py — initializes Sentry SDK with the SENTRY_DSN env
var. Wire into core.api startup if you want production error tracking." \
    core/sentry_init.py
fi

echo "═══════════════════════════════════════════════════════════════"
echo "✅ Done. Remaining work (your decisions):"
echo "═══════════════════════════════════════════════════════════════"
echo
echo "  • Robinhood → Webull migration (14 core/ + 29 bots/ + 8 blogs)"
echo "    See OVERNIGHT_DIRTY_AUDIT.md → 'Decide' section"
echo
echo "  • Other dirty files (run \`git status\` to inspect)"
echo
echo "Next: \`railway up\` to deploy when you're ready."
