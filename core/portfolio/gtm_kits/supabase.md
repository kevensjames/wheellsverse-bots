PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

# Supabase SaaS Factory — Complete GTM Kit

**Offer:** Done-for-you white-label tenant & owner portal on Supabase — branded auth, maintenance-request intake with realtime status, document storage, owner reporting. Fully managed.
**Price:** $1,500 setup + $300/mo
**Buyer:** Owner-operators of independent residential property-management firms (80–600 units) running on spreadsheets.
**Niche:** Property management companies in Phoenix, Arizona.

---

## 1. Market Brief

### Top 3 pains removed
1. **The phone/email tar pit.** A spreadsheet shop fields the same questions all day — "Did you get my maintenance request?", "When's the plumber coming?", "Where's my owner statement?" The portal turns those repeat interruptions into self-serve status checks, so the owner-operator stops being a human help desk.
2. **No single source of truth.** Maintenance requests live in texts, voicemails, and inbox threads; nothing is tracked or timestamped. A request falls through, a tenant gets angry, an owner hears about it. The portal gives every request a status, a history, and an audit trail.
3. **Owner trust gap at renewal time.** Independent firms lose owner accounts to bigger competitors that "have a portal." A branded owner-reporting view (statements, docs, request activity for their units) makes a 200-unit shop look as buttoned-up as a national franchise — without franchise overhead.

### 2 alternatives the buyer uses now
1. **Spreadsheets + email + a shared phone line** (the status quo). Free, familiar, and the source of every pain above.
2. **All-in-one PM software** (AppFolio, Buildium, DoorLoop, Rentvine). Powerful but a forklift change: per-unit pricing that stings at scale, months of migration, accounting they're not ready to rip out, and a generic login screen that carries the vendor's brand — not theirs. Many owner-operators have looked, balked at the switching cost, and stayed on spreadsheets.

### The single sharpest wedge
**A branded portal in ~2 weeks that bolts onto how they already work — not a system they have to migrate into.** The competition's whole pitch is "move everything onto us." Ours is "keep your spreadsheets and your accountant; we'll just give your tenants and owners a professional front door with your logo on it, for a fraction of per-unit pricing, live in two weeks." Wedge, not platform.

### 3 objections (with the answer)
1. *"Why not just buy AppFolio/Buildium?"* — Those replace your whole operation and charge per unit forever; at 300 units that's a five-figure annual commitment plus a months-long migration. We're a focused front door — tenant/owner portal only — that works alongside your current process. Flat $300/mo, live in two weeks, your branding.
2. *"I'm not technical / I don't have a developer."* — That's the entire point. It's done-for-you and fully managed. You send me your logo, colors, and a tenant/owner list; I stand it up, you review, we go live. You never touch Supabase, hosting, or code.
3. *"What if I outgrow it or want to leave?"* — It's your Supabase project and your data; export anytime, no lock-in. If you later move to a full PM platform, you leave with clean structured records — better off than the spreadsheets you started with.

---

## 2. Service Pack — `build_portal_pack`

### Components (what gets built)
1. **Branded auth** — logo, color palette, custom domain (e.g., `portal.theirfirm.com`), separate tenant and owner login roles. Supabase Auth + Row-Level Security so tenants see only their unit; owners see only their properties.
2. **Maintenance-request intake + realtime status** — tenant submits a request (category, description, photo upload); it lands in a queue with a live status (`Submitted → Acknowledged → Scheduled → In Progress → Resolved`). Tenant sees status update in realtime; no "did you get it?" calls.
3. **Document storage** — leases, notices, inspection reports, owner statements; per-role access via Supabase Storage + RLS. Tenants get their docs, owners get theirs.
4. **Owner reporting** — a per-owner view of their units: open/closed maintenance activity, uploaded statements/documents, and basic occupancy/request summaries. Read-only, clean, branded.
5. **Admin console (operator + client)** — the firm's staff triage requests, change statuses, upload documents, and add/remove tenants and owners.

### What the client receives
- A live, branded portal at their own subdomain (tenant + owner logins).
- A 1-page admin how-to (triage a request, upload a doc, add a user) + a 15-minute Loom walkthrough.
- A welcome email template they can send tenants/owners to drive first login.
- **Managed hosting, monitoring, backups, and updates** under the $300/mo — they never touch infrastructure.
- Their own Supabase project and exportable data (no lock-in).

