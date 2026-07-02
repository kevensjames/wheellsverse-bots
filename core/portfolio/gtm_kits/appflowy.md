PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

# AppFlowy Enterprise — Go-To-Market Kit
### Done-for-you private AppFlowy workspace for Charlotte CPA & tax firms under the FTC Safeguards Rule

---

## 1. Market Brief

**Who we sell to:** Managing partner or IT admin at a 5–40 person CPA / tax / bookkeeping firm in Charlotte, NC. They handle client SSNs, financial statements, and tax returns — which makes them a "financial institution" under the FTC Safeguards Rule (16 CFR Part 314), so a documented information security program isn't optional for them.

### Top 3 pains removed
1. **"Our SOPs and client procedures live on a SaaS cloud we don't control."** Notion/Google host the firm's entire operating playbook on multi-tenant infrastructure with vendor staff access and unclear data residency. We move it to a single-tenant box the firm owns, with no third-party reading the data.
2. **"We can't cleanly answer the Safeguards questions about our knowledge systems."** The Rule requires access controls, encryption, an inventory of where data lives, and a named person responsible. Most firms have none of this written down for their internal wiki. We deliver the access-role map, encryption-at-rest/in-transit evidence, and backup proof as artifacts they can hand an auditor or cyber-insurer.
3. **"Onboarding and 'where's that procedure?' eats senior time every busy season."** Tribal knowledge lives in 6 people's heads and 40 stale Google Docs. We migrate it into one structured, searchable workspace so a new hire ramps in days, not months.

### 2 alternatives the buyer uses now
- **Notion / Google Workspace (SaaS):** familiar and cheap, but multi-tenant, vendor-accessible, and a recurring "is this even compliant?" headache.
- **A shared network drive + Word docs (or a SharePoint nobody maintains):** technically "on our servers" but unsearchable, version-chaos, no role controls, and no backup story.

### The single sharpest wedge
**The FTC Safeguards Rule turned "where our SOPs live" from an IT preference into a compliance liability — and we hand the firm a self-hosted workspace plus the exact audit artifacts that close that gap, for less than the monthly cost of one billable afternoon.** We sell *compliance evidence they can show*, not just software.

### 3 objections (and the answer)
1. *"We're not technical — who maintains this?"* → It's fully managed. Patching, backups, and monitoring are on us for $400/mo. You log in and use it like Notion; you never touch a server.
2. *"AppFlowy isn't as polished as Notion."* → True on some edges. But for SOPs, wikis, and client-procedure databases it does 95% of what you use Notion for — and the 5% you give up buys you sole control of the data and a clean compliance answer. We migrate your content so the switch is invisible to staff.
3. *"$2,500 + $400/mo feels steep vs. our $20/seat Notion."* → One reportable data incident or a failed cyber-insurance question costs far more than a year of this. You're buying single-tenant isolation, managed ops, and Safeguards artifacts — not seats. (And at ~15 seats, Notion Business already runs you more per month than this.)

---

## 2. Service Pack — `build_compliance_deploy_blueprint`

The repeatable engine behind every engagement. A solo operator runs this as a checklist + a library of reused templates, customizing only the thin client-specific layer.

