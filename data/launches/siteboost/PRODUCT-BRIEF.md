# SiteBoost AI — Productization Brief

**Author**: Wheellsverse (J.K. Blaze)
**Sub-brand**: SiteBoost AI (separate from Wheellsverse main brand — protects reputation)
**Product type**: Done-for-you website + monthly maintenance
**Audience**: Local US businesses (restaurants, salons, plumbers, electricians, contractors, etc.) without a website

---

## Strategic positioning

### Why a sub-brand, not Wheellsverse-branded

Cold outbound carries a permanent reputation cost — once a few prospects mark "spam," the entire sending domain is poisoned. Splitting the brand:

- **Wheellsverse** = your digital products (NarAI, AI playbooks, KDP books) sold to operators who already know you
- **SiteBoost AI** = local-business outbound brand, separate domain (`hello.wheellsverse.com`), separate email infra

If SiteBoost ever gets reputation damage from cold outbound, it's contained to that sub-brand. Your Wheellsverse Stripe checkout + Shopify reputation stays clean.

### The offer (single SKU, no choice paralysis at top of funnel)

> **$497 one-time. Custom website built in 48 hours. $49/mo to keep it running.**

That's it. No three tiers. No "starter / pro / agency" pricing matrix. The prospect's decision is binary: yes/no.

**Why $497**:
- Below most local-business "I need to think about it" psychological floor (~$1000)
- Above the "this can't be real" floor (~$200) — too cheap = looks fake
- High enough for healthy unit economics: at 95% margin = $472/sale, target CPA $150 = 3:1 ROAS achievable

**Why $49/mo**:
- Aligns recurring revenue with hosting + ongoing tweaks (1-2 small changes/month)
- 10% of sites churn in month 1, 5%/mo after = 14-month average lifetime = $686 LTV from MRR alone
- Total LTV at 14mo: $497 + (14 × $49) = **$1,183 per customer**

### Funnel

```
Cold email + site preview → 5-8% reply rate
Reply → auto-response with Calendly link → 30-40% book a 15-min call
15-min call → 40-60% close on the spot ($497 charged via Stripe link)
Customer → 48h delivery (template + 30min personalization by you/contractor) → live site
Customer → $49/mo Stripe subscription auto-charges
```

**Expected funnel math per 1,000 emails sent**:
- 1,000 emails × 6% reply = 60 replies
- 60 replies × 35% book = 21 calls
- 21 calls × 50% close = **11 sales**
- 11 × $497 = **$5,467 one-time** + 11 × $49 = **$539/mo recurring**

At $1,000-1,500 of monthly outbound infra cost (Instantly + Hunter + domains + Places API), **breakeven at ~3 sales/month, healthy profit at 6+**.

### Pricing strategy — what to charge for what

| Item | Price | Margin | Notes |
|---|---|---|---|
| Standard site | $497 one-time | 95% | Template-driven, 30min human polish |
| Monthly maintenance | $49/mo | 95% | Includes hosting + 1-2 minor tweaks per month |
| Extra page (after launch) | $97 | 95% | Add menu, contact form, gallery, etc. |
| Custom photography | $250 | 50% | Subcontract to local freelancer |
| Logo design | $147 | 80% | Generate via AI + 30min refinement |
| Annual prepay maintenance | $499/yr (vs $588) | 95% | 15% discount → secures cashflow |
| Rush delivery (24h) | $197 add-on | 95% | Pure margin — barely changes the work |

**Average revenue per customer at year 1** with reasonable upsells: $497 + $588 maintenance + $97 (one extra page average) + occasional $250 photography = **~$1,200-1,400** in year-1 revenue. ~$600/yr recurring after year 1.

### Delivery pipeline (what happens when someone says "yes")

1. **T+0min**: Stripe charges $497, webhook fires
2. **T+1min**: Auto-email with intake form (URL of biz, top 3 services, hours, 2-3 photos if they have them)
3. **T+24h after intake**: You spend 30-45 min: polish their preview, add their real content, deploy to their domain
4. **T+48h**: "Your site is live" email with login + admin URL
5. **T+7 days**: Check-in email — "anything you want changed?"
6. **T+30 days**: First $49 charge clears, subscription is locked in

### Geographic strategy (start narrow, expand wide)

**Phase 1 (Month 1-2)**: One city only. Test with 200 prospects in Boston (or your city).
- Easier reply rate (you can mention neighborhood landmarks in copy)
- Tight enough geo that the audience clusters → Andromeda-equivalent for email
- If it works in one city, it works in 50

**Phase 2 (Month 3-4)**: 5 cities. NAI runs autonomous weekly scans, generates 100 sequences/week per city.
- 5 × 100 = 500 sequences/week = ~30 closed sales/month at 6% funnel
- $14,910 one-time + $1,470/mo recurring per month

**Phase 3 (Month 5+)**: Hire 1 part-time site-builder ($25/hr, 10hrs/week = $1k/mo cost) to handle the 30min polish per site. Free your time for sales calls only.

### Risks + mitigations

| Risk | Mitigation |
|---|---|
| Email deliverability collapse (domain blacklisted) | Use Instantly's domain warmup, rotate 3 sending domains, throttle at 50/day/domain |
| Customer expects custom design, gets template | Be explicit in email + intake: "based on a proven layout, personalized for you" — never use "custom design" |
| Negative reviews from buyers ("you used a template!") | Build a portfolio page early: `hello.wheellsverse.com/work` showing 20 happy customers → social proof drowns out 1-2 bad reviews |
| Refund chargebacks | 7-day money-back if site not delivered. After delivery, no refund — Stripe-defensible. |
| Google Places ToS change | Always use the Places API, never scraping the UI. API usage is contractually allowed. |
| GDPR/CAN-SPAM lawsuit | Skip EU entirely (hardcoded in scanner). CAN-SPAM footer hardcoded in every email. Physical address + real sender + unsubscribe required and enforced. |
| Bad-faith competitor copies your sites | Each site is per-customer; even if competitors clone the *templates*, they don't have your prospect data, email pipeline, or sales funnel. The tech is the easy part. |

