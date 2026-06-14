# WheellsVerse Marketing Distribution — Global Plan v1

**Operator:** Kevens James (J.K. Blaze)
**Last revised:** 2026-06-14
**Scope:** all marketing + distribution surfaces (Toodle, SiteBoost, KDP, DS24, Stan, BigCommerce, Shopify, NarAI/KAI, social, content)
**Time horizon:** 90 days

---

## TL;DR — the one-screen version

You built a Ferrari engine with full bodywork and four wheels. You haven't driven it yet. Every distribution surface — Meta funnel, cold outbound, 9 social clients, 5 product channels — is waiting for the same thing: **proven inflow at the top of ONE funnel.**

**Plan A (chosen):** Drive 80% of effort to **Toodle → KDP** for 30 days. Prove $5/day Meta → $50/day. Layer Pinterest + X organic to amplify. SiteBoost runs as parallel B2B track with 7 prospects already prepped. Defer DS24, Stan, BigCommerce, Shopify, TikTok, YouTube, LinkedIn organic until one funnel hits.

**Don't:** Run five funnels in parallel. Your attention is the constraint, not your infrastructure.

---

## 1. Inventory — what you've actually built

### Code surface (~40 marketing modules in `core/`)
- **ESPs / capture:** `kit.py` (v4), `convertkit.py` (v3 legacy), `email_capture.py`, `email_funnel.py`, `lead_capture.py`, `toodle_dispatcher.py`
- **Paid:** `meta_ads.py` (HTTP + SDK runner), Stripe (`stripe_*`)
- **Cold outbound:** `cold_outreach.py` (SiteBoost backbone)
- **Social:** `facebook.py`, `instagram.py`, `tiktok.py`, `twitter.py`, `linkedin.py`, `pinterest.py`, `threads.py`, `telegram.py`, `whatsapp.py`
- **Products:** `kdp_*` (5 modules), `stan_*`, `shopify_*`, `narai_shopify_*`
- **Content:** `content_calendar.py`, `repurpose.py`, `seo.py`, `shorts_pipeline.py`

### Bots (~70 in `bots/`)
Most "affiliate" bots repurposed during the 2026-05-26 affiliate→owned-product cleanup (550 URLs removed, 18 bots refit).

### Product channels live
| Channel | Status | Inventory |
|---|---|---|
| KDP (Amazon) | Live | Night Parliament + others |
| DS24 | Live | 19 products, $1.3K cap, 9 masterclasses @ $97 |
| Stan.store | Live | 41 bundles |
| BigCommerce | Live | 10-product catalog |
| Shopify | Integrated | Agent workforce in flight |
| NarAI / KAI | Sales page live | SaaS service |

### Funnels built
1. **Toodle** — Meta → Blueprint PDF → Kit nurture → KDP book (pipe verified; ad PAUSED)
2. **SiteBoost** — Local SMB cold email → site preview → agency sale (7 Fall River prospects launch-ready)
3. **NarAI direct** — Sales page + signup/login/pricing wired
4. **Stan / DS24 direct** — Landing pages exist, no inflow proven

### Marketing playbooks (`marketing/`)
12 .md files: KDP nurture, Welcome, Long-tail, ad brief, abandoned cart, launch email, social drop, Meta App Review packet, MailerLite migration plan, AI Entrepreneur Blueprint source, this doc.

### Lead magnet
**AI Entrepreneur Blueprint** PDF — live at https://wheellsverse-bots.pages.dev/blueprint.pdf (verified 200, application/pdf, 4.85 MB)

---

## 2. The core thesis (sanity-checked against build choices)

You are a **one-person multi-product operator**. The 2026-05-26 affiliate cleanup signaled a deliberate strategic pivot:

> **From** earning a margin on someone else's products (affiliate)
> **To** owning the customer + the product + the margin (WheellsVerse stack)

That decision shapes everything below. Every channel choice is "does this drive owned audience to owned product?"

---

## 3. Diagnosis — what's working / idle / broken / unproven

| Status | Item | Note |
|---|---|---|
| ✓ Working | Toodle capture → Kit → SMTP → blueprint delivery | Real test emails landed in inbox; subscriber `4145058365` created |
| ✓ Working | SiteBoost 5-stage pipeline | Scan → preview → compose → send via Instantly v2 |
| ✓ Working | Blueprint PDF | Cloudflare Pages, 4.85MB, served correctly |
| ✓ Working | KDP launch automation | Multiple titles published with truth-verify gates |
| ⏸ Idle | Meta ad | PAUSED, blocked on Phase A click or App Review approval |
| ⏸ Idle | 9 social platform clients | No content calendar driver firing them |
| ⏸ Idle | 30+ repurposed bots | Refit for owned-product workflows, but doing what? |
| ❌ Broken | Cross-channel attribution | Every channel writes to its own silo — no unified view |
| ❌ Broken | Two-daemon split | :5051 prod vs :5052 Toodle — technical debt |
| ❓ Unproven | KDP organic traffic without paid | Books published; no sales velocity data shared yet |
| ❓ Unproven | Stan / DS24 / BigCommerce conversion | Catalogs live; inflow not proven |
| ❓ Unproven | NarAI / KAI subscriber rate | Page live; signups not surfaced in any dashboard |

