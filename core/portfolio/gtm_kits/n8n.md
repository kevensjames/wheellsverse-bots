PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

# n8n Automation Agency — Go-To-Market Kit
### Lead-to-Booking Engine for Scottsdale Med Spas

**Offer:** $1,500 setup + $400/mo managed · **Buyer:** Owner-operator, 1–3 location med spa, $40k–150k/mo, non-technical, leaking leads to slow response.

---

## 1. Market Brief

Scottsdale is one of the most concentrated, affluent, tourist-fed med spa markets in the US — a wellness hub where demand is high but so is competition. That cuts both ways for your offer: the prospect is *already getting leads* (so the problem is purely conversion, not demand-gen — easier to fix and easier to attribute), and they're losing those leads to a competitor two miles away who answered first. The pain is "I'm paying for leads and a rival is closing them," not "I need more leads." That's the most fixable, fastest-ROI problem a med spa has, which is exactly why this offer is the right one for this market.

**The math (well-documented):** only **7% of businesses respond to a new lead within 5 minutes**, while responding in 5 min makes you **21x more likely to qualify** the lead and the **first responder wins ~78% of deals** (MIT/HBR/Velocify). For a med spa specifically, **52% of callers abandon after 3 minutes on hold**, only **20–30% of missed callers call back**, and **~79% have skipped booking entirely because it was too hard to reach someone**. At a $500–700 average ticket and 30–50% inquiry-to-book rate, even **3 missed calls/day ≈ $130k+/yr lost**. A six-figure leak plugged for $4,800/yr — a trivially easy ROI story.

### Top 3 pains this offer removes
1. **Speed-to-lead leak** — the new inquiry that goes cold before anyone replies. Form/DM comes in at 7pm while the injector is with a client; by morning the prospect has booked the competitor who texted back in 60 seconds. Headline pain, cleanest provable ROI.
2. **The missed/after-hours call that never calls back** — evenings and Sundays are peak research time and the spa is closed or short-staffed. 70–80% of those callers don't try again. Missed-call text-back converts a dead call into a live text thread automatically.
3. **No-shows and the unasked-for review** — empty chairs from no-shows (reminders cut these 30–50%) and a thin/stale Google profile in a market where prospects comparison-shop on reviews. Reminders + post-visit review requests recover booked revenue and compound local ranking.

### The 2 alternatives the buyer uses today
1. **Manual front desk + their booking software's basic reminders (the real status quo).** Receptionist calls leads back "when she gets a minute"; baked-in PMS reminders (Boulevard, Aesthetics Pro, Vagaro). *Feels* covered — your biggest competitor — but has no speed-to-lead, no missed-call capture, no review loop, and the leak leaves no record so the owner never sees it.
2. **A GoHighLevel-style DIY platform or a generic marketing agency.** GHL ($97–497/mo, ships empty) or a "marketing guy" who set up a half-configured automation and disappeared. Proper setup is 60+ hours of A2P 10DLC, workflow, and intake config — **most DIY owners quit within 30 days.** The alternative is known to fail for exactly the reason you exist.

### The single sharpest wedge to lead with
**"You're already paying for these leads. A med spa two miles away is closing them because they reply in 60 seconds and you reply tomorrow — and you can't even see it happening."**

Lead with **speed-to-lead instant reply** as the spearhead (not the full 4-part stack). Make it concrete in the first 60 seconds: *send a fake inquiry to their own web form / call their main line after hours in front of them and let the silence do the selling.* That live demo of their own leak is the entire close. The other three modules are the "and it also does this" that justifies the retainer.

### The 3 objections to expect
1. **"My front desk / booking software already handles this."** → Those tools react *after* someone reaches you; they do nothing for the lead who never got through or the form that sits overnight. Counter with the live demo (their own un-answered after-hours call) + the no-trace point. Position as a layer *on top of* their booking system, not a replacement.
2. **"$1,500 + $400/mo is a lot / I could get GoHighLevel for $97."** → Anchor against the leak, not the software: $4,800/yr vs. a documented $130k+/yr loss. The $97 tool is the *empty* version — "you'd be buying the 60 hours of setup nobody at your front desk has time for, which is why DIY owners quit in 30 days." Done-for-you + managed is the value.
3. **"Is texting patients compliant? / Will this feel spammy?"** (acute in a premium, medical-adjacent market) → Address HIPAA-friendliness, A2P 10DLC handled-for-them, and brand-matched copy proactively. Stress it's reply-to-an-inbound-inquiry (consented, expected) not cold blasting, tuned to their luxury positioning.