### What makes this different from existing competitors

Three things, in priority order:

1. **The preview-link in the email IS the demo.** Most cold outbound asks for a meeting first. SiteBoost gives them something to react to. Reply rate ~3-4x higher.

2. **Single SKU.** Most "AI site agencies" have tiered pricing that requires a sales call to figure out. SiteBoost says $497, decide now. Friction-elimination.

3. **48h delivery, mostly automated.** Competitors take 1-3 weeks because they design from scratch. SiteBoost delivers in 48h because the template + personalization is mostly done before the prospect ever pays. The 30min you spend is just polish.

### Anti-positioning (what you DON'T say)

- ❌ "AI-generated site" — sounds spammy, devalues
- ❌ "Built by ChatGPT" — same problem
- ❌ "Custom design" — overpromise, you're using templates
- ❌ "Web design agency" — pulls in price-sensitivity comparisons to $3k Webflow shops

- ✅ "We build your site in 48 hours using a proven layout, then polish it for you"
- ✅ "Trusted by 47 small businesses in [city]" (once true)
- ✅ "Live in 2 days, $497, no agency markup"

### Where this fits in the Wheellsverse stack

This product is *separate* operationally but shares the same operator (you):

- **Lives at**: `hello.wheellsverse.com` (not `wheellsverse.com` subdomain — different brand entity)
- **Stripe account**: same Stripe, separate Product line, separate price IDs
- **Email infra**: SEPARATE outbound domain (Instantly), SEPARATE inbox (Gmail or Helpscout) for replies
- **Marketing**: zero overlap with Wheellsverse marketing — local business prospects are a different ICP
- **Notion delivery**: shared workspace, separate database `SiteBoost Customers` for tracking

**Cross-leverage**:
- NAI runs autonomous weekly scans (already wired in `narai/tools/local_prospect_tool.py`)
- Wheellsverse marketing skills (market-emails, market-copy) can be invoked for any SiteBoost copy iteration
- ConvertKit drip sequences can drop SiteBoost customers into a Wheellsverse newsletter list IF they opt-in during onboarding (cross-sell to AI playbooks later)

### Launch readiness checklist

Required before first send (in order):

- [ ] Register `hello.wheellsverse.com` (or alt — `instantsites.co`, `localsiteboost.com`)
- [ ] Set up Google Workspace email on the new domain: `jay@hello.wheellsverse.com`
- [ ] Configure SPF + DKIM + DMARC on the new domain
- [ ] Sign up Instantly.ai ($30/mo starter) + buy 2-3 sending mailboxes
- [ ] Start domain warmup — **2-4 weeks before first cold email**
- [ ] Google Cloud Platform → Places API enabled + key generated
- [ ] Hunter.io free tier signed up (50 lookups/mo) — upgrade to $49 plan after first test
- [ ] Cloudflare Pages account → connect `preview.hello.wheellsverse.com` for hosting previews
- [ ] Stripe → create new "SiteBoost Site" product at $497, "SiteBoost Monthly" subscription at $49/mo
- [ ] Build intake form (Tally.so or Google Forms, 10 fields max)
- [ ] Build delivery template: Notion page for each customer with checklist
- [ ] Write 3 onboarding emails (welcome, intake reminder day 3, site-live confirmation)
- [ ] Connect Calendly → 15-min slot type for "SiteBoost Discovery"

The 4-week warmup window is the bottleneck. Start that immediately. Everything else parallelizes.

### Realistic revenue projection (Year 1)

| Month | Sales | One-time | MRR (new) | Cumulative MRR |
|---|---|---|---|---|
| 1 (warmup, manual sends) | 2 | $994 | $98 | $98 |
| 2 (Boston only) | 5 | $2,485 | $245 | $343 |
| 3 (Boston + 2 cities) | 11 | $5,467 | $539 | $882 |
| 4 (5 cities) | 22 | $10,934 | $1,078 | $1,960 |
| 5 | 25 | $12,425 | $1,225 | $3,185 |
| 6 | 28 | $13,916 | $1,372 | $4,557 |
| 7-12 (steady-state) | 30/mo × 6 | $89,460 | $8,820 | $13,377 |
| **Year 1 total** | **~155 sales** | **~$135,000** | **~$13,300 MRR** | — |

Y1 gross revenue ~$135k one-time + ~$72k MRR cumulative (avg over year) = **~$207k Y1**. Costs: ~$2k/mo infra + part-time builder ~$12k/yr = ~$36k cost → **~$170k Y1 profit at the upper end**, or ~$100k if reply/close rates run half of optimistic.

These are projections, not promises. Real numbers depend on reply rate (the single biggest lever), close rate, and refund rate. The system this code creates makes those numbers *measurable*, which means iterable.

### Final note

The reason SiteBoost works isn't the code. It's that small US businesses without websites are an enormous, demonstrably under-served market (~5M according to Yelp 2024 data), they all have phone numbers, and they all want websites but most have never been pitched in a way that doesn't feel salesy. The **personalized preview link** kills that objection.

Build the system. Send 200 emails to Boston. Measure what happens. Iterate from there.
