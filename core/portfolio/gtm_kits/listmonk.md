PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

---

# Listmonk Email — GTM Kit

**Offer:** Done-for-you managed newsletter platform — private, branded Listmonk on your own domain (DKIM/SPF/DMARC + Amazon SES), full list migration, 3 custom templates. Flat-fee Mailchimp replacement.
**Price:** $750 setup + $200/mo
**Niche:** Independent bookstores in Portland, Oregon

---

## 1. Market Brief

### Top 3 pains removed
1. **The list-size penalty.** Mailchimp/Constant Contact bill on contact count and send volume. A bookstore that grows its list from 8k to 20k subscribers can see its bill jump from ~$150/mo to ~$400/mo for the exact same newsletter. This kit kills the per-contact tax — sending to 50k costs the same as sending to 5k.
2. **Deliverability they can't see or fix.** On shared-pool ESPs, the store has no control over sender reputation, and event/"this week's reading" emails increasingly land in Promotions or spam. A private Listmonk on a properly authenticated domain (DKIM/SPF/DMARC) over SES gives the store its own sending reputation and inbox placement they actually own.
3. **Owning the relationship, not renting it.** The subscriber list is the bookstore's single most valuable owned asset, and right now it lives inside a platform that can raise prices, change tiers, or lock the account. After migration, the list, the domain, and the platform all belong to the store.

### 2 alternatives the buyer uses now
1. **Mailchimp** — the default. Familiar, but the bill scales with the list and the free/cheap tiers keep shrinking.
2. **Constant Contact** — common with older, owner-operated retail. Friendlier support, but the same per-contact pricing model and the same lack of deliverability control.

(Distant thirds the buyer occasionally floats: Squarespace/Shopify Email bundled with their site, or "we just post it on Instagram instead" — both are why the wedge below matters.)

### The single sharpest wedge
**"Your bill goes up every time your list grows. Mine doesn't."** The flat fee is the whole pitch. For a store already paying $150–500/mo and watching that number climb each season, a fixed $200/mo that *never* moves with list size is a concrete, do-the-math win — not a vague "better tool" claim. Everything else (deliverability, ownership) is the supporting case; the price slope is the hook.

### 3 objections (and the honest answer)
1. *"Listmonk is open-source / self-hosted — is it reliable, and what if it breaks?"*
   → It's managed. You never touch a server. I run it, monitor it, patch it, and back it up — same as you never see Mailchimp's servers. The $200/mo is exactly so this is my problem, not yours.
2. *"Migrating my list sounds risky — what if I lose subscribers or break my signup form?"*
   → Migration is included and done with you watching: I export from Mailchimp, import with all tags/segments intact, set up the new signup form, and we send one test campaign before anything goes live. Your old account stays active until you confirm the new one works.
3. *"I'm not technical. Will I be able to actually send a newsletter?"*
   → If you can write an email in Mailchimp, you can send one in Listmonk. The interface is a list, a template, and a Send button. I also leave you a one-page cheat sheet and the first month of support is hands-on.

---

## 2. Service Pack — `build_listmonk_pack`

### Components
1. **Provisioning** — Managed Listmonk instance stood up on dedicated hosting (private, single-tenant per client).
2. **Domain + deliverability** — Sending subdomain (e.g. `mail.yourbookstore.com`), DKIM, SPF, and DMARC records, plus Amazon SES set up and moved out of sandbox to production sending.
3. **List migration** — Export from Mailchimp/Constant Contact; import with tags, segments, and subscription status preserved; suppression/unsubscribe list carried over (compliance-critical).
4. **Signup form swap** — New subscribe form + confirmation (double opt-in) page, embed snippet handed to the store for their website footer.
5. **3 templates** — Branded with the store's logo, colors, and fonts: (a) a weekly/standard newsletter, (b) an event announcement, (c) a new-arrivals / staff-picks layout.
6. **Test + cutover** — One test campaign to a seed list, deliverability check (inbox placement, auth pass), then go-live.
7. **Handover** — Admin login, a one-page "how to send a campaign" cheat sheet, and a 20-minute walkthrough call.
8. **Ongoing ($200/mo)** — Hosting, monitoring, patching, daily backups, SES quota management, and email support for sending questions.

### What the client receives (deliverables checklist)
- [ ] Live private Listmonk at their own admin URL
- [ ] Authenticated sending domain (DKIM/SPF/DMARC all passing)
- [ ] SES in production, sending limits sized to their list
- [ ] Full list imported, segments and unsubscribes intact
- [ ] Working signup form embedded on their site
- [ ] 3 branded templates ready to use
- [ ] One verified test send
- [ ] Cheat sheet + recorded/live walkthrough
- [ ] Month-1 hands-on support