**One-line positioning:** *Done-for-you speed-to-lead that plugs a six-figure, invisible leak in a market where the lead is already paid for and the only question is who replies first.*

**Sources:** [MIT/HBR speed-to-lead](https://caseyresponse.com/blog/lead-response-time-statistics) · [Velocify / first-responder](https://verse.ai/blog/speed-to-lead-statistics) · [Zenoti spa abandonment](https://www.zenoti.com/thecheckin/salon-spa-booking-communication-trends) · [Med spa missed-call revenue loss](https://blog.salescaptain.com/how-to-reduce-missed-calls-for-medspa-2025-guide/) · [Spa Voices missed calls](https://spavoices.com/missed-calls-in-medical-spas/) · [GHL DIY-fails / agency pricing](https://netpartners.marketing/gohighlevel-agency-pricing-guide/) · [Scottsdale med spa density](https://www.buoyhealth.com/providers/Medical%20Spa/AZ/Scottsdale) · [No-show reduction 30–50%](https://leadspheres.com/crm/for-service-businesses/for-med-spas/)

---

## 2. Service Pack — `build_workflow_pack`

**Deliverable type:** Productized done-for-you service. Self-hosted n8n + Twilio + booking system. One reusable engine, thin per-client config layer. Buildable and operable by a solo operator.

### A. The n8n Workflow Pack (the core IP — built once, reused everywhere)

| # | Workflow | Trigger | Action |
|---|----------|---------|--------|
| 1 | **Speed-to-Lead** | New lead webhook (web form / FB/IG Lead Ad / Google LSA) | Instant SMS + email reply <60s, then 5-touch follow-up cadence until reply or booking |
| 2 | **Missed-Call Text-Back** | Twilio inbound call → no answer / voicemail | Auto-SMS "Sorry we missed you — text us back or book here [link]" within 1–2 min |
| 3 | **No-Show / Recovery** | Booking status = no-show OR appointment-time elapsed without check-in | SMS/email re-book sequence + optional "we held your spot" offer |
| 4 | **5-Star Review Request** | Booking status = completed (+ delay window) | SMS/email review ask; happy → Google review link, unhappy → private feedback (review-gating-aware) |
| 5 | **Reminder + Confirmation** (the glue that *prevents* no-shows) | Appointment booked / 24h + 2h pre-appt | Confirmation + reminders with reply-to-confirm (feeds Workflow 3) |

**Shared sub-components reused across all five:**
- **Master config node** (one `Set` node per client: business name, hours, timezone, booking URL, Google review URL, Twilio number, brand tokens) — the *only* thing that changes per client.
- **Quiet-hours / TCPA-compliance guard** (no SMS outside allowed hours; STOP/opt-out handling; consent check).
- **Lead/contact upsert + dedupe** to the datastore.
- **Conversation state machine** (stops a sequence the moment the lead replies or books).
- **Error/dead-letter handler** → operator alert (so a solo operator isn't blind to failures).
- **Centralized message-template library** (variables, not hardcoded copy).

### B. Messaging Content Pack
- ~25–30 pre-written SMS/email templates per scenario, med-spa-toned, merge-field driven. Reused as defaults; lightly customized per client (name, offer, voice).
- Compliance footer block (STOP to opt out, business identity) — reused as-is.

### C. Integration Connectors
- Twilio (SMS + inbound call/voicemail webhook) — reused.
- Booking system adapter — **the main per-client variable.** Pack ships **2–3 prebuilt adapters** (Vagaro, Boulevard, Mangomint, Acuity, Square Appointments, etc.); a new system is a one-time build that then *becomes* reusable.
- Email sender (Postmark/SendGrid/SMTP) — reused.
- Lead-source intakes (web form, Meta Lead Ads, Google) — reused, mapped per client.

### D. Infrastructure (self-hosted, one stack, multi-tenant by config)
- Dockerized n8n + Postgres + Caddy/Traefik (TLS), backups, on one VPS the operator owns. **One stack hosts many clients**; each client = workflows + config node + isolated credentials.
- Credential vault entries per client (Twilio, booking, email) — isolated, never shared.
- Health-check + uptime monitor + nightly DB/workflow-export backup.

### E. Client-Facing Assets (what they receive)
- Working engine live in production, their number texting their leads.
- Onboarding intake form (collects per-client config).
- 1-page "How it works" + weekly automated summary (leads contacted, missed-calls recovered, no-shows re-booked, reviews requested/landed) — n8n-generated → email/Slack/PDF, reused across all clients.
- Loom walkthrough + short SOP ("what to do when a lead replies / books").
- Opt-out & compliance one-pager for the client to acknowledge.

### Reused vs. Customized (the leverage map)

| Layer | Reused across all clients | Customized per client |
|-------|---------------------------|------------------------|
| 5 workflow templates | ✅ entire logic | — |
| Shared sub-components (compliance guard, state machine, dedupe, error handler) | ✅ | — |
| Message templates | ✅ as defaults | ✏️ name/offer/voice tweaks |
| Twilio / email connectors | ✅ | 🔑 credentials only |
| Booking adapter | ✅ if same system | 🔧 build once per *new* system |
| Config node (`Set`) | structure reused | ✏️ all values (the per-client soul) |
| Infra stack | ✅ one VPS, multi-tenant | 🔑 isolated creds + number |
| Reporting + onboarding form + SOPs | ✅ | ✏️ branding swap |

**The economic point:** ~90% of every build is template instantiation + config. The only genuinely custom work is (a) the per-client config values and (b) a booking adapter *the first time* a new booking system appears — after which it joins the reusable library.

### Two-Part Commercial Structure
**Setup build (one-time):** onboarding intake + access collection → provision number / 10DLC registration → instantiate 5 workflows + config node → connect booking adapter → end-to-end test (fake lead, missed call, no-show, completed appt) → go-live + walkthrough.

**Monthly managed retainer (recurring):** hosting, uptime monitoring, backups · Twilio/10DLC + deliverability management · template/offer tweaks + seasonal campaigns · monthly performance report + 1 optimization touch · compliance upkeep (opt-out list, carrier changes) · "it broke, I fix it" SLA — the real reason the retainer sticks.

### Solo-Operator Buildability Notes
- Build the 5 templates + shared sub-components **once** as a master n8n project, then clone+configure per client (no per-client engineering).
- One VPS, multi-tenant by config — don't spin a new server per client.
- Constrain booking-system support to 2–3 systems at launch to cap adapter sprawl.
- Compliance is non-negotiable and reusable — build the TCPA/quiet-hours/opt-out guard once, into every workflow; highest-liability area, so it must be a shared, audited component.
- Reporting must be automated, or the retainer eats your margin in manual reporting time.

**Single-sentence definition for the proposal:** *A self-hosted n8n engine of five interlocking automations (speed-to-lead, missed-call text-back, no-show recovery, review requests, and confirmation/reminders) wired to the med spa's booking system and Twilio — delivered as a configured, live, compliance-guarded production system, then kept running and tuned under a monthly managed retainer.*

---

## 3. Outreach Sequence

### Email 1
**Subject:** I filled out your contact form Tuesday at 2pm

Hi [First Name],

I filled out your med spa's contact form Tuesday at 2pm asking about Botox pricing — and never heard back.

I'm not writing to complain. I'm writing because it's probably costing you bookings. Most med spa leads go cold within an hour, and the first place to reply usually wins the appointment. When the form sits unanswered, that lead just fills out the next spa's form too.

I built a simple flow that auto-replies to every form fill in under 60 seconds — texts the lead back, answers the common first question, and offers a booking link before they move on. No new software for your front desk to learn.

Worth a 10-minute call to see if it'd fit your spa?

[Your Name]
[Phone]

*Not a fit? Reply "no" and I'll leave it there.*

### Email 2
**Subject:** Re: I filled out your contact form Tuesday at 2pm

Hi [First Name],

Quick follow-up on my note from a few days ago.

Here's the part that's easy to miss: the lead who fills out your form at 2pm is often comparing two or three spas at once. By the time someone calls them back the next morning, they've usually already booked elsewhere. It's not a marketing problem — the lead was already interested. It's a timing problem.

The 60-second auto-reply closes that gap automatically, day or night, without adding anything to your team's plate.

Can I grab 10 minutes this week to show you how it'd work for your spa?

[Your Name]
[Phone]

*Want me to stop? Just reply "no" — no hard feelings.*

### Email 3
**Subject:** Closing the loop

Hi [First Name],

I'll keep this short since I've reached out a couple of times.

If slow lead response isn't on your radar right now, no problem — I'll close the file. But if you've ever wondered how many form fills never turn into appointments, that's usually where the money is leaking, and it's a quick fix.

The offer stands: a 10-minute call, and I'll show you exactly how the auto-reply books leads before they ghost. Here's my calendar — [link].

If now's not the time, just reply "no" and I won't follow up again.

[Your Name]
[Phone]

---

## 4. Landing Copy

# Stop Losing Botox Bookings to Slow Replies — Every Lead Texted Back in 60 Seconds

### Hero
**Every Botox lead you don't text back in 5 minutes is a lead your competitor down the street just booked.**

Your front desk is busy. Your injectors are with clients. And the lead who just filled out your form? They're already messaging the next med spa on their list.

We install a done-for-you system on your booking software that texts and emails every new lead back in under 60 seconds — automatically, 24/7 — so you stop bleeding bookings to whoever answers first.

**[Book My Free Lead-Leak Audit →]**
*No tech work on your end. Live in 7 days.*

### The Problem: You're Not Losing Leads. You're Losing the Race.
You spend real money to make the phone ring — ads, referrals, your reputation. Then a new lead comes in at 7:42pm, your front desk is gone for the day, and they sit untouched until 10am tomorrow. By then, it's over.

- **78% of customers buy from the business that responds first** — not the cheapest, not the best-reviewed. The fastest.
- A 5-minute reply makes you up to **21x more likely to qualify the lead** than waiting 30 minutes.
- Every **missed call** is a $400–$1,200 booking that just dialed your competitor instead.
- Every **no-show** is an empty chair you already paid to fill.
- And every happy client who *didn't* leave a review is a 5-star you'll never get back.

You don't have a marketing problem. You have a *response-time* problem — and it's quietly costing you five figures a month.

### The Offer: Your Done-For-You Lead-to-Booking Engine
We build and run a complete speed-to-lead system on **self-hosted n8n**, wired directly into your booking software and Twilio. You don't touch a thing. Here's what it does the moment it goes live:

**⚡ Speed-to-Lead Instant Reply** — Every new lead (site, ads, or forms) gets a personal SMS *and* email within 60 seconds, day or night. You're first in line, every time.

**📞 Missed-Call Text-Back** — The second a call goes unanswered, the caller gets an automatic text: *"Hi, sorry we missed you! Were you looking to book? Reply here and we'll get you in."* No missed call ever goes cold again.

**🔁 No-Show Recovery** — Automated reminders before the appointment, and instant re-booking outreach the moment someone ghosts — turning empty chairs back into paid treatments.

**⭐ 5-Star Review Requests** — After every visit, the system asks happy clients for a Google review at the perfect moment — building the reputation that wins your next 100 leads.

All of it runs on **your own self-hosted n8n instance** — your data, your automations, no per-lead fees, no platform lock-in.

### Why Trust Us
- **Built for med spas, not "small business" in general.** We speak Botox, filler, memberships, and no-show culture.
- **You own the engine.** Self-hosted n8n means the system is yours. No $1,000/mo SaaS rental, no platform hostage.
- **We do the work — all of it.** You don't log into n8n, build a flow, or troubleshoot Twilio. We build it, run it, keep it humming.
- **Live in 7 days.** No 3-month "implementation." We plug into your existing booking system and Twilio and you're capturing leads next week.

### Pricing
**The Lead-to-Booking Engine** — **$1,500 setup** + **$400/month managed**
- Full done-for-you build on self-hosted n8n
- All four systems: speed-to-lead, missed-call text-back, no-show recovery, review requests
- Wired into your booking software + Twilio · Live in 7 days
- Ongoing monitoring, optimization, and support — we keep it running so you never think about it

*One booked treatment a month more than covers the retainer. Most clients recover the setup fee in the first two weeks.*

**[Book My Free Lead-Leak Audit →]**

### FAQ
**Do I need to be technical or learn n8n?** No. You never log in, never build a flow, never touch a setting. We handle the build, integration, and day-to-day management. You just watch the booked appointments come in.

**Will this work with my current booking system?** Almost certainly. We integrate with the major med spa booking and CRM platforms and connect through Twilio for texting. On your free audit, we'll confirm your exact setup before you pay a dollar.

**Is this just another chatbot or mass-texting app?** No. This is a custom automation engine built on your own self-hosted n8n — not a rented SaaS that charges per lead and owns your data. The messages are personal, well-timed, and fully yours.

**How fast until I see results?** Live within 7 days, texting leads back in 60 seconds from day one. Most clients see recovered missed calls and faster bookings in the first week — often before the first invoice is even due.

### Final CTA
**You already paid for these leads. Stop letting them walk.**

Every day without speed-to-lead is bookings handed to the med spa that replies faster. We'll show you exactly how many leads you're leaking — and how much it's costing you — for free.

**[Book My Free Lead-Leak Audit →]**
*15 minutes. No pitch, no pressure. Live in 7 days if you're a fit.*

---

## 5. Proposal Template

**Prepared for:** {{owner_first_name}}, Owner — {{med_spa_name}}
**Prepared by:** {{your_name}}, {{your_company}}
**Date:** {{proposal_date}} · **Valid through:** {{expiration_date}}

### The Problem We're Solving
{{med_spa_name}} is doing real volume — but every lead that waits more than 5 minutes for a reply is a lead cooling off and price-shopping your competitor down the street. Studies put the drop in conversion at **~80% when response time slips from 5 minutes to 30**. Missed calls go to voicemail (and voicemail goes nowhere). No-shows quietly burn booked revenue. And your happiest clients never get asked for the 5-star review that would bring you the next one.

You're not short on leads. You're leaking the ones you already paid for. **This engine plugs the leak — automatically, 24/7 — without adding a single task to your front desk.**

### The Outcome
Within {{days_to_value}} days of go-live, **every** new lead, missed call, and at-risk appointment gets an instant, on-brand response — and every satisfied client gets nudged for a review. The target: **recover {{recovered_bookings_per_month}}+ bookings/month** you're currently losing, at roughly **{{avg_ticket}}** per appointment — a return that pays for the entire system many times over.

### Scope of Work — What Gets Built
A done-for-you automation engine on **self-hosted n8n** (you own it — no per-seat SaaS tax, no data leaving to a third party), wired directly into {{booking_platform}} and your **Twilio** number:

1. **Speed-to-Lead Instant Reply** — Every new inquiry (web form, {{lead_sources}}) gets an SMS **and** email reply within 60 seconds, with a direct link to book.
2. **Missed-Call Text-Back** — Any unanswered call triggers an automatic text in seconds: "Sorry we missed you — here's how to book / how can we help?"
3. **No-Show & Recovery Sequences** — Smart reminders before the appointment, plus an automatic win-back flow for no-shows and cancellations to re-fill the chair.
4. **5-Star Review Requests** — After a completed visit, happy clients are automatically routed to your {{review_platform}} page; quiet feedback is routed privately to you.
5. **Owner Dashboard & Alerts** — Simple visibility into leads captured, replies sent, and bookings recovered — plus a heads-up when a hot lead needs a human.

Built, tested, and documented for you. **You don't touch n8n — that's our job.**

### Timeline

| Phase | What Happens | Timing |
|---|---|---|
| **1. Kickoff** | 30-min onboarding call; we collect Twilio + {{booking_platform}} access, your brand voice, and review links | Day 1 |
| **2. Build** | We stand up self-hosted n8n and build all four workflows | Days 2–{{build_end_day}} |
| **3. Test & Tune** | End-to-end testing with live test leads; you approve every message | Days {{test_start_day}}–{{test_end_day}} |
| **4. Go-Live** | Engine activated, monitored, and handed off with a walkthrough | Day {{golive_day}} |

**Full go-live in approximately {{total_timeline}}.**

### Investment

| Item | Price |
|---|---|
| **One-Time Setup & Build** (workflows, integration, testing, training) | **$1,500** |
| **Monthly Managed Service** (hosting, monitoring, message tuning, edits, support) | **$400/mo** |

*Twilio usage and any SMS carrier fees are billed at-cost directly through your own Twilio account (typically {{est_twilio_cost}}/mo). No long-term contract — month-to-month after the first {{minimum_term}}.*

### Our Guarantee (Risk Reversal)
**You carry zero risk on the build.** If the engine isn't live and working as described within {{guarantee_window}} days of receiving your access, we keep building at no extra cost until it is — or you get a full refund of the $1,500 setup. The monthly service is month-to-month: if it's not earning its keep, **cancel anytime with {{cancellation_notice}} days' notice.** We only want this in your business if it's making you money.

### Next Step
This is a simple decision: **one recovered booking a month covers the service.** Everything past that is profit you're leaving on the table today.

To lock in your build slot and get live within {{total_timeline}}:
1. **Reply "{{approval_word}}"** to this proposal, or sign below.
2. We send the kickoff link and access checklist same-day.
3. You're live and recovering leads by **{{target_golive_date}}**.

> We only onboard **{{monthly_client_cap}} new builds per month** to keep quality high. Your slot is reserved through **{{expiration_date}}**.

**Approved & accepted:**

________________________  ____________
{{owner_first_name}} {{owner_last_name}}, {{med_spa_name}}  ·  Date

________________________
{{your_name}}, {{your_company}} · {{your_phone}} · {{your_email}}

---

*Note: Market Brief stats are sourced from third-party studies (linked above) and are presented as industry benchmarks, not guarantees; the Proposal's outcome figures use merge fields so each estimate is set per-prospect. SMS texting features assume A2P 10DLC registration and inbound-inquiry consent — confirm compliance details with the client before go-live. Nothing in this kit has been sent, published, or deployed.*