### Reused-across-clients vs customized-per-client
| Reused across every client (my "factory") | Customized per client |
|---|---|
| Supabase schema (units, tenants, owners, requests, documents, roles) | Logo, color palette, brand name |
| RLS policy set (tenant/owner/admin isolation) | Custom subdomain + auth screens |
| Maintenance-request state machine + realtime wiring | Initial tenant/owner/unit data load |
| Document storage buckets + access rules | Document categories/labels to match their workflow |
| Owner-reporting view templates | Welcome-email copy with their voice |
| Admin console UI | Optional: a couple of bespoke status labels |

The schema, RLS, state machine, and UI are a **template I clone per client** — that's why setup is ~2 weeks and the margin holds at $300/mo. Per-client work is branding, domain, and the data load, not rebuilding the system.

---

## 3. Outreach Sequence (3-touch: Day 0 / 3 / 7)

> One CTA throughout: a **10-minute call**. Each email carries a one-line opt-out. From the hook: *"I build branded tenant/owner portals for PM firms your size that cut the email/phone back-and-forth."*

### Touch 1 — Day 0
**Subject:** A branded portal for {{company_name}}'s tenants — no developer needed
**Subject (alt):** {{first_name}} — cut the maintenance-request back-and-forth?

Hi {{first_name}},

I build branded tenant and owner portals for Phoenix property-management firms your size — the kind that cut the daily email and phone back-and-forth about maintenance requests and statements.

For a firm around {{unit_count}} units still tracking requests in spreadsheets and texts, it means tenants check their own request status, owners pull their own documents, and you stop being the help desk. It carries {{company_name}}'s branding — not some software vendor's — and goes live in about two weeks. No developer, no migration; it works alongside how you run things today.

Worth a quick look? I can show you a working demo in **10 minutes** — does Tuesday or Thursday afternoon work?

Best,
{{your_name}}
{{your_phone}} · {{your_calendar_link}}

*Not the right fit? Reply "no thanks" and I won't follow up.*

---

### Touch 2 — Day 3
**Subject:** Re: A branded portal for {{company_name}}'s tenants
**Subject (alt):** The "did you get my request?" calls

Hi {{first_name}},

Following up briefly. The pattern I see most with spreadsheet-run firms your size: it's not any single big problem — it's the steady drip of "did you get my request?" and "where's my statement?" calls that eat the day.

The portal kills that drip. Tenant submits a request, watches the status move in realtime; owners log in for their own docs and activity. Your brand on it, live in ~two weeks, $1,500 to set up and $300/mo fully managed — no per-unit pricing.

Still happy to walk you through a live demo in **10 minutes**. What does your week look like?

Best,
{{your_name}}
{{your_calendar_link}}

*If this isn't for you, just reply "stop" and you won't hear from me again.*

---

### Touch 3 — Day 7
**Subject:** Last note, {{first_name}} — closing the loop
**Subject (alt):** Should I close your file?

Hi {{first_name}},

I'll stop here so I'm not cluttering your inbox.

If giving {{company_name}}'s tenants and owners a branded, self-serve portal — without hiring a developer or migrating off your spreadsheets — is worth 10 minutes this month, grab a time here: {{your_calendar_link}}. If the timing's just off, tell me when to circle back and I will.

Either way, I appreciate you reading.

Best,
{{your_name}}
{{your_phone}} · {{your_calendar_link}}

*Prefer I drop it entirely? Reply "remove" and I'll close your file for good.*

---

## 4. Landing Copy

### Hero
# Give Your Tenants and Owners a Branded Portal — Without Hiring a Developer
**Subhead:** A self-serve tenant and owner portal — your logo, your domain — that cuts the maintenance-request phone tag and the "where's my statement?" emails. Built on Supabase, fully managed, live in about two weeks.
**[Book a 10-minute demo]** · *No migration. Keep your spreadsheets and your accountant.*

### The problem
You run 80–600 units out of spreadsheets, texts, and a shared inbox — and it works, until it doesn't. Maintenance requests get buried in threads. Tenants call to ask if you got the one they sent yesterday. Owners email for statements you've already sent. And when an owner shops a competitor with a slick portal, your spreadsheet-run firm suddenly looks small. The all-in-one platforms want to replace your whole operation and charge you per unit to do it. You don't need a forklift. You need a front door.

### The offer
**Supabase SaaS Factory builds you that front door — done-for-you and fully managed.**
- **Branded auth** — your logo, colors, and domain; separate secure logins for tenants and owners.
- **Maintenance requests with realtime status** — tenants submit and watch progress (`Submitted → Scheduled → Resolved`) without calling you.
- **Document storage** — leases, notices, statements; each tenant and owner sees only what's theirs.
- **Owner reporting** — owners log in for a clean, branded view of their units' activity and documents.
- **Fully managed** — hosting, backups, monitoring, and updates handled. You never touch code or infrastructure.

