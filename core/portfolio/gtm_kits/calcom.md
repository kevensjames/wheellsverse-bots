PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

# GTM Kit — Cal.com Scheduling for Scottsdale Med Spas

---

## 1. Market Brief

**Who we're selling to:** Owner/manager of a 1-3 location med spa in Scottsdale, AZ, currently paying $200-500/mo for Vagaro, Mindbody, or Calendly. They run injectables, laser, facials, and body contouring — high-ticket appointments ($300-1,500) where a single no-show is real money out the door.

### Top 3 pains we remove
1. **No-shows on high-ticket slots.** A no-show on a $600 laser appointment isn't a gap in the calendar — it's $600 gone plus a wasted provider hour. Their current tool either doesn't enforce deposits or makes them too clunky to turn on. We collect a Stripe deposit at the moment of booking, so the client has skin in the game before they ever walk in.
2. **A booking page that looks like someone else's brand.** A $400/visit clientele lands on a page stamped with a Calendly logo or a generic Vagaro marketplace listing that surfaces competitors. It cheapens a premium brand. We give them a booking page on *their* subdomain, in *their* colors, with *their* logo — nobody else's name on it.
3. **Round-robin and provider routing that's a fight to configure.** Multi-provider spas need new clients spread across injectors fairly and returning clients routed back to "their" person. In Mindbody/Vagaro this is buried in settings or behind a higher tier. We set it up correctly once and manage it.

### 2 alternatives the buyer uses now
- **All-in-one spa platforms (Vagaro / Mindbody):** Booking + POS + marketing bundled, $200-500/mo, but the booking UX is dated, deposit enforcement is weak or upsold, and the brand is theirs-not-yours. Switching feels heavy because POS/records live there.
- **Calendly (+ a patchwork):** Cheap and clean, but it's obviously Calendly, deposit collection is limited/awkward for med-spa flows, and round-robin across providers on the cheaper tiers is thin. It screams "small operation."

### The single sharpest wedge
**Deposit-on-booking that actually gets turned on.** Every competitor *technically* supports deposits; almost nobody has it configured and live because it's fiddly and they're afraid of friction. We make "card-on-file / deposit collected before the slot is confirmed" the default, done-for-them — and tie it to the no-show number, which is the one metric that directly maps to recovered revenue. That's the line that gets a yes: *"~30% fewer no-shows, and it's already set up."*

### 3 objections (and the answer)
1. *"My POS / client records / memberships live in Vagaro — I can't move."* → You don't move them. We replace only the **booking funnel** — the public page where new and returning clients schedule. Keep Vagaro for checkout and records; we feed clean, deposit-secured appointments into your day. (Honest caveat: two-way calendar sync, not a full POS migration.)
2. *"Won't asking for a deposit scare clients off?"* → For $300-1,500 services, a refundable deposit *filters out* the people who were going to ghost you anyway. We set the amount conservatively (e.g., $50, credited to the visit) and you keep the no-show fee. The clients you want don't blink.
3. *"$897 + $197/mo is more than my current tool."* → Your current tool is the $200-500/mo line item. We're the layer that recovers the no-show revenue that line item is leaking. One recovered $600 no-show a month covers us three times over. If we don't move your no-show number, you can walk (see guarantee).

---

## 2. Service Pack — `build_booking_pack`

A productized, repeatable build. The operator runs the same `build_booking_pack` checklist per client; only a thin top layer is customized.

### Components (what gets built)
- **Self-hosted Cal.com instance** on the client's subdomain (e.g., `book.glowmedspaaz.com`), TLS, behind the operator's managed hosting.
- **Brand skin:** logo, brand colors, favicon, custom booking-page copy, confirmation/reminder email branding.
- **Event types per service:** injectables, laser, facials, consults, etc. — duration, buffers, lead time, and pricing/deposit per type.
- **Providers & routing:** one seat per injector/provider; round-robin for new clients, sticky routing for returning clients where supported.
- **Calendar sync:** two-way Google/Microsoft 365 sync per provider so personal calendars and the booking page never double-book.
- **SMS + email reminders:** confirmation, 24h reminder, 2h reminder, configurable.
- **Stripe deposit-on-booking:** connected to the client's own Stripe account; deposit (or full prepay) captured before the slot confirms; no-show fee policy wired in.
- **Embed + links:** "Book Now" button/embed for their site, Instagram link-in-bio URL, Google Business Profile booking link.

### What the client receives
- A live, branded booking page on their subdomain.
- Their providers, services, hours, and deposit rules configured and tested with a real test booking.
- A one-page "how it works" cheat-sheet + a 20-minute handoff walkthrough (recorded).
- A monthly managed service: monitoring, updates, config changes, reminder/deposit tweaks, and a short monthly "no-shows prevented" note.

### Reused across clients vs. customized per client

