PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

# Penpot Design — Go-To-Market Kit

**Offer:** Done-for-you self-hosted Penpot on your agency's own server/VPC — hardened Docker Compose, HTTPS, encrypted backups, SSO, and a client-facing data-ownership one-pager, plus a managed retainer.
**Price:** $1,500 setup + $300/mo managed
**Buyer:** Owner or ops/IT lead at a 5–30 person branding/design agency serving regulated/NDA-bound clients
**Niche:** Branding and design agencies in Washington, DC

---

## 1. Market Brief

**Who this is for:** A DC branding/design shop whose client roster skews toward law firms, federal contractors, healthcare/biotech, financial services, trade associations, and government-adjacent orgs — clients who put real teeth in their NDAs and ask hard questions about where files live.

### Top 3 pains removed
1. **"Our design files sit on a US SaaS vendor's cloud we don't control."** Today every board, asset, and client logo lives in Figma's multi-tenant cloud. With self-hosted Penpot, files live on the agency's own server/VPC — the agency can answer "where is our data?" with a server, a region, and a backup location instead of a vendor's marketing page.
2. **"We can't pass a client security questionnaire or NDA data-residency clause without hedging."** Regulated DC clients increasingly send vendor security reviews. Penpot self-hosted plus the included data-ownership one-pager gives a clean, truthful answer: data at rest on infrastructure you control, encrypted backups, SSO-gated access, no third-party design-tool processor in scope.
3. **"Seat-based SaaS pricing scales against us and we don't own our work environment."** Per-editor cloud pricing punishes growth and contractor churn. A self-hosted instance turns a rising variable seat bill into a fixed, predictable cost on infrastructure the agency owns — and the agency keeps the environment even if it later changes managers.

### 2 alternatives the buyer uses now
1. **Figma (cloud) / Adobe stack** — the default. Familiar, full-featured, but multi-tenant cloud with data-residency answers the agency can't fully control, and seat costs that climb with headcount.
2. **DIY self-host or "we'll have our dev set it up"** — someone spins up open-source Penpot/other OSS on a box, then it rots: no HTTPS renewal discipline, no tested backups, no SSO, no patching, and it becomes a liability nobody owns. Most agencies in this band have no in-house person who *owns* this past week one.

### The single sharpest wedge
**"Pass the client security questionnaire."** Not "save money," not "open source" — the wedge is the moment a regulated client's NDA or vendor-security review forces the question *"where do our design files live and who can touch them?"* Penpot Design lets a DC agency answer that in writing, on infrastructure they own, with backups and SSO — turning a deal-threatening procurement hurdle into a one-page yes. Cost savings and ownership are supporting beats, not the spear.

### 3 objections (and the honest answer)
1. *"Penpot isn't Figma — will my designers actually use it?"* — Fair. Penpot is closest-to-Figma of the open-source tools and improving fast, but it isn't a 1:1 replacement. Honest framing: this is for the client-confidential / regulated slice of your work where data control is the deciding factor, run it as a pilot on one project before any full switch. We don't oversell parity.
2. *"What happens if you disappear / get hit by a bus?"* — Everything runs on **your** server with standard, documented Docker Compose and open-source software — no proprietary lock-in to me. You get the runbook, the backup keys, and the one-pager. The retainer is for convenience, not captivity, and you can offboard with everything in hand.
3. *"$300/mo to babysit a Docker container?"* — The retainer isn't babysitting an idle box; it's tested restores, security patching, version upgrades, SSO/user changes, and being the named owner when a client asks a security question. The alternative is your most expensive person doing it badly at 11pm, or nobody doing it until it breaks.

---

## 2. Service Pack — `build_penpot_deployment_pack`

### Components (what gets built)
- **Hardened Docker Compose stack** — Penpot (frontend, backend, exporter), PostgreSQL, Redis, reverse proxy (Caddy/Traefik) with auto-renewing HTTPS, sane resource limits, restart policies, and a locked-down network posture (no exposed DB/Redis ports).
- **HTTPS + domain** — TLS via Let's Encrypt on the agency's chosen subdomain (e.g. `design.agency.com`), HSTS, modern cipher config.
- **Encrypted backups** — Automated nightly `pg_dump` + assets snapshot, client-side encrypted, shipped to the agency's own object storage (S3/B2/Wasabi) with a **documented, tested restore** (not just a backup that's never been opened).
- **SSO** — OIDC/SAML integration to the agency's identity provider (Google Workspace / Microsoft Entra / Okta) so access follows their existing joiner/mover/leaver process; optional registration lockdown so only SSO users get in.
- **Data-ownership one-pager** — A client-facing PDF the agency can hand to *their* clients/procurement: where data lives, encryption at rest/in transit, access control, backup/retention, and offboarding. The artifact that wins the security questionnaire.
- **Runbook + handover** — Plain-language ops doc: how to add/remove users, restore from backup, apply updates, rotate secrets, and who-owns-what. Backup encryption keys handed to the agency.