### Components
1. **Provision & Harden** — Single-tenant AppFlowy Cloud (self-hosted, Docker Compose stack) on a dedicated VM (client's cloud account or one we manage). Firewall, TLS, SSH hardening, automatic security updates.
2. **SOP / Content Migration** — Pull the firm's existing SOPs, checklists, and client-procedure docs out of Notion/Google/Word into a structured AppFlowy workspace (spaces → wikis → databases).
3. **Role-Based Access** — Workspace roles mapped to firm roles (partner / manager / staff / contractor), least-privilege by default, named workspace owner.
4. **Encrypted Backups** — Encrypted-at-rest nightly backups to a separate location, with a documented restore test.
5. **FTC Safeguards Mapping** — A short evidence pack mapping what we built to the relevant 16 CFR 314.4 elements (access controls, encryption, asset inventory, qualified individual, service-provider oversight).
6. **Managed Operations** — Ongoing patching, backup monitoring, uptime checks, and a quarterly restore test + access review.

### What the client receives
- A live, private AppFlowy workspace at their own domain (e.g. `wiki.theirfirm.com`), staff logins issued.
- Their SOPs migrated and organized into a clean structure (not a doc dump).
- A **Compliance & Deploy Blueprint** PDF: architecture diagram, access-role matrix, encryption summary (at rest + in transit), backup & restore-test record, and the Safeguards-element mapping table.
- A one-page **Restore & Continuity** runbook.
- Managed support with a named contact and a quarterly review cadence.

### Reused across clients vs. customized per client

| Reused across clients (your IP / templates) | Customized per client |
|---|---|
| Docker Compose stack + hardening script | Their VM, domain, TLS cert |
| Backup + restore-test automation | Their actual SOP/content migration |
| AppFlowy workspace structure template (firm-ops wiki, client-procedure DB, onboarding space) | Role matrix mapped to *their* org chart |
| Safeguards-mapping document template | Firm name, qualified-individual name, asset inventory specifics |
| Restore/continuity runbook template | Their backup location + tested restore record |
| Onboarding & training deck | Live training session with their team |

> **Margin note:** ~80% of each build is the reused blueprint. The customized 20% (content migration + role mapping + filling in their names/inventory) is the only part that scales with effort — which is what keeps a one-person operation profitable at this price.

---

## 3. Outreach Sequence (3-touch: Day 0 / 3 / 7)

Cold email to a Charlotte CPA firm's managing partner. Plain text, one clear CTA (a 10-minute call), one-line opt-out on every message. Merge fields in `{{ }}`.

> **Compliance note (for the operator, not the prospect):** confirm CAN-SPAM basics — real sender name, valid physical mailing address in the footer, honored opt-outs.

---

**EMAIL 1 — Day 0**
**Subject:** where {{firm_name}}'s SOPs actually live
**Subject (alt):** the Safeguards question about your wiki

Hi {{first_name}},

Since the FTC Safeguards Rule, most CPA firms I talk to are a little uneasy that their SOPs and client procedures live on a SaaS cloud — Notion, Google — that they don't actually control.

I set up private, self-hosted knowledge bases for accounting firms here in Charlotte: same Notion-style workspace your team already knows, except it runs on a server *you* own, with role-based access, encrypted backups, and a tidy evidence pack mapped to the Safeguards Rule.

Worth a quick look for {{firm_name}}? I can walk you through it in 10 minutes.

Open to a short call next week?

Best,
{{your_name}}
{{your_phone}} · {{your_company}}, Charlotte NC

*Not interested? Reply "no thanks" and I won't follow up.*

---

**EMAIL 2 — Day 3**
**Subject:** re: where {{firm_name}}'s SOPs actually live

Hi {{first_name}},

Quick follow-up. The part that usually lands with partners isn't the software — it's that they walk away with **artifacts an auditor or cyber-insurer will actually ask for**: an access-role matrix, encryption summary, and a tested backup record, all mapped to the Safeguards Rule.

You keep the Notion-style experience your staff likes; the firm keeps sole control of the data.

Setup is $2,500, then $400/mo fully managed — I handle the server, patching, and backups so nobody at {{firm_name}} has to.

Can I grab 10 minutes this week to show you what the finished workspace looks like?

Best,
{{your_name}}
{{your_phone}} · {{your_company}}, Charlotte NC

*Prefer I stop? Just reply "stop" — that's the last you'll hear from me.*

---

**EMAIL 3 — Day 7**
**Subject:** closing the loop, {{first_name}}

Hi {{first_name}},

I'll leave it here so I'm not crowding your inbox.

If "are our internal procedures stored somewhere we actually control?" is a question you'd rather have a clean answer to before your next insurance renewal or peer review, that's exactly the gap I close for Charlotte firms — self-hosted workspace, done-for-you, with the compliance evidence in hand.

If now's the time, here's my calendar for a 10-minute call: {{calendar_link}}

Either way, thanks for reading.

Best,
{{your_name}}
{{your_phone}} · {{your_company}}, Charlotte NC

*This is my last note on this — reply "no" anytime and you're off my list for good.*

---

## 4. Landing Copy

### Hero
# Your firm's knowledge base, self-hosted and private — Notion power, your servers.
**A done-for-you, single-tenant AppFlowy workspace for Charlotte CPA and tax firms. Your SOPs and client procedures, migrated and managed — on a server you control, with the FTC Safeguards evidence to prove it.**

[**Book a 10-minute call →**]

---

### The problem
Your operating procedures, client checklists, and onboarding docs are the most valuable thing your firm owns that isn't a client relationship. Right now they probably live on Notion or Google — a multi-tenant cloud where vendor staff can access the data, you can't say exactly where it sits, and "is this Safeguards-compliant?" is a question nobody wants to answer out loud.

Since the FTC Safeguards Rule, that's not just an IT preference anymore. It's a documented-controls problem your insurer and your peer reviewer can ask about.

---

### The offer
We stand up a **private AppFlowy Cloud** — the open-source, Notion-style workspace — on a single-tenant server that belongs to your firm. Then we do the work most firms never get around to:

- **Migrate your SOPs** out of Notion/Google/Word into one clean, searchable workspace.
- **Role-based access** mapped to your org — partner, manager, staff, contractor — least-privilege by default.
- **Encrypted backups**, nightly, with a tested restore.
- **A Safeguards evidence pack** — access matrix, encryption summary, backup record — mapped to 16 CFR 314.4.
- **Fully managed** — we run the server, patching, and monitoring. You just log in and work.

Your team gets the Notion experience they already know. Your firm gets sole control of the data and a clean compliance story.

---

### Why trust us
- **Charlotte-local and specialized.** We work with accounting and tax firms, not "any business." We speak Safeguards, busy season, and peer review.
- **Single-tenant by design.** Your workspace is yours alone — no shared infrastructure, no other firms' data on the same box.
- **Managed, not dumped.** This isn't "here's a server, good luck." There's a named contact, a quarterly review, and a restore test you can point to.
- **Evidence you can hand over.** When your insurer or auditor asks about internal data systems, you have a document — not a shrug.

---

### Pricing
**$2,500 one-time setup** — provisioning, hardening, full SOP migration, role mapping, backups, and your Compliance & Deploy Blueprint.
**$400/month managed** — hosting oversight, patching, backup monitoring, quarterly restore test + access review, and support.

No per-seat pricing. Add your whole team. *(Server/VM hosting can run on your cloud account or be bundled — we'll size it on the call.)*

[**Book a 10-minute call →**]

---

### FAQ

**Q: Is AppFlowy as good as Notion?**
For firm SOPs, wikis, and client-procedure databases, it covers the vast majority of what you use Notion for — and we migrate your content so the change is nearly invisible to staff. The trade-off you make on a few polish details, you get back as full control of your data.

**Q: We're not technical. Who runs the server?**
We do — entirely. The $400/mo covers patching, backups, monitoring, and updates. Your team only ever sees a login screen, the same as any web app.

**Q: Does this make us "FTC Safeguards compliant"?**
It closes a specific, real gap — where your internal knowledge lives and how it's controlled — and gives you documented evidence (access controls, encryption, backups) mapped to the Rule. We're your knowledge-system component, not your entire compliance program; we'll be clear about exactly what we cover and what stays with you or your IT/compliance advisor.

**Q: What if we want to leave?**
It's open-source AppFlowy and it's your data on your server. There's no lock-in — we'll hand over a full export and documentation. We'd rather earn the $400 every month than trap you.

[**Book a 10-minute call →**]

---

## 5. Proposal Template

> Send as a 1–2 page PDF or doc. Replace every `{{merge_field}}`.

---

**Private Knowledge Base — Engagement Proposal**
Prepared for **{{firm_name}}** · Attn: **{{contact_name}}, {{contact_title}}**
Prepared by **{{your_name}}, {{your_company}}** · {{date}}
Valid through **{{proposal_expiry_date}}**

---

### Outcome
{{firm_name}} will have a **private, self-hosted AppFlowy workspace** — your team's SOPs and client procedures migrated into one searchable, role-controlled system that runs on a server your firm controls. You'll walk away with the data isolation and the documented evidence (access, encryption, backups) that directly address the FTC Safeguards Rule's requirements for your internal knowledge systems — without adding a single server-admin task to your team's plate.

### Scope
1. Provision and harden a single-tenant AppFlowy Cloud server (TLS, firewall, automatic security updates) at **{{workspace_domain}}**.
2. Migrate existing SOPs and procedure content from **{{current_tools}}** into a structured workspace (firm-ops wiki, client-procedure database, onboarding space).
3. Configure role-based access mapped to {{firm_name}}'s org chart ({{number_of_seats}} users), least-privilege by default.
4. Set up encrypted nightly backups with a documented, tested restore.
5. Deliver the **Compliance & Deploy Blueprint**: architecture diagram, access-role matrix, encryption summary, backup/restore record, and FTC Safeguards (16 CFR 314.4) mapping table.
6. Live team training session + Restore & Continuity runbook.
7. **Ongoing (monthly):** managed hosting oversight, patching, backup monitoring, quarterly restore test + access review, and support.

*Out of scope:* full firm-wide compliance program, tax/legal advice, and migration of non-knowledge data (e.g., client tax files in your practice-management system). We cover the knowledge-system component and will name what stays with your IT/compliance advisor.

### Timeline
- **Week 1:** kickoff, server provisioning + hardening, workspace structure built.
- **Week 2:** SOP/content migration, role configuration, backups + restore test.
- **Week 3:** training, Blueprint delivery, go-live.
- **Target go-live: {{target_go_live_date}}.** Ongoing managed service begins at go-live.

### Investment
- **One-time setup: $2,500** — provisioning, hardening, full migration, role mapping, backups, Blueprint, and training.
- **Managed service: $400/month** — hosting oversight, patching, backup monitoring, quarterly restore test + access review, support. Month-to-month; cancel anytime with 30 days' notice.
- *(VM/hosting: {{hosting_arrangement}}.)*

### Risk reversal / guarantee
**30-day go-live guarantee.** If your workspace isn't live with your SOPs migrated and your Blueprint delivered within 30 days of kickoff, your setup fee is fully refunded. And because it's open-source AppFlowy on your own server, **there's no lock-in** — cancel the managed service any month and keep your workspace, your data, and a full export with documentation.

### Next step
Approve by replying to this email or signing below, and we'll schedule kickoff for **{{proposed_kickoff_date}}**. A 50% setup deposit (**$1,250**) starts the work; the balance is due at go-live.

Approved: ________________________  Date: __________
**{{contact_name}}, {{contact_title}}, {{firm_name}}**

---

*Prepared by {{your_name}} · {{your_company}} · {{your_email}} · {{your_phone}} · Charlotte, NC*