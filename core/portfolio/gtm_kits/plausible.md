PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

# Plausible Analytics — GTM Kit
**Offer:** Done-for-you privacy-safe analytics for dental practices
**Target:** Owner / office manager of a 1–4 dentist practice in Austin, TX running a website + paid ads
**Price:** $600 setup + $150/mo

---

## 1. Market Brief

### Top 3 pains removed
1. **HIPAA-pixel legal exposure.** GA4 + Meta Pixel quietly ship visitor IPs, page URLs (which can reveal a service like "dental implants" or "sedation"), and ad-click IDs to Google/Meta. That's the exact data pattern now driving HIPAA tracking-pixel lawsuits and OCR enforcement against healthcare sites. We remove the pixels and replace them with cookieless, no-PII tracking the practice actually owns.
2. **"I have no idea which ads or referrers actually produce booked patients."** Most practices run Google/Meta ads on faith. GA4's interface is overbuilt, sampled, and consent-mode-gapped, so the owner can't get a straight answer to "where did this month's new patients come from?" We deliver one plain-English monthly patient-source report instead.
3. **Cookie-banner friction + data they don't control.** Cookieless analytics needs no GDPR/CPRA cookie consent banner for the analytics layer, and all data lives on infrastructure tied to the practice — not buried in a Google property the office manager can't navigate.

### 2 alternatives the buyer uses now
1. **Google Analytics 4** (free, already installed, usually by a past web vendor) — the default, and the source of the risk.
2. **"Whatever the marketing agency / web guy sends us"** — a screenshot of sessions in a monthly PDF, or nothing at all; no first-party setup, no conversion clarity.

### Single sharpest wedge
**The pixel on your site is now a legal liability, not just a marketing tool — and the fix also finally tells you which ads book patients.** One move kills a lawsuit vector *and* gives the owner the number they've always wanted. No competing "analytics tool" leads with the legal angle to a dentist; that's the opening.

### 3 objections (and the answer)
1. *"Our web guy / agency already handles analytics."* — They installed the pixel that's the liability. We don't replace your web person; we fix the tracking layer and hand you a report they don't provide. Happy to loop them in.
2. *"$150/mo for analytics when GA is free?"* — GA is free because *you* are the product and the data goes to Google. The $150 buys legal risk reduction + a done-for-you report nobody on staff has to build. One avoided demand letter or one correctly-cut ad budget pays for a year.
3. *"Is this actually HIPAA-compliant / will it break my site?"* — Cookieless tracking collects no PII and no cookies; it's lighter than the pixels we remove and won't slow the site. We provide a written summary of exactly what is and isn't collected. (Note: we are not your lawyer — final compliance sign-off stays with your counsel; we reduce the exposure and document it.)

---

## 2. Service Pack — `build_privacy_analytics_pack`

### Components
| Component | What it is |
|---|---|
| Managed self-hosted Plausible | A Plausible instance run on infrastructure I manage (single VPS, multi-tenant), tracking script served under a domain tied to the practice. |
| Pixel audit & removal | Find every GA/Meta/3rd-party tracking tag on the site, document it, remove or replace it. |
| Cookieless tracking install | Plausible script deployed; no cookies, no cross-site identifiers, no PII. |
| Conversion / goal tracking | Track the actions that mean "new patient lead": appointment-form submit, click-to-call, booking-widget click, contact submit. |
| Branded monthly patient-source report | One PDF, practice-logo'd: traffic by source, which paid campaigns drove conversions, top pages, month-over-month trend, one plain-English takeaway. |
| Written "what we collect" summary | One-page plain-English data sheet the practice can show counsel/staff. |

### What the client receives
- A live, password-protected analytics dashboard URL (read-only login for the office).
- Their old tracking pixels removed, with a before/after audit list.
- Conversion goals firing on their real lead actions, validated with a test submission.
- A branded monthly PDF on the 1st of each month (delivered, not self-serve).
- The one-page data-collection summary for compliance peace of mind.
- Email support for "what does this number mean" questions.

### Reused-across-clients vs customized-per-client
**Reused (my platform / templates — keeps margin high):**
- The Plausible server, hosting, backups, updates, security patching.
- The pixel-audit checklist and removal SOP.
- The monthly report template + the generation workflow.
- The "what we collect" summary boilerplate.
- Conversion-goal patterns (form/call/booking) — same recipes every time.