### What the client receives
- A live, HTTPS, SSO-gated Penpot instance on infrastructure **they own** (their VPS/VPC).
- The encrypted backup pipeline running to **their** storage, with a restore demonstrated on a call.
- The data-ownership one-pager (PDF + editable source) branded to their agency.
- The runbook and all credentials/keys in their password manager.
- A 30-minute team walkthrough recording.

### Reused across clients vs. customized per client
| Reused across clients (the IP / the product) | Customized per client |
|---|---|
| Hardened Compose templates & reverse-proxy config | Domain/subdomain + DNS + TLS for their host |
| Backup + encryption + restore scripts | Their object-storage bucket, keys, retention policy |
| SSO integration playbooks (Google/Entra/Okta) | Their specific IdP wiring, groups, and lockdown rules |
| Data-ownership one-pager **template** | Agency branding, client names/region, their actual stack |
| Runbook template + onboarding walkthrough script | Hosting target (their VPS vs. AWS/GCP VPC), sizing |
| Hardening/security checklist | Pilot-project scoping for their first confidential job |

**Margin logic:** ~80% of the build is reused templates and scripts; per-client work is DNS, IdP wiring, and storage — a repeatable 1–2 day deployment after the first few.

---

## 3. Outreach Sequence

3-touch cold email. One audience: owner or ops/IT lead at a 5–30 person DC branding/design agency. One CTA throughout: a 10-minute call. Plain text, no images, personalized first line.

---

**TOUCH 1 — Day 0**
**Subject:** where your client design files live

Hi {{first_name}},

Quick one — do your regulated clients' NDAs make uploading design files to Figma's cloud a problem? A few DC agencies working with law firms and federal-adjacent clients have hit this on security questionnaires.

I set up self-hosted Penpot (open-source, Figma-style) on the agency's *own* server — hardened, HTTPS, encrypted backups, SSO — so your client files never leave infrastructure you control. Comes with a one-page data-ownership doc you can hand straight to a client's procurement team.

Worth a 10-minute call to see if it fits {{company}}?

— {{sender_name}}, {{sender_title}}

*Not relevant? Reply "no thanks" and I'll close the loop.*

---

**TOUCH 2 — Day 3**
**Subject:** re: where your client design files live

Hi {{first_name}},

Following up with the concrete version. When a {{company}} client sends a vendor security review and asks "where do our design files live and who can access them?" — self-hosted Penpot lets you answer: on your server, encrypted at rest, SSO-gated, backed up to your own storage. In writing, on a one-pager.

It's done-for-you: $1,500 to deploy on your box, $300/mo to keep it patched, backed up, and audit-ready. Most agencies run it as a pilot on one confidential project first — no big switch.

Open to a 10-minute call this week?

— {{sender_name}}

*Want me to stop? One word and you're off my list.*

---

**TOUCH 3 — Day 7**
**Subject:** last note — owning your design stack

Hi {{first_name}},

Last one from me. The agencies that care about this are usually the ones whose clients put real teeth in their NDAs — government, legal, healthcare, finance. If that's not {{company}}, no worries and I'll leave it there.

If it is: I'll stand up a self-hosted Penpot instance on infrastructure you own, with the data-ownership one-pager that gets you through procurement — and you keep everything even if we part ways.

10 minutes? Here's my calendar: {{calendar_link}}

— {{sender_name}}

*Reply "unsubscribe" and I won't follow up again.*

---

## 4. Landing Copy

### Hero
# Your client design files never leave your servers. Self-hosted Figma, managed.
**Penpot Design** stands up a hardened, self-hosted Penpot instance on your agency's own server or VPC — HTTPS, encrypted backups, and SSO included — so you can finally answer "where do our design files live?" with infrastructure you control.

**[ Book a 10-minute call ]**
*$1,500 setup + $300/mo managed. For DC branding & design agencies with regulated, NDA-bound clients.*

### The problem
Your clients are law firms, contractors, healthcare and finance brands. Their NDAs and vendor security reviews ask one question your current tools can't cleanly answer: **where do our design files live, and who can access them?**

Right now those files sit in a multi-tenant SaaS cloud you don't control, behind data-residency answers you can't fully verify, on seat pricing that climbs every time you hire. One tough procurement questionnaire and the deal stalls.

### The offer
We deploy **Penpot** — the open-source, Figma-style design tool — on **your** infrastructure, done-for-you and kept running:
- **Hardened Docker Compose** stack with HTTPS, locked-down networking, sensible defaults
- **Encrypted backups** to your own storage, with a restore we actually test in front of you
- **SSO** wired to your Google Workspace, Microsoft Entra, or Okta
- **A client-facing data-ownership one-pager** you hand straight to procurement
- **A managed retainer** — patching, upgrades, user changes, and a named owner when a client asks a security question

Files live on infrastructure you own. You keep the keys, the runbook, and everything else — even if we part ways.

### Why trust us
- **No lock-in by design.** Standard Docker Compose, open-source software, your server. You hold the backup keys and the runbook from day one.
- **Honest about fit.** Penpot isn't a 1:1 Figma clone. We scope it to your confidential, regulated work and recommend a pilot before any full switch — we'd rather right-fit one project than oversell a migration.
- **Tested, not theoretical.** A backup you can't restore isn't a backup. We demonstrate the restore on a call before handover.