### Reused across clients vs. customized per client
| Reused across clients (build once, run forever) | Customized per client |
|---|---|
| Listmonk install/config playbook + provisioning scripts | The store's domain + DNS records |
| Standard DKIM/SPF/DMARC + SES setup runbook | SES account/identity per sending domain |
| 3 base template skeletons (HTML structure) | Logo, colors, fonts, footer address dropped into templates |
| Migration export/import scripts (Mailchimp + Constant Contact) | Their actual list, tags, and segments |
| Monitoring, backup, and patching automation | Their seed test list + go-live timing |
| Cheat sheet + onboarding walkthrough deck | Store name swapped into the cheat sheet |

The economics: ~80% of every build is the reusable runbook. Per-client custom work is roughly half a day — DNS, branding the 3 templates, and the migration. That's what makes $750 setup + $200/mo viable for a solo operator.

---

## 3. Outreach Sequence

3 touches, plain text, sent from a real personal address (not a marketing tool). One CTA throughout: a 10-minute call. Each email carries a one-line opt-out.

**Merge fields:** `{{first_name}}`, `{{store_name}}`, `{{city}}` (Portland), `{{calendar_link}}`, `{{your_name}}`, `{{your_phone}}`

---

### Touch 1 — Day 0

**Subject:** {{store_name}}'s Mailchimp bill

> Hi {{first_name}},
>
> Quick question — is {{store_name}}'s Mailchimp (or Constant Contact) bill creeping up as your subscriber list grows?
>
> That's the part most shop owners don't love: the bigger your list gets, the more you pay every month, for the same newsletter. I move bookstores onto a private email platform on your own domain for a **flat $200/mo that doesn't change as your list grows** — plus a one-time setup. I handle the whole move, list and all.
>
> Worth a 10-minute call to see if the math works for {{store_name}}? Here's my calendar: {{calendar_link}}
>
> {{your_name}}
> {{your_phone}}
>
> *Not the right fit? Reply "no thanks" and I won't follow up.*

---

### Touch 2 — Day 3

**Subject:** the actual numbers for {{store_name}}

> Hi {{first_name}},
>
> Following up with the part that matters — the math.
>
> A shop on Mailchimp paying ~$300/mo today is at ~$3,600/year, and that number climbs every time the list grows. My flat plan is $750 once to move you over, then $200/mo — and it stays $200 whether you have 8,000 subscribers or 40,000. You also end up *owning* the list and the platform instead of renting them.
>
> I do the migration myself, your old account stays live until the new one is proven, and we send a test campaign before anything goes out for real.
>
> 10 minutes this week? {{calendar_link}}
>
> {{your_name}}
>
> *Want me to stop emailing? Just reply "stop" — no hard feelings.*

---

### Touch 3 — Day 7

**Subject:** last one — closing the loop on {{store_name}}

> Hi {{first_name}},
>
> I'll leave it here so I'm not cluttering your inbox.
>
> If the Mailchimp bill ever crosses the line from "fine" to "annoying" as your list grows, the offer stands: a private, branded newsletter platform on {{store_name}}'s own domain, full migration handled, flat $200/mo. I'm local and I work with independent {{city}} shops specifically, so this isn't a call center.
>
> If now's not the time, no problem at all — keep my email and reach out whenever. And if it *is* worth 10 minutes: {{calendar_link}}
>
> Thanks for the time, {{first_name}}.
>
> {{your_name}}
> {{your_phone}}
>
> *This is my last note unless you reply — reply "stop" anytime to opt out for good.*

---

## 4. Landing Copy

### Hero
**H1:** Stop paying Mailchimp more every time your list grows. Own your newsletter.

**Subhead:** A private, branded newsletter platform on your own domain — full list migration handled for you, flat $200/mo no matter how big your list gets. Built for independent Portland bookstores.

**Primary CTA button:** Book a 10-minute call →

---

### Problem
Your email list is the most valuable thing your shop owns — it's the readers who actually show up for the author event and buy the staff pick. So why does it cost more to reach them every season?

Mailchimp and Constant Contact bill you on contact count. Grow your list — which is the whole point — and your bill grows with it. Worse, on a shared sending platform you have no control over whether "this week at the shop" lands in the inbox or gets buried under Promotions. You're paying more, every year, to rent a list you should own.

---

### The offer
I move your newsletter onto **Listmonk** — a private, professional email platform that runs on *your* domain, fully managed by me. You get:

- **A flat monthly fee that never moves with list size.** 5,000 subscribers or 50,000 — it's $200/mo, period.
- **Your own sending reputation.** Proper DKIM/SPF/DMARC authentication on your domain over Amazon SES means your emails are set up to reach the inbox, not the spam folder.
- **The whole move done for you.** I migrate your full list, tags and segments intact, set up your signup form, and build 3 branded templates (newsletter, event, new arrivals).
- **You own everything.** The list, the domain, the platform — all yours. No more renting your most important asset.

If you can send an email in Mailchimp, you can send one here. You never touch a server — that's my job.

---

### Why trust me
I'm a solo operator who does one thing: move owner-run shops off per-contact email platforms onto owned, flat-fee ones. I'm local to Portland and I work with independent bookstores specifically — not a national agency, not a call center. When you email, you reach me. Your old Mailchimp account stays active until your new platform is proven with a live test send, so there's no leap-of-faith cutover.