### Why trust me
I'm a solo builder who does one thing well: branded portals for independent Phoenix PM firms. You work directly with the person building it — no account managers, no offshore handoff. It's built on Supabase, the same battle-tested platform thousands of production apps run on, and it's **your** project and **your** data — exportable anytime, zero lock-in. You send me a logo and a tenant list; I do the rest.

### Pricing
**$1,500 one-time setup + $300/month, fully managed.**
Flat rate — **not** per-unit. A 500-unit firm pays the same $300/mo as a 100-unit firm. No migration fees, no surprise tiers. Setup is a single project; the monthly covers hosting, backups, monitoring, support, and updates.
**[Book a 10-minute demo]**

### FAQ
**Q: Do I have to move off my spreadsheets or change my accounting?**
No. The portal is a front door for tenants and owners — it runs alongside how you work today. Keep your spreadsheets and your accountant.

**Q: How long until it's live?**
About two weeks from when you send your branding and your tenant/owner list. You review a staging version before anything goes public.

**Q: What if I want to leave or outgrow it?**
It's your Supabase project and your data — export anytime, no lock-in. You're never trapped, and you leave with clean structured records.

**Q: I'm not technical. Is this really hands-off?**
Yes. It's done-for-you and fully managed. You'll get a 1-page guide and a short walkthrough for the day-to-day (triaging requests, uploading docs), and I handle everything technical.

### Closing CTA
**Stop being the help desk. Give your tenants and owners a portal with your name on it.**
**[Book a 10-minute demo]** — see a working version live, then decide.

---

## 5. Proposal Template

> Replace every `{{merge_field}}` before sending.

---

**PORTAL BUILD PROPOSAL**
Prepared for **{{client_first_name}} {{client_last_name}}**, {{company_name}}
Prepared by {{your_name}} · {{your_email}} · {{your_phone}}
Date: {{proposal_date}} · Valid through: {{valid_through_date}}

### Outcome
Within **{{timeline_weeks}} weeks**, {{company_name}} will have a live, branded tenant-and-owner portal at **{{portal_subdomain}}**. Your tenants will submit and track maintenance requests without calling your office; your owners will log in for their own documents and unit activity; and your {{unit_count}}-unit firm will present like a national operation — while you keep your existing spreadsheets and accounting untouched. Target result: a measurable drop in repeat "did you get it / where is it" calls and emails within the first 30 days of tenant adoption.

### Scope
**Included (`build_portal_pack`):**
1. Branded auth — your logo, colors, and {{portal_subdomain}}; separate tenant and owner logins.
2. Maintenance-request intake with realtime status tracking and tenant photo uploads.
3. Document storage with per-role access (tenants and owners each see only what's theirs).
4. Owner-reporting view — per-owner unit activity and documents.
5. Admin console for your staff to triage requests, manage documents, and add/remove users.
6. Initial data load of up to {{initial_user_count}} tenants/owners and {{unit_count}} units.
7. 1-page admin guide + 15-minute walkthrough video.

**Not included (available on request):** full accounting/rent-ledger system, online rent payments, native mobile apps, integrations with {{existing_software}}. *(Scope additions quoted separately.)*

### Timeline
- **Week 1:** Kickoff, branding + domain setup, data load, staging portal stood up.
- **Week 2:** Your review on staging, revisions, go-live, and walkthrough.
- Ongoing: fully managed — hosting, backups, monitoring, updates.

### Investment
- **One-time setup: $1,500** (due at kickoff to reserve your build slot).
- **Managed service: $300/month** (begins at go-live; covers hosting, backups, monitoring, support, and updates).
- **Flat rate — not per-unit.** No migration fees. Month-to-month; cancel anytime with 30 days' notice.

### Guarantee / Risk reversal
**Go-live or you don't pay the monthly.** You review the portal on staging before it's public. If it isn't live and working to the scope above within **{{timeline_weeks}} weeks** of receiving your branding and data, you pay **$0 in monthly fees until it is**. And because it's **your** Supabase project and **your** data — exportable anytime — you're never locked in. The risk of trying this is close to zero.

### Next step
1. Reply **"approved"** to this email, or sign here: {{signature_link}}.
2. Pay the **$1,500** setup to reserve your slot: {{payment_link}}.
3. Send your logo, color preferences, desired subdomain, and tenant/owner/unit list to {{your_email}}.

I'll have your staging portal ready for review within **{{staging_eta_days}} days** of receiving those.

Questions first? Grab 10 minutes: {{your_calendar_link}}.

— {{your_name}}