### Pricing
**$1,500 one-time setup** — deployment on your server/VPC, HTTPS, encrypted backups, SSO, data-ownership one-pager, runbook, and team walkthrough.
**$300/mo managed** — security patching, version upgrades, backup monitoring + periodic restore tests, user/SSO changes, and named-owner support for client security questions.
*No per-seat fees. Cancel anytime — you keep the instance and all keys.*

**[ Book a 10-minute call ]**

### FAQ
**Is Penpot really a Figma replacement?**
It's the closest open-source option and improving quickly, but it isn't identical. We position it for your client-confidential, regulated work where data control is the deciding factor — and we recommend running a pilot on one project before any broader switch.

**What if we want to leave, or you disappear?**
Everything runs on your server with standard Docker Compose and open-source software. You already hold the backup keys, runbook, and credentials. There's no proprietary layer to extract — you can offboard with everything in hand.

**Where exactly does our data live?**
On the server or VPC **you** choose — your region, your hosting account. Encrypted backups go to **your** object storage (S3, Backblaze B2, Wasabi, etc.). We document all of it in the data-ownership one-pager for your clients' procurement teams.

**What does the $300/mo actually cover?**
Security patching and version upgrades, backup monitoring with periodic tested restores, SSO and user changes, and being the named owner who answers when a client sends a security questionnaire. Not babysitting an idle box — keeping it audit-ready.

### Closing CTA
**Stop hedging on the "where do our files live?" question.**
Get a self-hosted, managed Penpot instance on infrastructure you own — and a one-pager that gets you through procurement.
**[ Book a 10-minute call ]**

---

## 5. Proposal Template

> Replace every `{{merge_field}}` before sending. Keep it to two pages.

**Penpot Design — Self-Hosted Penpot Deployment & Management**
Prepared for **{{client_agency_name}}** ({{client_contact_name}}, {{client_contact_title}})
Prepared by **{{sender_name}}, {{sender_title}}** — {{sender_date}}
Valid through **{{proposal_valid_through}}**

### Outcome
Within {{timeline_days}} business days, {{client_agency_name}} will run its own self-hosted Penpot design environment on {{hosting_target}} — HTTPS-secured, SSO-gated, and backed up with encryption to {{client_storage_target}}. You'll be able to answer any client's "where do our design files live and who can access them?" with a signed data-ownership one-pager backed by infrastructure you own. Goal: clear {{primary_client_or_use_case}}'s security review without hedging.

### Scope
**Included:**
- Hardened Docker Compose deployment of Penpot on {{hosting_target}} (frontend, backend, exporter, PostgreSQL, Redis, reverse proxy)
- HTTPS on {{design_subdomain}} with auto-renewing TLS and modern hardening
- Encrypted nightly backups to {{client_storage_target}}, with a restore demonstrated live before handover
- SSO via {{identity_provider}} (OIDC/SAML), with registration locked to SSO users
- Client-facing data-ownership one-pager (PDF + editable source), branded to {{client_agency_name}}
- Ops runbook + 30-minute team walkthrough (recorded); all keys and credentials handed to your password manager

**Not included (available as add-ons):** data migration from existing Figma files, custom plugin development, end-user design training beyond the walkthrough, hosting/infrastructure fees (billed by {{hosting_provider}} directly to you).

### Timeline
- **Day 0 — Kickoff:** confirm host, domain, IdP, and storage access ({{client_agency_name}} provides {{client_prerequisites}})
- **Days 1–2 — Build:** deploy stack, HTTPS, backups, SSO
- **Day 3 — Verify & hand over:** live restore test, walkthrough, one-pager delivery, keys handed over
*Total: ~{{timeline_days}} business days from prerequisites received.*

### Investment
- **Setup (one-time): $1,500** — due 50% to start, 50% on handover
- **Managed retainer: $300/mo** — patching, upgrades, backup monitoring + periodic restore tests, SSO/user changes, named-owner support for client security questions; month-to-month, cancel anytime
- *Excludes third-party hosting/storage fees, billed directly to you by {{hosting_provider}}.*

### Risk reversal / guarantee
**No-lock-in, restore-it-or-it's-free guarantee:** If we can't demonstrate a successful encrypted backup restore at handover, you don't pay the second half of setup — full stop. Everything runs on open-source software and standard Docker Compose on **your** infrastructure; you hold the keys and runbook from day one, so you can walk away at any time with your entire environment intact. Cancel the retainer whenever you like — the instance and all access stay yours.

### Next step
1. Sign below or reply to approve.
2. Pay the 50% setup deposit ({{deposit_amount}}) via {{payment_link}}.
3. Book kickoff: {{calendar_link}}.

Approved by: ______________________  ({{client_contact_name}}, {{client_contact_title}})  Date: __________

— {{sender_name}}, {{sender_title}} · {{sender_email}} · {{sender_phone}}