PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

# Ghost Publishing — Go-To-Market Kit
## "Client Insider" — Done-For-You Branded Newsletters for Charlotte RIAs

---

## 1. Market Brief

**Buyer:** Solo to 2–8 advisor independent RIAs and wealth-management firms in Charlotte, NC, who email clients market commentary but have no technical staff.

### Top 3 pains removed
1. **"My commentary looks like everyone else's Mailchimp blast."** Generic templates, a competitor's logo one forward away, and a footer that screams "I used a free tool." The Client Insider gives them a branded publication on their own domain (e.g., `insights.theirfirm.com`) that looks like an institution, not a mailing list.
2. **"I'm renting my client list and I don't fully own it."** On Mailchimp/Constant Contact the list, the deliverability reputation, and the archive live inside a platform they don't control and can't easily export cleanly. Self-hosted Ghost means they own the database, the member records, and the published archive outright.
3. **"There's no clean way to make this a paid offering later."** Advisors increasingly want a premium tier (model-portfolio notes, planning deep-dives) but have no path from "free email" to "paid subscription" without stitching tools together. Ghost + Stripe gives a paid/free tier toggle from day one — switched on whenever they're ready, no rebuild.

### 2 alternatives the buyer uses now
- **Mailchimp / Constant Contact / Flodesk** — email-list tools. Cheap and familiar, but rented infrastructure, weak branding, no native paid tier, and an archive that isn't really a publication.
- **"My assistant copies the commentary into Outlook / I post a PDF to the website."** Manual, unbranded, untracked, no signup mechanism, no member list growth, no archive a prospect can browse.

### The single sharpest wedge
**Ownership + a built-in paid tier, with zero technical lift for the advisor.** Competitors sell either a list tool (no ownership, no real paid tier) or a website (no newsletter engine). Ghost Publishing is the only option that hands a no-technical-staff RIA a firm-branded, self-owned newsletter that is *already wired for a Stripe paid tier* — and then runs it for them. The advisor never touches a dashboard.

### 3 objections (and the answer)
1. **"Why not just keep Mailchimp for $20/month?"** → Mailchimp is rented and caps out at "a prettier email." You're paying for an *owned asset* (your list, your archive, your domain) plus a paid-revenue path. The first 3–4 paying members at a $30/mo premium tier cover your entire retainer.
2. **"Self-hosted sounds like something that'll break and I'll be on the hook."** → You never log into a server. It's fully managed — hosting, updates, Mailgun deliverability, and backups are on me. You get a monthly "everything's healthy" note and a single point of contact (me).
3. **"Compliance — will my CCO / broker-dealer allow this?"** → It's email you already send, just on better-looking, archivable infrastructure. You keep full control of every word; nothing publishes without your approval. I'll set up an archive and disclosure footer your compliance reviewer signs off on once, then reuse it. *(Drafts only — advisor/CCO owns final approval of all content and disclosures.)*

---

## 2. Service Pack — `build_publication_pack`

What the engagement actually delivers and assembles.

### Components
| # | Component | What it is |
|---|-----------|-----------|
| 1 | **Self-hosted Ghost instance** | Ghost(Pro-equivalent) on managed VPS, on the client's subdomain (`insights.firm.com`), SSL, backups |
| 2 | **Branded theme** | Firm logo, colors, fonts, headshot, email header/footer applied to a proven base theme |
| 3 | **Stripe paid + free tiers** | Connected Stripe account; free tier live, paid tier ($X/mo + annual) configured and switchable |
| 4 | **Member signup** | Embedded signup form + a hosted subscribe page + portal (members manage their own plan) |
| 5 | **Mailgun sending** | Domain auth (SPF/DKIM/DMARC), dedicated sending subdomain, deliverability warmed |
| 6 | **Contact import** | Clean import of the existing client list from Mailchimp/CSV, deduped, tagged |
| 7 | **Compliance footer + archive** | Disclosure footer, unsubscribe, public/members-only archive structure |
| 8 | **Managed retainer** | Monthly: hosting, updates, backups, deliverability monitoring, 1 issue-send support, small tweaks |

### What the client receives (deliverables)
- A live, branded newsletter at their own subdomain, ready to publish.
- A logged-in member portal and a public subscribe page link they can put in their email signature and on their site.
- Their existing contacts imported and confirmed, with sending verified (test send + deliverability check passed).
- A 1-page "How to publish an issue" cheat sheet (write → preview → send, 3 steps) + a 15-minute walkthrough recording.
- A Stripe paid tier configured and dormant, with a 1-page "how to switch it on" note for when they're ready.
- A named point of contact (me) and a monthly health note.

