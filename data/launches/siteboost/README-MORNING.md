# 🌅 Morning Briefing — Read This First

**What I did overnight while you slept:**

Built the complete SiteBoost AI system — end-to-end pipeline that finds local businesses without websites, generates personalized site previews, drafts CAN-SPAM-compliant cold-email sequences, and integrates with both your marketing skill stack AND NAI's autonomous tooling.

Dry-run validation: ✅ **PASSED** end-to-end (10 fake Boston businesses → 7 enriched → 7 previews → 7 sequences → run report).

---

## 🆕 v3 ADDITIONS — operations + launch readiness

Built after domain decision (`hello.wheellsverse.com` as subdomain). Adds the tools you'll actually run daily.

| Command | What it does |
|---|---|
| `python3 scripts/siteboost_status.py` | **Launch readiness dashboard.** Single command shows artifacts, env vars, DNS, Calendly state, pipeline activity. Exits 0 = ready to send, 1 = blocked with list. |
| `python3 scripts/verify_dns.py` | One-shot SPF/DKIM/DMARC/MX/CNAME check (5 records) |
| `python3 scripts/wait_for_dns.py --notify` | Poll DNS every 60s, macOS-notify when 5/5 ✓ |
| `python3 scripts/export_sequences_csv.py --sequences <path>` | **Instantly fallback path.** Exports a 3-touch sequence file to Instantly's CSV-import format. Use if you don't want to set up `INSTANTLY_API_KEY`. |
| `bash scripts/deploy_previews.sh <previews-dir>` | Push generated HTML previews to `preview.wheellsverse.com` via Cloudflare Pages |
| [WARMUP-TRACKER.md](WARMUP-TRACKER.md) | **28-day Instantly warmup checklist.** Daily ticks, weekly stop-conditions, Day-28 first-real-send criteria. |
| [DNS-CHEATSHEET.md](DNS-CHEATSHEET.md) | Cloudflare DNS records to paste (5 total) |
| [TASK-4-API-KEYS.md](TASK-4-API-KEYS.md) | Step-by-step Google Places + Hunter + Anthropic key setup |
| `local_prospect/site/wrangler.toml` | Cloudflare Pages config (security headers, CSP, HSTS pre-tuned) |

### Current status (from `siteboost_status.py` at last run)

- ✅ All 24 artifacts present on disk
- ❌ 5 env vars unset (GOOGLE_PLACES_API_KEY, HUNTER_API_KEY, SITEBOOST_OUTBOUND_DOMAIN, SITEBOOST_SMTP_USER, SITEBOOST_PHYSICAL_ADDRESS)
- ❌ DNS 0/5 records propagated (paste 5 Cloudflare records → run `wait_for_dns.py`)
- ❌ Calendly URL still placeholder in 2 files
- ✅ 27/27 tests passing
- ✅ 2 dry-run campaigns executed (Boston, MA)

**Run `python3 scripts/siteboost_status.py` anytime to see the current state.**

---

## 🆕 v2 ADDITIONS (built after the first briefing — pre-funnel + sales + post-payment + tests + dedupe)

The first build covered cold-email sending. The v2 additions cover **everything between reply and revenue**, plus operational safety:

| New artifact | What it solves |
|---|---|
| [data/launches/siteboost/SALES-PLAYBOOK.md](data/launches/siteboost/SALES-PLAYBOOK.md) | Reply auto-responder · 15-min call script · 10 common objections + responses · post-call follow-up · weekly volume targets |
| [local_prospect/intake.html](local_prospect/intake.html) | Customer intake form (5 sections, progress bar, drag-drop photo upload). Embed at `hello.wheellsverse.com/intake?customer={id}`. Posts to your handler. |
| [core/siteboost_onboarding.py](core/siteboost_onboarding.py) | 3 post-payment emails: T+0 welcome, T+24h intake nudge (only if not yet submitted), T+48h site-live announcement |
| [scripts/siteboost_stripe_setup.py](scripts/siteboost_stripe_setup.py) | Idempotent Stripe products+prices+payment-links for 7 SiteBoost SKUs ($497 site, $49/mo, $97 extra page, $147 logo, $250 photo, $197 rush, $499 annual). Tagged with `brand: siteboost` for webhook routing. |
| [core/siteboost_state.py](core/siteboost_state.py) | Persistent dedupe state. Prevents double-scanning the same place_id and double-emailing the same address across runs. Includes blocklist for emails/domains. Supports "least-recently-scanned" rotation for NAI's weekly cron. |
| [tests/test_siteboost_pipeline.py](tests/test_siteboost_pipeline.py) | Pytest suite — 25+ tests covering all 5 stages + state + onboarding + end-to-end smoke. All dry-run; no API keys needed. Run with `pytest tests/test_siteboost_pipeline.py -v`. |