---

## 4. The decision framework

A channel earns priority only if it scores well on three axes:

1. **Time-to-revenue** — how many days from "decide" to "first dollar"
2. **Compounding** — does effort decay (paid ads) or accumulate (SEO, owned list)
3. **Operator fit** — can ONE person sustain it without burning out

**Score (0=avoid, 5=hero):**

| Channel | Time | Compound | Op fit | Total |
|---|---|---|---|---|
| Toodle (Meta ad → KDP) | 5 | 2 | 4 | **11** |
| Email (Kit + SMTP) | 5 | 5 | 5 | **15** |
| Pinterest | 3 | 5 | 4 | **12** |
| X organic | 3 | 4 | 3 | **10** |
| IG Reels | 3 | 2 | 3 | **8** |
| SEO blog | 1 | 5 | 4 | **10** |
| SiteBoost cold email | 4 | 3 | 4 | **11** |
| TikTok organic | 2 | 2 | 2 | **6** |
| YouTube organic | 1 | 5 | 2 | **8** |
| LinkedIn organic | 2 | 3 | 3 | **8** |
| TikTok / FB paid | 4 | 1 | 2 | **7** |
| Telegram / WhatsApp broadcast (owned) | 5 | 4 | 5 | **14** |

**Top 5 by score:** Email (15), Telegram/WA (14), Pinterest (12), Toodle Meta (11), SiteBoost (11).

**Action: bet on the top 5. Defer the bottom 7 until one of the top 5 prints daily revenue.**

---

## 5. The plan — concentrate, prove, then diversify

### Phase 1 — Twin tips of the spear (next 7 days)

**Two parallel tracks, no others:**

#### Track 1: Toodle → KDP (consumer)
- **Day 1:** Click through Path A in Ads Manager UI ([marketing/META_ADS_MANUAL_FINISH.md](META_ADS_MANUAL_FINISH.md)). Reuse PAUSED campaign `120249191226470279` + adset `120249191226830279`. Toggle to Active. ~60 seconds.
- **Day 1–2:** Submit App Review per [marketing/META_APP_REVIEW_SUBMISSION.md](META_APP_REVIEW_SUBMISSION.md). 3–7 day review clock starts.
- **Day 1–7:** Monitor opt-ins via `GET /toodle/status` (auth required). Record daily: spend, opt-ins, CPL, email opens, blueprint clicks, attributed Amazon book sales.
- **Stop condition:** if CPL > $5 after 5 days at $5/day spend, the creative or the offer is wrong — not the funnel. Iterate the creative (Higgsfield, new angle), not the plumbing.

#### Track 2: SiteBoost → Local SMB (B2B)
- **Day 1:** Send the 7 Fall River prospects already prepped. Use the live pipeline.
- **Day 2–7:** Track replies. One reply = qualified-call attempt.
- **Stop condition:** if 0/7 reply by day 5, the email template is wrong or the offer is wrong. Iterate copy, NOT the pipeline.

### Phase 2 — Repurposing engine (days 8–21)
- **Build the Repurpose Agent** (designed in the original strategy doc, not yet built):
  - 1 blueprint chapter → 5 quote cards + 1 carousel + 1 Reel script + 1 Pinterest pin
  - Source: `marketing/ai_entrepreneur_blueprint.md` and KDP book chapters
- **Wire to TOP 3 social channels only** (per scoring): Pinterest, X, IG Reels.
  - **Pinterest first** — best score, evergreen, ranks for years
  - **X second** — compounds via follower count
  - **IG Reels third** — best free reach right now, but algo-dependent
- **Every post → CTA to blueprint.pdf** (same lead magnet, no fragmentation)

### Phase 3 — Funnel #2 (days 22–45)
**Only after Phase 1 prints daily revenue:**
- Pick ONE additional product as funnel #2 — likely Stan bundles (highest existing inventory)
- Build a second lead magnet specific to that audience (NOT the same Blueprint — different problem, different offer)
- Same pipeline: paid inflow → email nurture → product purchase

### Phase 4 — Diversify into back-end (days 46+)
- DS24, BigCommerce, Shopify, NarAI as **back-end up-sells** to Toodle subscribers
- They are NOT separate funnels — they are products the existing audience buys later
- One-email upgrade flow per product

---

## 6. The missing piece — Unified Attribution Dashboard

Currently you write to Kit, KDP, BigCommerce, Stan, DS24, Shopify in isolation. You **cannot answer** "what did $5 of Meta spend generate this week?" because the data lives in five silos.

### Build (Phase 1 ride-along, max 2 hours):
```
narai/api/routes/attribution.py
  POST /attribution/event  body: {ts, source_utm, action, value_cents, product, channel}
  GET  /attribution/dashboard?days=7   summary: spend, leads, conversions, revenue, ROI per channel
```