---

### Pricing
**One simple plan. No per-contact pricing, ever.**

| | |
|---|---|
| **Setup (one-time)** | **$750** — provisioning, domain authentication, SES, full list migration, signup form, 3 branded templates, test send, walkthrough |
| **Managed monthly** | **$200/mo** — hosting, monitoring, patching, daily backups, deliverability management, email support |

Compare that to a Mailchimp bill that climbs every time your list grows. Most shops paying $300+/mo today are at $3,600+/year and rising — this is flat.

**CTA button:** See if the math works for your shop — book 10 minutes →

---

### FAQ

**Is Listmonk reliable if it's open-source and self-hosted?**
It's fully managed — you never see a server. I provision it, monitor it, patch it, and back it up daily, the same way you never thought about Mailchimp's infrastructure. The $200/mo exists precisely so reliability is my responsibility, not yours.

**What happens to my current subscribers during migration?**
Nothing breaks. I export your full list and import it with tags, segments, and unsubscribe history intact, set up your new signup form, and we send a test campaign before anything goes live. Your old account stays active until you confirm the new one works.

**Will I actually be able to send a newsletter myself?**
Yes. The interface is a list, a template, and a Send button. You get a one-page cheat sheet, a walkthrough call, and hands-on support for your first month. If you can do it in Mailchimp, you can do it here.

**What if I want to leave later?**
The platform runs on your domain and the list is yours — you're never locked in. If you ever move on, I hand off your data cleanly. No hostage-taking; that's the whole point of owning it.

**Final CTA:** Stop renting your list. Book a 10-minute call → [{{calendar_link}}]

---

## 5. Proposal Template

> **Newsletter Migration Proposal**
> Prepared for **{{store_name}}** ({{contact_name}})
> Prepared by **{{your_name}}** — {{your_email}} · {{your_phone}}
> Date: **{{proposal_date}}** · Valid through: **{{valid_through_date}}**

---

### Outcome
{{store_name}} will own a private, branded newsletter platform on **{{sending_domain}}** with a **flat, predictable cost of $200/mo that does not increase as your subscriber list grows** — replacing your current **{{current_platform}}** bill of approximately **{{current_monthly_cost}}/mo**. Your full list of **{{list_size}} subscribers** moves over intact, your emails are authenticated for inbox delivery, and you own the list, the domain, and the platform outright.

### Scope
**Included in this engagement:**
1. Provisioning a private, managed Listmonk instance for {{store_name}}.
2. Setting up sending domain **{{sending_domain}}** with DKIM, SPF, and DMARC authentication.
3. Configuring Amazon SES for production sending, sized to {{list_size}} subscribers.
4. Migrating your full list from {{current_platform}} — tags, segments, and unsubscribe history preserved.
5. Building your new signup form and confirmation flow; embed snippet provided for your website.
6. Building **3 branded templates** (standard newsletter, event announcement, new arrivals / staff picks) using {{store_name}}'s logo, colors, and fonts.
7. One test campaign + deliverability verification before go-live.
8. Handover: admin access, a one-page cheat sheet, and a 20-minute walkthrough call.

**Not included** (available on request): ongoing copywriting, custom automations/journeys beyond the signup confirmation, or website redesign.

### Timeline
| Phase | What happens | Timing |
|---|---|---|
| Kickoff | DNS access, branding assets, {{current_platform}} export login | Day 1 |
| Build | Instance, domain auth, SES, templates | Days 2–5 |
| Migration + test | List import, signup form, test send | Days 6–7 |
| Go-live | Cutover + walkthrough call | **~{{go_live_window}} (about 1 week)** |

Your existing {{current_platform}} account stays active throughout and until you confirm go-live.

### Investment
| Item | Amount |
|---|---|
| One-time setup (everything in Scope) | **$750** |
| Managed monthly (hosting, monitoring, patching, daily backups, deliverability, support) | **$200/mo** |
| *Per-contact / list-size fees* | **$0 — none, ever** |

First payment: $750 setup + first month ($200) due at kickoff. Monthly billing starts on go-live. **Estimated first-year total: $3,150** — compared with roughly **{{current_annual_cost}}** on {{current_platform}}, *before* their next list-growth price increase.

### Guarantee (risk reversal)
**Proven-before-you-pay-monthly cutover.** Your current platform stays live the entire time. We don't go live until a real test campaign passes deliverability checks and you've sent yourself a successful email. **If the migration isn't working to your satisfaction within 14 days of go-live, I'll refund the $750 setup fee in full** — and your old account never went away, so you've lost nothing.

### Next step
Reply to approve, or grab 10 minutes here: **{{calendar_link}}**. On that call we confirm your domain, your branding assets, and a go-live date. I can typically have {{store_name}} fully migrated within **one week** of kickoff.

— {{your_name}} · {{your_email}} · {{your_phone}}

---

*End of kit. PROPOSE MODE — nothing has been sent, published, or deployed; all copy is a draft for operator review.*