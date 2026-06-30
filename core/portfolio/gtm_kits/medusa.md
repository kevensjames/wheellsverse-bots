PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

---

# Medusa Commerce — Go-To-Market Kit

**Offer:** Done-for-you Medusa storefront on a self-hosted instance — catalog import, B2B/wholesale tiered pricing, custom checkout, Stripe, monthly managed plan.
**Price:** $3,500 setup + $450/mo
**Beachhead:** Specialty coffee roasters with retail + wholesale in Portland, OR (10–150 SKUs, $50k–$1M/yr)

---

## 1. Market Brief

### Top 3 pains removed
1. **Bleeding margin on platform fees + apps.** A roaster doing $30k/mo on Shopify is paying a 2.9%+30¢ rate plus a monthly plan, plus a B2B/wholesale app ($60–$300/mo), plus a tiered-pricing app, plus extra-staff-account fees. The "real" Shopify bill is rarely the sticker price. Medusa self-hosted removes the platform tax — you pay Stripe's processing and a flat hosting bill, full stop.
2. **B2B pricing duct-taped on with apps.** Wholesale price lists, per-account tiers, net terms, and "log in to see pricing" are bolted onto Shopify with apps that break on theme updates and don't talk to each other. On Medusa, price lists and customer groups are *native* — wholesale isn't a plugin, it's the data model.
3. **You don't own the thing your business runs on.** Theme code, checkout, customer data, and roadmap all live inside someone else's walled garden. Migrate-out is painful, customization hits a wall, and the rules can change under you. Medusa is your codebase on your infrastructure — open-source core, your database, your repo.

### 2 alternatives the buyer uses now
1. **Shopify (Basic/Shopify/Advanced) + a stack of wholesale/B2B apps** — the default, and the one they're frustrated with.
2. **Shopify Plus** — the "upgrade" Shopify pushes for serious B2B, at ~$2,300+/mo. Sticker shock is the wedge here: most $50k–$1M/yr roasters can't justify Plus, so they stay stuck on the app-duct-tape tier.

*(Honorable mention they may also use: WooCommerce/WordPress — cheaper but a maintenance and security headache, and B2B is still a plugin pile.)*

### The single sharpest wedge
**"You're paying Shopify Plus-level money in fees and apps for B2B features Medusa gives you natively — without the Plus bill, and you'd actually own it."** Lead with the *fee math*, not the tech. The roaster doesn't care about open-source; they care that ~$400/mo is walking out the door for pricing logic they could own outright.

### 3 objections (and the honest answer)
1. **"Self-hosted sounds like a maintenance nightmare — what if it breaks at 2am during a wholesale order?"**
   → That's exactly what the $450/mo managed plan is for: monitoring, backups, updates, and a same-business-day fix SLA. You're not running a server; I am. You get the ownership without the on-call pager.
2. **"Migrating off Shopify will break my SEO / lose my customers / be a six-week ordeal."**
   → Catalog, customers, and URL redirects are imported and mapped 1:1; we keep your URL structure and 301 the rest. You stay live on Shopify until the Medusa store is approved on staging — cutover is a DNS flip, not a gap.
3. **"$3,500 is a lot up front when Shopify is 'just' $X/mo."**
   → The setup pays for itself in roughly 8–9 months on fee savings alone (~$400/mo), and every month after that is margin you keep. We can also show the 3-year number: Shopify-plus-apps vs. Medusa-managed is typically a five-figure swing in your favor.

---

## 2. Service Pack — `build_medusa_demo_pack`

A repeatable package so a solo operator can deliver consistently. The demo pack is what you show a prospect on the 10-min call *before* they pay — a pre-built Portland-roaster demo store seeded with realistic coffee SKUs and live wholesale pricing.