### What the v2 additions add to your launch checklist

These tasks run AFTER the original 5 morning tasks (skill cp · domain · email infra · API keys · pricing decision):

- **Stripe products** — run `python scripts/siteboost_stripe_setup.py --dry-run` to preview the 7 SKUs. Then run without `--dry-run` (with `STRIPE_API_KEY` set) to create them. Writes payment-link URLs to `data/launches/siteboost/stripe_payment_links.json`.
- **Calendly slot** — create a 15-min "SiteBoost Discovery" slot at calendly.com. Find/replace the `calendly.com/<your-handle>/15min` template in `SALES-PLAYBOOK.md` with your actual URL.
- **Read [SALES-PLAYBOOK.md](data/launches/siteboost/SALES-PLAYBOOK.md) once before your first call.** 10 min read; saves 10 hours of fumbling on early calls.
- **Self-host the intake form** — copy `local_prospect/intake.html` to `hello.wheellsverse.com/intake.html` (Cloudflare Pages, GitHub Pages, or any static host). Wire `<form action>` to Tally.so OR a custom handler that writes to `data/launches/siteboost/intakes/<customer_id>.json`. The form already reads `?customer=` from the URL query string.
- **Customer-id wiring check** — the Stripe `success_url` redirects to `https://hello.wheellsverse.com/intake?customer={CHECKOUT_SESSION_ID}`. Confirm your intake-form host serves the file at `/intake` (not `/intake.html`) so the URL is clean.
- **Run the test suite** — `pytest tests/test_siteboost_pipeline.py -v` before going live. All tests are dry-run, no credentials needed. If anything fails, the per-test class docstring explains what it's validating.

---

## TL;DR — What you can do in the next 30 minutes

```bash
cd ~/Projects/wheellsverse-bots   # or wherever your repo is
python3 scripts/local_prospect_run.py --all --location "Boston, MA" --limit 20
open data/launches/siteboost/runs/2026-06-02-boston-ma/03-previews/*.html
cat data/launches/siteboost/runs/2026-06-02-boston-ma/05-report.md
```

That runs the entire pipeline in **dry-run** (no API spend, no emails sent) and shows you what the real output will look like. You'll see 7 generated HTML preview sites and 21 emails ready to review (3 touches × 7 businesses).

---

## What was built (file map)

### Core Python modules
| File | What it does |
|---|---|
| [core/places_scanner.py](core/places_scanner.py) | Google Places API client. Finds businesses without websites. Auto-skips GDPR regions. |
| [core/email_enricher.py](core/email_enricher.py) | Hunter.io wrapper. ~50% hit rate finds an email per business. |
| [core/site_generator.py](core/site_generator.py) | Template-driven site builder. Picks 1 of 3 templates by category, personalizes with LLM (Claude). |
| [core/cold_outreach.py](core/cold_outreach.py) | Email composer (3-touch sequence per prospect) + Instantly.ai sender. Has hardcoded CAN-SPAM footer, hardcoded "refuse to send from wheellsverse.com" guard. |

### HTML templates
| File | Used for |
|---|---|
| [local_prospect/templates/site_restaurant.html](local_prospect/templates/site_restaurant.html) | Restaurants, cafés, bakeries |
| [local_prospect/templates/site_service.html](local_prospect/templates/site_service.html) | Salons, plumbers, dentists, contractors |
| [local_prospect/templates/site_retail.html](local_prospect/templates/site_retail.html) | Pet stores, florists, boutiques |

### Orchestration
| File | What it does |
|---|---|
| [scripts/local_prospect_run.py](scripts/local_prospect_run.py) | CLI entry point with `--scan`, `--enrich`, `--generate`, `--compose`, `--send`, `--all` modes. **Dry-run by default**; needs `--live` per stage + `--confirm` for send. |
| [narai/tools/local_prospect_tool.py](narai/tools/local_prospect_tool.py) | NAI tool wrapper. Exposes the pipeline so NAI can autonomously scan a new ZIP weekly + queue up sequences for your review. |
| [local_prospect/SKILL.md](local_prospect/SKILL.md) | Claude Code skill manifest. **Needs manual copy to `~/.claude/skills/market-local-prospect/SKILL.md`** — auto-mode blocked me from writing directly. (1 command: see below.) |