Every Toodle capture, every Stripe webhook, every KDP purchase webhook (when available) writes one row. The dashboard surfaces ROI per channel daily.

**Without this you're flying blind for the rest of the plan.**

---

## 7. The "stop doing" list

These exist in code but should be **deliberately PAUSED** until Phase 4:

- ❌ TikTok organic posting
- ❌ YouTube organic posting
- ❌ LinkedIn organic posting
- ❌ Threads cross-posting
- ❌ Paid ads on TikTok, FB-with-different-objective, Google
- ❌ KDP Amazon-internal ads
- ❌ New product creation on Stan, DS24, BigCommerce
- ❌ "More content" without a defined distribution channel

Every minute spent on one of these in Phase 1–3 is a minute not spent on the top 5.

---

## 8. KPIs — what to measure daily

Three numbers on a Post-it next to your monitor:

1. **Yesterday's Toodle opt-ins**  (target: ≥3/day at $5/day spend = CPL ≤ $1.67)
2. **Yesterday's SiteBoost replies**  (target: ≥1/week from 7 prospects = ~14% reply rate)
3. **Yesterday's revenue, attributed**  (Kit subs × LTV estimate; Stripe direct; KDP sales)

Weekly review (Sunday, 30 min):
- Channel-level CAC and LTV trajectory
- Which content piece performed best (basis for Phase 2 repurpose)
- Decisions for next week

---

## 9. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Meta ad disapproved on review | Phase 2 (organic Pinterest + X) starts ASAP regardless |
| Kit account limit (1000 subs on free) | MailerLite migration plan ready in `marketing/MIGRATE_FROM_KIT_TO_MAILERLITE.md`; switch at 800 |
| Gmail SMTP daily cap (~500) | Workspace upgrade at $6/mo if daily volume passes 300 |
| Blueprint PDF feels stale after 90 days | Refresh creative + offer angle in Phase 4 |
| Solo founder burnout | Phase 1 is 80% of effort on ONE thing — by design |
| Toodle daemon on :5052 dies | Cron + Login Item respawn pattern (memory: established) |
| Cloudflare Tunnel URL changes on reboot | Long-term: named tunnel post App-Review approval |

---

## 10. Three questions only the operator can answer

1. **Revenue target.** What's the number that decides "Phase 1 succeeded"? $100/day? $1K/day? Without it, "focus" has no edge.
2. **The hero product.** Pick one: KDP books / Stan bundles / DS24 courses / NarAI subscription / SiteBoost agency. Everything else becomes back-end. Currently all five compete for your attention.
3. **Operator hours/day on marketing.** 4? 8? 12? Decides Phase 2 / 3 pacing.

Until those three are answered, this plan executes Phase 1 on autopilot but Phases 2–4 stay theoretical.

---

## 11. First-7-days action sequence (literal)

```text
Day 1 (today)
  Morning  – Path A click in Ads Manager (60s). Ad goes Active.
  Morning  – Send 7 SiteBoost prospects. Mark them in CRM.
  Morning  – Decide Q1 (revenue target) + Q2 (hero product) above.
  Afternoon – Submit Meta App Review (Phase B packet).
  Evening  – Build attribution.py route (2 hrs).

Day 2
  Check Toodle opt-ins (was ad approved by Meta? Did it serve?).
  Check SiteBoost replies. Reply within 1 hour to any.
  Stand up attribution dashboard endpoint.

Day 3–5
  Daily KPI check (3 numbers).
  If Meta ad serving, expand budget +$2/day each successful day (max $20/day).
  If SiteBoost reply → demo call → propose.

Day 6
  Half-day Repurpose Agent design + first prototype.
  Pick the FIRST blueprint chapter to repurpose.

Day 7
  First 5 social posts go out (Pinterest, X, IG Reels), 1 each from 5 quote cards.
  Weekly review: continue, iterate, or pivot.
```

---

## 12. Alternatives considered but not chosen

**Plan B — Five funnels in parallel.** Rejected: attention split across 5 funnels means none hits scale. One-person constraint.

**Plan C — Cold outbound first (SiteBoost only).** Rejected: SiteBoost is included in Phase 1 Track 2 anyway. Toodle gives consumer-side reach Toodle uniquely solves.

**Plan D — Pure organic, no paid ads.** Rejected: organic takes 3–6 months to compound. Paid is the fastest validation loop.

**Plan E — Pause everything, rebuild attribution first.** Tempting but slow. Attribution gets built in Phase 1 as ride-along. The funnels don't wait.

---

## 13. Document maintenance

This doc revises every 14 days. Sections that drift:
- §1 inventory (channels added/retired)
- §3 diagnosis (status changes)
- §5 phase timing (slips happen)
- §11 action sequence (next 7-day window)

When Phase 1 hits its revenue target, this doc moves to v2 with a different Phase 1 focus.