### Reused-across-clients vs customized-per-client
**Reused (built once, productized — this is the margin):**
- Base Ghost theme + email template framework
- VPS provisioning / deployment scripts and server hardening checklist
- Mailgun domain-auth runbook (SPF/DKIM/DMARC)
- Stripe tier setup checklist
- Contact-import + dedupe routine
- Compliance disclosure-footer template (advisor/CCO edits the wording)
- Onboarding cheat sheet, walkthrough script, monthly health-note template

**Customized per client:**
- Logo, brand colors, fonts, headshot, firm name throughout
- Subdomain + DNS + their Stripe account + their Mailgun domain
- Their actual contact list (import, tags, segments)
- Disclosure wording their compliance reviewer approves
- Paid-tier price points and tier names

> Build target: ~6–8 hours of genuinely custom work per client on top of the reusable pack. That's what keeps a solo operator at one-and-done setups plus a stack of $450/mo retainers.

---

## 3. Outreach Sequence — 3 touches (Day 0 / 3 / 7)

Cold email to a named advisor. One CTA throughout: a 10-minute call. One-line opt-out on every send. Plain text, sent from a person, no images.

**Merge fields:** `{{first_name}}`, `{{firm_name}}`, `{{city}}` (= Charlotte), `{{your_name}}`, `{{calendar_link}}`.

---

### Touch 1 — Day 0 (the hook)
**Subject options:**
- A) `Your own branded client newsletter, {{first_name}}?`
- B) `{{firm_name}}'s market updates — off Mailchimp?`

> Hi {{first_name}},
>
> Quick one. Would you want your client market updates going out from **{{firm_name}}'s own branded newsletter — with a paid tier option — instead of Mailchimp?**
>
> I set these up for Charlotte advisory firms: a newsletter you actually own (your domain, your list, your archive), Stripe-ready for a premium tier when you want it, and fully managed so you never touch a server. You write; everything else is handled.
>
> Worth a quick look? I can show you a live example in **10 minutes**: {{calendar_link}}
>
> {{your_name}}
>
> *Not a fit? Reply "no thanks" and I won't follow up.*

---

### Touch 2 — Day 3 (proof + specificity)
**Subject options:**
- A) `Re: Your own branded client newsletter`
- B) `The 3-paying-members math, {{first_name}}`

> Hi {{first_name}},
>
> Following up with the part most advisors find compelling: the newsletter is wired for a **paid tier from day one** (Stripe, free + premium). Most firms keep it free at first — but the moment 3–4 clients subscribe at a modest premium rate, the whole thing pays for itself.
>
> And nothing changes about how you work: you write the commentary, I handle hosting, deliverability, updates, and backups. No dashboard, no IT.
>
> Want me to walk you through a live one? **10 minutes:** {{calendar_link}}
>
> {{your_name}}
>
> *Prefer I stop? One-word reply — "stop" — does it.*

---

### Touch 3 — Day 7 (last touch, low-friction close)
**Subject options:**
- A) `Last note — {{firm_name}} newsletter`
- B) `Should I close the file, {{first_name}}?`

> Hi {{first_name}},
>
> I'll leave it here so I'm not cluttering your inbox.
>
> If owning your client newsletter — branded, paid-tier-ready, and fully managed — is worth 10 minutes sometime this quarter, grab any slot here: {{calendar_link}}. If now's not the time, no problem at all; I'll close it out.
>
> Either way, wishing {{firm_name}} a strong rest of the year.
>
> {{your_name}}
>
> *Reply "no" and you're off my list for good.*

---

## 4. Landing Copy

### Hero
**H1:** Your own branded client newsletter — owned, paid-tier ready, fully managed.

**Subhead:** For Charlotte RIAs and wealth firms who send clients market commentary and want it to look — and run — like an institution, not a Mailchimp blast. You write. I handle everything else.

**Primary CTA button:** `Book a 10-minute walkthrough`

---

### Problem
You send your clients real, thoughtful market commentary. But it goes out from a rented list tool, in a template a dozen other firms also use, with no clean way to ever charge for a premium tier — and a client list you don't truly own.

If your firm grew up, your newsletter didn't. It should be on your domain, in your brand, with the option to become a paid product whenever you're ready — and it should run without you ever logging into a dashboard.

---

### The offer
**The Client Insider** is a done-for-you newsletter built on self-hosted Ghost and managed for you end to end:

- **Branded to your firm** — your logo, colors, and domain (`insights.yourfirm.com`). Looks like you, not a mailing list.
- **You own it** — your list, your archive, your member database. Not rented.
- **Paid + free tiers, Stripe-ready** — turn on a premium subscription whenever you want; no rebuild.
- **Fully managed** — hosting, deliverability (Mailgun), updates, and backups are all on me.
- **Zero technical lift** — your existing contacts imported for you; you just write and hit send.

---