**Customized per client:**
- Which specific tags exist on *their* site and how they're injected (Tag Manager vs hardcoded vs theme).
- Their real lead actions / which booking tool they use (LocalMed, Dentrix portal, Calendly, custom form).
- Report branding (logo, practice name) + the one written takeaway each month.
- Their tracking subdomain + dashboard access.

**Operator reality:** ~3–4 hrs setup per client (mostly the audit + goal wiring), ~20–30 min/mo per client to generate and sanity-check the report. One VPS comfortably hosts dozens of practices.

---

## 3. Outreach Sequence

3 touches, from one prospect, plain text, sent from a personal address. Replace `{{...}}` before sending. **Drafts only — nothing is sent in PROPOSE MODE.**

### Touch 1 — Day 0
**Subject:** the tracking pixel on {{practice_name}}'s site

Hi {{first_name}},

Quick heads-up, not a pitch: the Google/Meta tracking pixel on {{practice_website}} is the same kind of pixel now driving the wave of HIPAA tracking-pixel lawsuits and OCR complaints against medical and dental practices. It quietly sends visitor data (including which service pages they viewed) off to Google and Meta.

I set up privacy-safe, cookieless analytics for Austin dental practices — same "where do my new patients come from" insight, without the pixel that creates the exposure. As a bonus you finally get a clear monthly read on which ads actually book patients.

Worth a 10-minute call to see if it applies to your site? I can show you exactly what's firing on it.

— {{your_name}}, {{your_city}}
{{your_phone}}

*Not interested? Reply "no" and I won't follow up.*

### Touch 2 — Day 3
**Subject:** re: the tracking pixel on {{practice_name}}'s site

Hi {{first_name}},

Following up with the concrete version. On most dental sites I look at, I find GA4 plus a Meta pixel loading on the appointment-request page — meaning form context and the visitor's IP leave your control. That page is exactly where the lawsuits focus.

The fix is a one-time swap: I pull the pixels, drop in cookieless tracking you own, and wire up conversion tracking so you can see which Google/Meta campaigns produce real booking actions. You get a branded patient-source report each month.

10 minutes this week? I'll walk you through what's on {{practice_website}} live, no commitment.

— {{your_name}}
{{your_phone}}

*Reply "no" to opt out — I'll stop here.*

### Touch 3 — Day 7
**Subject:** last note — your patient-source numbers

Hi {{first_name}},

Last one from me. Two things most practice owners I talk to want and don't have:

1. Confidence the website tracking isn't quietly creating a HIPAA-pixel liability.
2. A straight answer to "which ads actually booked patients last month."

I deliver both for a flat setup plus a low monthly, fully done-for-you. If now's not the time, no problem — I'll leave the door open.

If you want me to run a free 10-minute audit of what's on {{practice_website}}, just reply "audit" and I'll grab a slot.

— {{your_name}}
{{your_phone}}

*Not the right fit? Reply "no" and you won't hear from me again.*

---

## 4. Landing Copy

### Hero
**H1:** See where your new patients come from — without the privacy lawsuits GA invites.
**Subhead:** Done-for-you, cookieless analytics for Austin dental practices. We pull the tracking pixels that create HIPAA exposure, replace them with privacy-safe tracking you own, and send you a plain-English patient-source report every month.
**CTA button:** Book a free 10-minute pixel audit

### Problem
The Google Analytics and Meta pixels sitting on your practice website were installed to help marketing. Today they're a liability. They send visitor IP addresses and the exact pages people view — including service pages like implants or sedation — to Google and Meta. That data pattern is what's driving the wave of HIPAA tracking-pixel lawsuits and OCR complaints against clinics.

And after all that risk, you *still* can't get a clear answer to the only question that matters: which ads and referrers actually book new patients? GA4 is overbuilt, sampled, and broken by cookie consent — so it sits unread.

### The offer
We replace the risky tracking with a managed, self-hosted Plausible setup that is cookieless, collects no personal data, and needs no cookie-consent banner. Then we wire up conversion tracking on your real lead actions — appointment forms, click-to-call, booking clicks — so every month you get one branded, plain-English report showing exactly where your new patients came from and which paid campaigns earned them.

- **Pixel audit & removal** — we find and pull every risky tag.
- **Cookieless tracking you own** — no cookies, no PII, no banner.
- **Conversion tracking** — see which ads produce booking actions.
- **Branded monthly patient-source report** — delivered, not another dashboard to learn.