| Reused across clients (build once, clone) | Customized per client |
|---|---|
| Cal.com deployment/hosting template & infra | Subdomain + DNS/TLS for their domain |
| Event-type templates for standard med-spa services | Their exact service menu, durations, prices, deposits |
| Reminder copy templates (SMS/email) | Logo, colors, favicon, page copy, brand voice |
| Round-robin / sticky-routing config recipe | Their providers, seats, working hours |
| Stripe deposit flow recipe & no-show policy template | Their Stripe account connection + deposit amounts |
| Onboarding cheat-sheet & handoff video script | Their embed on their site / IG / Google profile |
| Monthly managed-ops checklist | Their monthly "no-shows prevented" report |

**Operator note:** ~80% of every build is the cloned template. The per-client work is one intake form (brand assets + service menu + Stripe + provider list) → ~half a day of configuration → a test booking → handoff.

---

## 3. Outreach Sequence — 3-touch cold email

From the hook: *"I build med spas a fully branded booking page with deposit collection that's cut no-shows ~30%."*
One CTA throughout: **a 10-minute call.** One-line opt-out on every email.
*(Compliance note for operator: cold B2B email — use real business addresses, a true physical address in the footer, honor opt-outs. The ~30% figure should reflect your own results; soften to "as much as 30%" or cite a named case study before sending if you can't yet stand behind it.)*

### Touch 1 — Day 0
**Subject options:** `No-shows at {{spa_name}}?` / `{{first_name}} — your booking page has Calendly's logo on it`

> Hi {{first_name}},
>
> Quick one — I build Scottsdale med spas a fully branded booking page (your subdomain, your colors, no Calendly logo) that collects a deposit when clients book. For the spas I've done it for, it's cut no-shows by around 30%.
>
> On a $600 laser slot, one recovered no-show a month more than pays for the whole thing.
>
> Worth a 10-minute call to see if it'd move the number at {{spa_name}}?
>
> — {{operator_name}}, {{operator_company}}
> {{phone}} · {{calendar_link}}
>
> *Not the right fit? Reply "no" and I won't follow up.*

### Touch 2 — Day 3
**Subject:** `Re: No-shows at {{spa_name}}?`

> Hi {{first_name}},
>
> Following up with the one number that matters: most spas I talk to are quietly eating 1-3 no-shows a week on high-ticket slots because their booking tool doesn't actually enforce a deposit — it's there, but it's never turned on.
>
> I do it done-for-you: branded page on your subdomain, providers + round-robin, calendar sync, SMS reminders, and a Stripe deposit captured before the slot is confirmed. You keep Vagaro/Mindbody for everything else.
>
> 10 minutes this week? Here's my calendar: {{calendar_link}}
>
> — {{operator_name}}
>
> *Prefer I stop? Reply "no" — that's the last you'll hear from me.*

### Touch 3 — Day 7
**Subject:** `Closing the loop, {{first_name}}`

> Hi {{first_name}},
>
> Last note from me. If no-shows aren't costing you enough to bother with, ignore this and I'll close it out.
>
> But if even one missed $400-600 appointment a week stings, that's roughly $1,600-2,400/month walking out the door — and the fix is a deposit-on-booking page I can stand up on your subdomain in about a week, fully managed.
>
> If it's worth 10 minutes: {{calendar_link}}. If not, no hard feelings.
>
> — {{operator_name}}, {{operator_company}}
>
> *Reply "no" to opt out and I'll remove you for good.*

---

## 4. Landing Copy

### Hero
**H1:** Your Own Branded Booking System — No More Calendly Logo, No More No-Shows
**Subhead:** Done-for-you booking on *your* subdomain, in *your* brand — with a Stripe deposit collected before every appointment. Built and managed for Scottsdale med spas. Live in about a week.
**Primary CTA:** Book a 10-minute call → `{{calendar_link}}`
**Trust strip under CTA:** Your subdomain · Your Stripe account · Your providers · Cancel anytime

### The Problem
Your booking page is doing two things to your brand right now:

- **It's wearing someone else's name.** A $400-a-visit client lands on a Calendly page or a Vagaro marketplace listing that lists your competitors three rows down. That's not the first impression a premium med spa wants to make.
- **It's letting people ghost you for free.** Your tool *can* take deposits — it's just never set up, because it's fiddly. So every week a couple of high-ticket slots no-show, and that revenue is simply gone.

You didn't build a $500-a-visit experience to lose it at the booking screen.

### The Offer
We stand up a **white-labeled, self-hosted Cal.com booking system on your own subdomain** and manage it for you:

- Booking page in your logo, colors, and domain — no third-party branding
- Your providers, with round-robin for new clients and routing back to favorites for returning ones
- Two-way Google / Microsoft 365 calendar sync — no double-bookings
- SMS + email reminders (confirmation, 24h, 2h)
- **Stripe deposit collected at booking** — into your own Stripe account, with your no-show policy
- Embeds for your website, Instagram bio, and Google Business Profile

You keep Vagaro or Mindbody for POS and records. We replace the part that's costing you money: the booking funnel.

### Why Trust Us
- **Done-for-you, not DIY.** You hand over your brand assets and service menu once; we build, test with a real booking, and hand you a live system. No dashboards to wrestle.
- **It's your stuff, on your terms.** Your subdomain, your Stripe account, your client data. We manage it; you own it.
- **Built for med spas specifically.** Deposit-on-booking and provider round-robin aren't afterthoughts here — they're the whole point.
- **Local and accountable.** Focused on Scottsdale med spas, managed by one operator who answers the phone.

### Pricing
**$897 one-time setup + $197/month managed**

Setup includes the full branded build, your providers and services, calendar sync, SMS reminders, and Stripe deposit configuration — tested and handed off live. The monthly covers hosting, monitoring, updates, unlimited config changes, and a monthly "no-shows prevented" snapshot.

Compare to: what you're paying Vagaro/Mindbody/Calendly today ($200-500/mo) *plus* the no-show revenue you're not recovering. One saved high-ticket appointment a month typically covers the entire monthly fee.

**CTA:** Book a 10-minute call → `{{calendar_link}}`

### FAQ
**Q: Do I have to leave Vagaro / Mindbody?**
No. Keep them for POS, records, and memberships. We only replace the public booking page — the part where deposits and branding matter most. Your calendars stay in sync.

**Q: Won't asking for a deposit drive clients away?**
For $300-1,500 services, a small refundable deposit (credited to the visit) mostly filters out the people who were going to no-show anyway. Your real clients expect it. You set the amount; we wire it up.

**Q: Whose Stripe account does the money go into?**
Yours. Deposits and payments flow directly into your own Stripe account — we configure the connection but never touch the funds.

**Q: How long until it's live?**
About a week from the day you send over your brand assets, service menu, and provider list. We build, test with a real booking, and walk you through it.

### Final CTA
**Stop losing $400 slots at the booking screen.**
Book a 10-minute call and I'll show you exactly what your branded, deposit-secured page would look like.
→ `{{calendar_link}}`

---

## 5. Proposal Template

> **Branded Booking System — Proposal for {{spa_name}}**
> Prepared for {{contact_name}}, {{contact_title}} · {{date}}
> From {{operator_name}}, {{operator_company}} · {{operator_email}} · {{phone}}

### Outcome
Within ~{{timeline_days}} days, {{spa_name}} will have a fully branded booking page at **{{booking_subdomain}}** that collects a **{{deposit_amount}} deposit** into your own Stripe account before each appointment is confirmed — with the goal of cutting no-shows on high-ticket slots by roughly **{{target_noshow_reduction}}** and recovering the revenue those empty slots cost you today.

### Scope
**Included in this engagement:**
- Self-hosted Cal.com instance on **{{booking_subdomain}}** (TLS, managed hosting)
- Brand skin: logo, colors, favicon, booking-page copy, branded confirmation/reminder emails
- Event types for your services: {{service_list}} — with per-service durations, buffers, and deposits
- Providers configured ({{provider_count}} seats): {{provider_names}}, with round-robin for new clients and sticky routing for returning clients
- Two-way calendar sync (Google / Microsoft 365) per provider
- SMS + email reminders: confirmation, 24-hour, and 2-hour
- Stripe deposit-on-booking connected to **your** Stripe account, with your no-show policy
- Embeds for your website, Instagram bio link, and Google Business Profile
- Real test booking + recorded handoff walkthrough + one-page cheat-sheet

**Not included (kept where they are):** POS, checkout, client records, and memberships remain in {{current_platform}}. This replaces the booking funnel only — not a full platform migration.

### Timeline
| Phase | What happens | Timing |
|---|---|---|
| Kickoff | You send brand assets, service menu, provider list, Stripe connect | Day 0 |
| Build | Instance stood up, branded, services + providers + reminders configured | Days 1-4 |
| Deposit + sync | Stripe deposit flow + calendar sync wired and tested | Days 4-6 |
| Handoff | Real test booking, walkthrough, go-live | ~Day {{timeline_days}} |

### Investment
- **One-time setup:** **${{setup_fee}}** (default $897) — full build, configuration, testing, handoff
- **Managed monthly:** **${{monthly_fee}}/mo** (default $197) — hosting, monitoring, updates, unlimited config changes, monthly "no-shows prevented" snapshot
- Billing: setup due at kickoff; monthly begins at go-live. {{payment_terms}}
- Month-to-month. Cancel anytime with {{cancellation_notice}} notice.

### Risk-Reversal / Guarantee
**14-day go-live guarantee.** If your branded, deposit-collecting page isn't live and working within 14 days of you sending complete assets, your setup fee is **fully refunded** — no questions.
**90-day no-show guarantee.** Run it for 90 days. If your no-show rate on high-ticket appointments hasn't measurably improved, I'll work the next month free until it does — or refund that month. You keep the system regardless.

### Next Step
1. Reply **"approved"** to this proposal (or sign at {{esign_link}}).
2. I send a 5-minute intake for your brand assets, service menu, and provider list.
3. You connect Stripe (your account) via a secure link.
4. We go live in ~{{timeline_days}} days.

**Questions first?** Grab 10 minutes here: {{calendar_link}}

---

*All deliverables above are drafts for operator review. Nothing has been sent, published, deployed, or billed. Before any outreach: verify the ~30% no-show claim against your own results (or soften the language), confirm CAN-SPAM footer requirements, and rotate/secure any Stripe credentials handled during onboarding.*