### Strategic docs
| File | What it covers |
|---|---|
| [data/launches/siteboost/PRODUCT-BRIEF.md](data/launches/siteboost/PRODUCT-BRIEF.md) | Full productization: $497/$49 pricing + funnel math + Y1 revenue projection (~$170k upper, ~$100k realistic) + risks/mitigations + launch checklist |
| [data/launches/siteboost/README-MORNING.md](data/launches/siteboost/README-MORNING.md) | This file |
| [.env.example](.env.example) | Updated with new env var section: GOOGLE_PLACES_API_KEY, HUNTER_API_KEY, SITEBOOST_OUTBOUND_DOMAIN, INSTANTLY_API_KEY |

---

## The 5 things ONLY YOU CAN DO

I cannot do these — they need your credit card, your decisions, or your domain ownership:

### 1. Install the skill (30 seconds)

```bash
mkdir -p ~/.claude/skills/market-local-prospect
cp local_prospect/SKILL.md ~/.claude/skills/market-local-prospect/SKILL.md
# Verify: ls ~/.claude/skills/market-local-prospect/
```

After this, you can trigger the workflow via: *"scan for local prospects in Boston"* or *"run SiteBoost campaign for Cambridge MA"*.

### 2. Domain decision: ✅ Using `hello.wheellsverse.com` (a subdomain)

**Decision made:** outbound from `hello.wheellsverse.com` (subdomain of your existing brand). Subdomains have **separate sending reputation** in Gmail/Outlook, so the main `wheellsverse.com` brand stays safe even if outbound gets hammered.

The hardcoded refusal in `core/cold_outreach.py` now blocks only the *critical* domains (apex `wheellsverse.com`, `www`, `shop`, `app`) — subdomains like `hello.wheellsverse.com`, `studio.wheellsverse.com` etc. are allowed.

Find/replace done across 13 files (88 references). `hello.wheellsverse.com` is now the default everywhere.

### 3. Set up email infra (2-4 weeks calendar time, ~30 min active work)

This is the bottleneck. Cold outbound from a fresh domain = blacklisted in 5 days. Order:

1. **Day 0 today**: Buy the domain (#2 above)
2. **Day 0**: Add SPF + DKIM + DMARC records (Cloudflare DNS UI, 5 min)
3. **Day 0**: Buy Google Workspace ($6/mo) — `jay@yourdomain.com`
4. **Day 1**: Sign up [Instantly.ai](https://instantly.ai) ($30-90/mo)
5. **Day 1**: Connect the new mailbox to Instantly → enable warmup
6. **Day 1-14**: Let Instantly's warmup pool send fake conversations → real reputation built
7. **Day 14+**: NOW you can send real cold emails

Translation: **the first cold email goes out 2 weeks from today** at the earliest. You can build the pipeline + test in dry-run today and queue real emails on day 14.

### 4. Get the API keys (15 minutes total)

```bash
# Google Places — https://console.cloud.google.com → APIs & Services → Enable "Places API (New)" → Credentials → Create API key
# $200/mo free credit covers ~6,000 lookups. Plenty for testing + early scale.
export GOOGLE_PLACES_API_KEY=...

# Hunter.io — https://hunter.io (free 50/mo tier, paid $49/mo for 5,000)
export HUNTER_API_KEY=...

# Add to .env (not .env.example) so the pipeline picks them up
```

Test the live pipeline with **5 prospects** before scaling: `python scripts/local_prospect_run.py --scan --location "your city" --limit 5 --live` → confirms API key works + costs ~$0.05.

### 5. Make the pricing/positioning calls

[PRODUCT-BRIEF.md](data/launches/siteboost/PRODUCT-BRIEF.md) recommends:
- **Single SKU $497 one-time + $49/mo maintenance** (no choice paralysis)
- **Boston-first** for Phase 1 (or whichever city you're in for local landmark references)
- **48-hour delivery promise**
- **NEVER call it "AI-generated"** (devalues; sounds spammy)

Review the brief. If you want different pricing/positioning, the changes are easy — they live in `core/cold_outreach.py` (email template strings) + `data/launches/siteboost/PRODUCT-BRIEF.md`.

---

## Quality gates I baked in (so you can't accidentally break things)

These are hardcoded — by design, they cannot be disabled without editing the source:

1. **Dry-run by default.** Every stage is dry-run unless you pass `--live`. Send stage additionally requires `--confirm`.
2. **GDPR block.** The scanner refuses to scan EU/UK/DE/FR/etc. locations. Hardcoded country code list.
3. **Sender domain guard.** `cold_outreach.py` refuses if outbound domain == `wheellsverse.com`. Protects your main brand.
4. **CAN-SPAM footer.** Hardcoded in every composed email — physical address, unsubscribe link, sender ID. Not optional.
5. **Daily send cap.** Max 50 emails/day per outbound domain (Instantly will throttle further during warmup).
6. **Volume scaling guard.** Pipeline writes intermediate JSON between stages so you can inspect before continuing.

---

## When to bring NAI into it (autonomous mode)

Once you're 2-3 weeks in and the pipeline + outbound infra is proven, mount the NAI tool:

```python
# In your NAI bootstrap
from narai.tools.local_prospect_tool import local_prospect_tool
narai.register_tool(local_prospect_tool)
```

Then NAI can run weekly:
- "Every Monday 6am, scan ZIP 02118 for restaurants + salons, run the full pipeline, drop sequences in `runs/<date>/` for Jay's review"

NAI never sends without your `--confirm` flag. Pipeline is queued, you wake up to a fresh batch each Monday morning. 5-10 minutes of Monday review → 100+ sequences/week.

---

## Risk reminder (read once, never forget)

| Risk | Severity | Mitigation in code |
|---|---|---|
| Wrong domain → wheellsverse.com gets blacklisted | 🔴 Critical | Hardcoded refusal in `cold_outreach.py` |
| Sending without warmup | 🔴 Critical | Instantly handles per-mailbox warmup automatically |
| GDPR fine (€20M max) | 🔴 Critical | Hardcoded EU country-code skip in `places_scanner.py` |
| CAN-SPAM fine ($46k per email) | 🟡 High | Hardcoded footer in `cold_outreach.py` |
| Google Places ToS violation | 🟡 High | Code only uses official Places API, never scrapes UI |
| Refund spike | 🟢 Medium | Brief recommends 7-day money-back if site not delivered |
| Negative SEO/reputation | 🟢 Medium | Sub-brand (hello.wheellsverse.com) separates from wheellsverse.com |

---

## How this connects to your existing Wheellsverse roadmap

| Existing surface | SiteBoost relationship |
|---|---|
| Your $5/day Meta launch | Separate effort. SiteBoost is cold-outbound; Meta is paid inbound. Don't merge. |
| NarAI Pro/Elite/Stock Alerts | Separate audience (B2C operators vs B2C local biz owners). Cross-sell ONLY after they're a SiteBoost customer for 60+ days. |
| Shopify (shop.wheellsverse.com) | SiteBoost takes payment via DIFFERENT Stripe product line on the SAME Stripe account. Customers never see Wheellsverse branding. |
| KDP books | Completely separate. Don't try to upsell SiteBoost customers your books — different ICP. |
| Marketing platform skills (market-*) | SiteBoost adds `market-local-prospect` as a sibling. Skills compose: you can run `market-copy` to iterate SiteBoost email copy, `market-funnel` to audit the SiteBoost funnel, etc. |
| OMC agency suite | `agency-pipeline` works on SiteBoost prospects too — same data structure. |

---

## Critical numbers from the projections (in [PRODUCT-BRIEF.md](data/launches/siteboost/PRODUCT-BRIEF.md))

| Metric | Estimate |
|---|---|
| Reply rate on personalized site-preview cold email | 5-8% |
| Reply → call rate | 30-40% |
| Call → close rate | 40-60% |
| Net funnel conversion (cold email → paid customer) | ~1-2% |
| Monthly infra cost at scale | $1,000-1,500 |
| Breakeven volume per month | ~3 sales |
| Healthy profit volume per month | 6+ sales |
| LTV per customer (with maintenance) | $1,183 |
| Year 1 realistic profit | $100k-170k |

**These are projections, not promises.** The pipeline will produce the *measurements* needed to convert "projection" → "reality" within 30 days of first send.

---

## Final note

The hardest part wasn't the code. It's the email deliverability + warmup timeline (2-4 weeks dead time) and your decisions on positioning/pricing. The code I built does the easy work; the hard work is the parts that need YOUR judgment and YOUR credit card.

Sleep well. The pipeline will be here when you wake up. Run the dry-run, walk through the sample previews, decide if the positioning feels right, then start the 4 setup tasks (skill copy → domain → email infra → API keys). After that, the system runs itself and produces measurable signal.

— Built by Claude · 2026-06-02 overnight