### Why trust me
I'm a solo operator who does one thing: stand up and run owned newsletters for independent advisory firms. You get **one named point of contact** — not a ticket queue — a 1-page publishing cheat sheet, and a monthly note confirming everything's healthy. Every issue and disclosure stays under your control and your compliance reviewer's approval; I never publish a word without your sign-off.

---

### Pricing
| | |
|---|---|
| **Setup** (one-time) | **$1,500** — full build, branding, Stripe tiers, Mailgun, contact import, go-live |
| **Management** (monthly) | **$450/mo** — hosting, updates, deliverability, backups, support, ongoing tweaks |

> The math: at a modest premium-tier price, **3–4 paying client-members cover the entire monthly retainer** — and you keep the rest.

**CTA button:** `Book a 10-minute walkthrough`

---

### FAQ
**Q: Do I have to manage a server or learn new software?**
No. It's fully managed — you never log into a server. Publishing an issue is three steps (write, preview, send), and you get a 1-page cheat sheet plus a short walkthrough video.

**Q: What happens to my existing Mailchimp/Constant Contact list?**
I import it for you — cleaned, deduped, and verified with a test send before anything goes live. Your contacts come with you.

**Q: Will this pass my compliance review?**
It's the same email you already send, on better infrastructure. You keep full control of every word; nothing publishes without your approval, and I set up a disclosure footer and archive your compliance reviewer signs off on. *(I draft; your firm and CCO own final approval.)*

**Q: Do I have to charge for it?**
No. Most firms launch free. The paid tier is built and dormant — you switch it on whenever you're ready, with a 1-page guide for when that day comes.

**Final CTA:** `Book a 10-minute walkthrough` · {{calendar_link}}

---

## 5. Proposal Template

> **Prepared for:** {{contact_name}}, {{firm_name}}
> **Prepared by:** {{your_name}}, Ghost Publishing
> **Date:** {{date}} · **Valid through:** {{valid_through_date}}

### Outcome
{{firm_name}} will have its own branded, firm-owned client newsletter — **The Client Insider** — live at **{{publication_subdomain}}** (e.g., `insights.{{firm_domain}}`). It will look like {{firm_name}}, run on infrastructure you own, be ready to accept paid subscriptions whenever you choose, and require zero technical effort from your team. You write the commentary; I run everything underneath it.

### Scope
**Included:**
1. Self-hosted Ghost publication provisioned on managed hosting, on your subdomain with SSL and backups.
2. Custom theme applied to your brand: logo, colors, fonts, headshot, email header/footer.
3. Stripe connected; free + paid tiers configured (paid tier dormant until you activate).
4. Member signup form, hosted subscribe page, and self-serve member portal.
5. Mailgun email sending with full domain authentication (SPF/DKIM/DMARC) and deliverability verification.
6. Import of your existing contact list ({{approx_contact_count}} contacts), deduped and tagged.
7. Compliance disclosure footer + public/members-only archive (wording approved by your reviewer).
8. Onboarding: 1-page publishing cheat sheet + 15-minute recorded walkthrough.

**Not included (out of scope):** writing your market commentary, investment/compliance advice, Stripe/Mailgun third-party fees (billed to you directly at cost), and custom development beyond the items above.

### Timeline
| Milestone | Target |
|---|---|
| Kickoff + brand assets collected | Day 0 |
| Instance live, theme + branding applied | Day {{build_day_1}} (~3–5 business days) |
| Mailgun + Stripe + contact import + test send | Day {{build_day_2}} |
| Review, walkthrough, go-live | Day {{golive_day}} (typically within ~2 weeks of kickoff) |

### Investment
| Item | Amount |
|---|---|
| One-time setup & build | **$1,500** (due at kickoff) |
| Managed retainer | **$450/month** (begins at go-live; month-to-month) |

*Third-party hosting/Stripe/Mailgun fees billed at cost. No long-term contract — cancel the retainer anytime with 30 days' notice; your data exports with you.*

### Risk-reversal / guarantee
**Go-live guarantee:** If your newsletter isn't live, branded, and passing a verified test send within **14 business days** of receiving your brand assets and list — for reasons within my control — you don't pay the setup fee until it is.
**Ownership guarantee:** It's yours. If you ever leave, I hand over a full export of your site, theme, and member list — no hostage-taking, no lock-in.

### Next step
1. Reply "approved" or sign below.
2. I'll send a short brand-asset checklist + the kickoff invoice.
3. We book a 30-minute kickoff and I start the build.

> **Approved by:** ______________________  **Date:** ____________
> {{contact_name}}, {{firm_name}}

---

*PROPOSE MODE — all of the above are drafts for operator review. Nothing has been sent, published, deployed, or charged. Pricing for third-party services (hosting, Stripe, Mailgun) passes through at cost and is not included in the figures above. The operator is not a lawyer or compliance professional; all disclosure and compliance language is a draft for the advisor and their CCO to review and approve before any send.*