### Components
| # | Component | What it is |
|---|-----------|-----------|
| 1 | **Medusa backend (self-hosted)** | Dockerized Medusa v2 + Postgres + Redis, deployed to a single small VPS (e.g. Hetzner/DigitalOcean) per client. |
| 2 | **Catalog import pipeline** | CSV/Shopify-export → Medusa products, variants (whole bean/ground, 12oz/5lb), collections, images. |
| 3 | **B2B / wholesale module** | Customer groups (Retail / Wholesale / Distributor), native price lists, "log in for wholesale pricing," minimum-order rules, net-terms flag. |
| 4 | **Custom storefront** | Next.js storefront (Medusa starter, themed to the roaster's brand) — PDP, cart, account, wholesale portal. |
| 5 | **Custom checkout + Stripe** | Stripe payments wired, tax + shipping zones, wholesale-vs-retail checkout paths. |
| 6 | **Managed-ops layer** | Monitoring/uptime, automated nightly backups, security + dependency updates, staging→prod deploy flow. |
| 7 | **Demo seed** | The reusable Portland-roaster demo (sample SKUs, a "Café & Wholesale" price tier, fake accounts) used for sales. |

### What the client receives
- A live, branded Medusa store on **their** domain, on a VPS **they** own (handed over, or kept under management).
- Their full catalog imported, plus a working **retail + wholesale** experience day one.
- A **wholesale portal**: approved B2B accounts log in and see tiered/list pricing, place orders, see terms.
- Stripe live and reconciled; tax/shipping configured for OR + their ship-to states.
- The **GitHub repo + infra credentials** (ownership is the whole pitch — they get the keys).
- A **runbook + Loom walkthrough** (add a product, approve a wholesale account, pull an export).
- Under the $450/mo plan: uptime monitoring, nightly backups, monthly updates, and same-business-day support.

### Reused across clients vs. customized per client
| Reused across clients (your IP / leverage) | Customized per client |
|---|---|
| Docker/VPS deploy template + provisioning script | Brand theme (logo, colors, type, homepage) |
| Medusa v2 base config + B2B/wholesale module pattern | Real catalog data + variant structure |
| Catalog importer (CSV/Shopify mapping) | Customer-group tiers + actual wholesale price lists |
| Next.js storefront starter + wholesale-portal components | Domain, DNS, Stripe account, tax/shipping zones |
| Stripe integration scaffold | Net-terms / minimum-order rules per their policy |
| Monitoring + backup + update scripts (managed-ops runbook) | Onboarding Loom + runbook screenshots |
| The Portland-roaster **demo store** (sales asset) | — |

**Operator math:** ~70% of every build is the reused template; the customization is data import, theming, and policy config. That's how one person delivers a $3,500 build in days, not weeks — and how the $450/mo stays profitable at scale.

---

## 3. Outreach Sequence (3-touch, cold email)

> One CTA across all three: **a 10-minute call.** Personalize the bracketed fields. Keep it plain-text, no images, no tracking pixels (deliverability + it's how a peer emails).

### Touch 1 — Day 0
**Subject:** the ~$400/mo Shopify tax on `[Roaster Name]`

> Hi `[First Name]`,
>
> I work with Portland roasters who run both retail and wholesale, and I keep seeing the same thing: most shops your size are paying ~$400/mo to Shopify in platform fees and B2B/wholesale apps — for tiered pricing you could actually own.
>
> I rebuild that exact setup on Medusa (open-source, self-hosted): native wholesale price lists, a real B2B login portal, Stripe — on your own store, not rented.
>
> Worth a 10-minute call to see the fee math on `[Roaster Name]` specifically? I can show a live demo roaster store on the call.
>
> — `[Your Name]`, `[Phone]`
>
> *Not the right time? Reply "no thanks" and I won't follow up.*

### Touch 2 — Day 3
**Subject:** re: the ~$400/mo Shopify tax on `[Roaster Name]`

> Hi `[First Name]`,
>
> Quick follow-up — the part most roasters don't expect: on Medusa, **wholesale pricing isn't an app, it's built in.** Customer groups, price lists, "log in for wholesale pricing," minimum orders — native, so nothing breaks on a theme update.
>
> I have a demo store seeded like a Portland roaster (12oz/5lb, café + wholesale tiers). I'll screen-share it on a 10-minute call and put your numbers next to it.
>
> Open this week or next?
>
> — `[Your Name]`
>
> *Prefer I stop? One word — "stop" — and you're off my list.*

### Touch 3 — Day 7
**Subject:** last one — `[Roaster Name]` owning its store

> Hi `[First Name]`,
>
> I'll leave it here so I'm not cluttering your inbox.
>
> The short version: $3,500 to move `[Roaster Name]` onto a Medusa store you own — catalog imported, retail + wholesale live, Stripe wired — then $450/mo to keep it monitored, backed up, and updated. For most roasters the fee savings cover the build in under a year, and you own the asset after.
>
> If owning your store instead of renting it is on your 2026 list, grab 10 minutes here: `[Booking Link]`.
>
> — `[Your Name]`, `[Phone]`
>
> *No reply and I'll assume the timing's off — won't email again.*

---

## 4. Landing Copy

### Hero
# Own Your Store. Stop Renting It From Shopify.
**Done-for-you Medusa storefronts for specialty roasters who run retail *and* wholesale.** Native B2B pricing, custom checkout, Stripe — on infrastructure you own, not a platform you rent.

`[Book a 10-minute call →]`  ·  *Live demo roaster store on the call.*

---

### The problem
You built a real business — retail walk-ins, wholesale accounts, café partners. But your store is a stack of duct tape:

- Shopify fees + a **B2B app** + a **tiered-pricing app** + extra staff seats — and the bill keeps climbing.
- Wholesale pricing is a plugin that **breaks every theme update.**
- The "fix" Shopify pushes is **Plus at ~$2,300/mo** — money you can't justify.
- And after all that, you **don't own** the code, the checkout, or your roadmap.

You're paying Plus-level money in fees and apps — for features you should just *own.*

---

### The offer
**A Medusa storefront, built for you, that you actually own.**

- **Native wholesale.** Customer groups, price lists, "log in for wholesale pricing," minimum orders — built into the platform, not bolted on.
- **Your catalog, imported.** Whole bean / ground, 12oz / 5lb, collections, images — mapped 1:1 from Shopify with URL redirects so your SEO survives.
- **Custom checkout + Stripe.** Retail and wholesale paths, your tax and shipping zones, real payments.
- **Self-hosted, owned by you.** Your repo, your database, your VPS. Open-source core. No platform tax.
- **Fully managed.** Monitoring, nightly backups, updates, and same-business-day support — so "self-hosted" never means "your problem."

---

### Why trust me
I'm a solo operator who does one thing: move specialty roasters off rented platforms onto Medusa stores they own. No agency overhead, no offshore handoff — you work with the person building it. I keep your old store live until the new one is approved on staging, so cutover is a DNS flip, not a gap. And I run a Portland-roaster demo store I'll walk you through on the first call — you see the real thing before you spend a dollar.

---

### Pricing
**$3,500 setup + $450/mo managed.**

- **Setup ($3,500, one-time):** full build — catalog import, B2B/wholesale config, branded storefront, custom checkout, Stripe, go-live + handover.
- **Managed ($450/mo):** hosting, monitoring, nightly backups, security + dependency updates, and same-business-day support.

For most roasters, **fee savings cover the setup in under a year** — and you own the asset.

`[Book a 10-minute call →]`

---

### FAQ
**Q: Isn't self-hosting risky if something breaks?**
A: That's what the $450/mo plan covers — I monitor it, back it up nightly, and fix issues same business day. You get ownership without running a server.

**Q: Will migrating off Shopify hurt my SEO or lose customers?**
A: No. Catalog, customers, and URLs are mapped 1:1 with 301 redirects, and your Shopify store stays live until the Medusa store is approved on staging. Cutover is a DNS flip — no downtime, no gap.

**Q: Can I edit products and run the store myself?**
A: Yes. You get the Medusa admin, a runbook, and a Loom walkthrough for everyday tasks — add a product, approve a wholesale account, pull an export. Anything bigger, I handle under the managed plan.

**Q: What happens if I ever want to leave?**
A: You already own everything — the repo, the database, the server. There's no lock-in. That's the entire point: it's your store, not mine.

---

### Final CTA
## Stop paying a platform tax on pricing you could own.
Book a 10-minute call. I'll run the fee math on your store and show you the live demo.
`[Book a 10-minute call →]`

---

## 5. Proposal Template

> Single-page proposal. Replace every `{{merge_field}}`. Keep it to one page — owner-operators don't read ten.

---

**PROPOSAL — Medusa Storefront for {{roaster_name}}**
Prepared for: {{contact_first_name}} {{contact_last_name}}, {{roaster_name}}
Prepared by: {{your_name}}, Medusa Commerce
Date: {{date}}  ·  Valid through: {{valid_through_date}}

---

### Outcome
{{roaster_name}} will own a self-hosted Medusa storefront that serves **retail and wholesale from one system** — native tiered pricing, a B2B login portal, custom checkout, and Stripe — replacing the Shopify-plus-apps stack currently costing roughly **{{current_monthly_fees}}/mo**. Target outcome: cut platform/app fees by ~{{estimated_monthly_savings}}/mo and own the asset outright.

### Scope
- Self-hosted Medusa v2 backend (Postgres + Redis) on a dedicated VPS
- Catalog import: {{sku_count}} SKUs / variants from {{current_platform}}, with images + 301 redirects
- B2B/wholesale: customer groups ({{tier_list}}), native price lists, wholesale login portal, minimum-order + net-terms rules
- Branded Next.js storefront ({{brand_colors_note}})
- Custom checkout + Stripe live, tax/shipping for {{ship_to_regions}}
- Handover: repo + infra credentials, runbook, and Loom walkthrough
- **Out of scope (quote separately):** content/photography, third-party integrations beyond {{included_integrations}}, ongoing feature work outside the managed plan

### Timeline
- **Week 1:** kickoff, VPS provision, catalog import, brand theme on staging
- **Week 2:** B2B/wholesale config, checkout + Stripe, your review on staging
- **Week 3:** revisions, redirects, go-live (DNS cutover) + handover
- *Old store stays live until you approve staging — no downtime.*
- Target go-live: **{{target_golive_date}}**

### Investment
- **Setup:** **$3,500** one-time — 50% ($1,750) to start, 50% ($1,750) at go-live
- **Managed plan:** **$450/mo** — hosting, monitoring, nightly backups, updates, same-business-day support (starts at go-live, monthly, cancel anytime with 30 days' notice)
- *Estimated payback on setup from fee savings: ~{{payback_months}} months*

### Guarantee / risk reversal
**You don't go live until you're happy.** Your current store stays running the entire time, so there's no gap and no risk to your sales. If the staging store doesn't meet what's scoped here, I'll keep working at no extra cost until it does — and if we can't get it right, you owe nothing beyond the {{deposit_amount}} deposit. After go-live, the managed plan is month-to-month — no lock-in, ever, because you own everything.

### Next step
Reply **"approved"** or sign below, and I'll send the deposit invoice and a 15-minute kickoff link. We can have {{roaster_name}} live by **{{target_golive_date}}**.

Approved: ______________________  Date: ____________
{{contact_first_name}} {{contact_last_name}}, {{roaster_name}}

---

*Prepared by {{your_name}} · {{your_email}} · {{your_phone}}*

---

*End of kit. Nothing here has been sent, published, or deployed — all drafts for operator review.*