### Why trust us
- We lead with the legal-risk angle because we actually audit what's on your site and show it to you live — before you pay anything.
- Managed and self-hosted: we run, patch, and back up the analytics; you get a clean read-only dashboard and a monthly PDF.
- Local and focused: we work with Austin dental practices, not everyone with a website.
- We give you a one-page written summary of exactly what is and isn't collected, so your counsel can sign off. (We reduce and document your exposure — your attorney owns final compliance.)

### Pricing
**$600 one-time setup** — pixel audit, removal, cookieless install, conversion tracking, dashboard, and your data-collection summary.
**$150/month** — managed hosting, updates, backups, your branded monthly patient-source report, and email support.
No long-term contract. Cancel anytime; you keep your audit.

### FAQ
**Is this HIPAA-compliant?**
Cookieless tracking collects no cookies and no personal data, which removes the pixel pattern the lawsuits target. We give you a written summary of exactly what's collected for your counsel. We're not your lawyer — we reduce and document the exposure; final sign-off stays with your attorney.

**Will this slow down or break my website?**
No. The Plausible script is lighter than the GA and Meta pixels we remove, so your site typically gets faster. We test conversions with a live submission before we're done.

**Do I have to give up Google Analytics?**
That's the point — GA is the source of the risk. But if you want, we can leave a stripped-down internal setup in place. Most practices are glad to be off it once they see the cleaner report.

**What do I actually get each month?**
One branded PDF: where your traffic came from, which paid campaigns drove booking actions, your top pages, the month-over-month trend, and one plain-English takeaway. No dashboard homework required.

### Closing CTA
**Stop running on a pixel that could cost you a lawsuit — and start seeing which ads book patients.**
Book a free 10-minute audit and I'll show you live exactly what's tracking on your site.
**CTA button:** Book my free 10-minute audit

---

## 5. Proposal Template

> Replace all `{{merge_fields}}` before sending. **Draft only — nothing sent in PROPOSE MODE.**

**Privacy-Safe Analytics — Proposal for {{practice_name}}**
Prepared for: {{contact_name}}, {{contact_title}}
Prepared by: {{your_name}}, {{your_business_name}}
Date: {{date}} · Valid through: {{expiry_date}}

### Outcome
After this engagement, {{practice_name}} will:
- No longer run the GA/Meta tracking pixels currently creating HIPAA-pixel exposure on {{practice_website}}.
- Have cookieless, practice-owned analytics that need no cookie-consent banner.
- See, every month, which marketing sources and paid campaigns actually drive new-patient booking actions — in one plain-English report.

### Scope
**Included:**
1. Full tracking audit of {{practice_website}} — every GA/Meta/3rd-party tag documented (before/after list).
2. Removal of the risky pixels and installation of cookieless Plausible tracking under a subdomain tied to your practice.
3. Conversion tracking on your real lead actions: {{lead_actions_e_g_appointment_form_click_to_call_booking_widget}}.
4. Read-only analytics dashboard access for {{number_of_logins}} staff member(s).
5. A one-page written summary of exactly what is and isn't collected, for your counsel.
6. Managed hosting, security updates, and backups, ongoing.
7. A branded monthly patient-source report, delivered by the {{report_delivery_day}} of each month.

**Not included:** Website redesign, ad-campaign management, or legal/compliance sign-off (we reduce and document exposure; your attorney owns final compliance).

### Timeline
- **Day 0:** Kickoff + site access. Audit delivered.
- **Days 1–5:** Pixel removal, cookieless install, conversion tracking, validated with a live test submission.
- **Day 5:** Dashboard handoff + data-collection summary.
- **Day 30:** First branded monthly report delivered. Recurring on the {{report_delivery_day}} thereafter.

### Investment
- **One-time setup:** $600 (audit, removal, install, conversion tracking, dashboard, data summary).
- **Monthly service:** $150/mo (managed hosting, updates, backups, branded monthly report, email support).
- No long-term contract. Month-to-month; cancel anytime with {{notice_period_e_g_30_days}} notice.

### Risk reversal / guarantee
If, within 30 days of setup, the cookieless tracking and your first monthly report aren't in place and working as described, I'll refund the $600 setup in full — and you keep your tracking audit. You're never locked in: the monthly service is cancel-anytime.

### Next step
Reply to this proposal or sign below, and I'll send a kickoff link to grab site access. We can have your audit done within {{turnaround_days}} of access.

Approved by: ______________________  Date: __________
{{contact_name}}, {{practice_name}}