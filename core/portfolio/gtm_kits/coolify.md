PROPOSE MODE — drafts for operator review; nothing sent, published, or deployed.

---

# Coolify Hosting — Go-To-Market Kit

**Offer:** Done-for-you Coolify migration + managed hosting
**Price:** $897 setup + $297/mo
**Niche entry point:** Web design & development agencies in Austin, TX
**Build step:** `build_migration_blueprint`

---

## 1. Market Brief

### Top 3 pains removed

1. **The bill that keeps climbing.** A 6-person shop running 10 client apps on Vercel/Heroku/Render watches the monthly invoice drift from $180 to $400+ as bandwidth, build minutes, add-on Postgres, and per-seat pricing stack up — with zero matching increase in performance. We move those same apps onto one VPS they own and cap the hosting cost at ~$40-60/mo of raw infrastructure.
2. **DevOps work nobody on staff actually wants to own.** Designers and front-end devs don't want to babysit SSL renewals, build pipelines, server patching, or 2am "the site's down" calls. The retainer makes that someone else's job.
3. **Vendor lock-in and pricing surprises.** Every PaaS pricing change (Heroku killing free dynos, Vercel's bandwidth overages, Render's instance bumps) is a fire drill. Coolify on their own server is portable, predictable, and re-deployable to any provider in an afternoon.

### 2 alternatives the buyer uses now

- **Status quo PaaS (Vercel / Heroku / Render / Netlify):** zero-ops, great DX, but the bill scales with success and you never own the stack.
- **A part-time freelance DevOps contractor or "the most technical person on the team" doing it ad hoc:** cheaper in theory, but inconsistent, undocumented, bus-factor-of-one, and the work competes with billable client hours.

### The single sharpest wedge

**"You're paying $300+/mo for hosting you could run for $40 — and the only thing standing between you and that savings is a weekend of terminal work nobody on your team wants to do. We do the weekend. You keep the savings."** The ROI is unusually clean: setup pays for itself in roughly 4-5 months, and every month after is positive cash. That math closes deals.

### 3 objections (and the answer)

1. *"What if you disappear / what if Coolify breaks and we're stuck?"* → Everything runs on **their** server, under **their** accounts, with full documented runbooks handed over. The retainer is convenience, not a hostage situation — they can fire us and still run.
2. *"Self-hosting means downtime and we'll be the ones explaining it to our clients."* → Backups, uptime monitoring, and alerting are in scope from day one; we target parity-or-better uptime and we're the first to know when something's off, not the client.
3. *"Migrating 10 live client apps sounds risky."* → Migrations are staged and reversible: new server stands up in parallel, we cut over one app at a time behind DNS, old PaaS stays live until each app is verified green. No big-bang switch.

---

## 2. Service Pack — `build_migration_blueprint`

The flagship deliverable. Before any cutover, every engagement produces a **Migration Blueprint**: a per-client document that maps the current stack to the target Coolify setup and serves as the contract for what "done" looks like.

### Components of the engagement

| Component | What it does |
|---|---|
| **Discovery + Migration Blueprint** | Inventory every app, runtime, DB, env var, cron, and domain. Map current→target. Flag risks. This is the build step. |
| **VPS provisioning** | Spin up a right-sized server (Hetzner/DigitalOcean), hardened base image, firewall, SSH keys, Coolify installed + secured. |
| **Coolify configuration** | Projects, environments, resource limits, internal networking, private registry if needed. |
| **App migration** | Move each app: repo connect, build config, env vars, managed databases (Postgres/MySQL/Redis), persistent volumes, file/storage migration. |
| **CI/CD** | Git-push-to-deploy wired per app (GitHub/GitLab webhooks), preview/staging environments where wanted. |
| **SSL + domains** | Automated Let's Encrypt certs, DNS cutover, www/apex/redirect handling, wildcard where needed. |
| **Backups** | Scheduled DB + volume backups to off-server object storage (S3/B2), tested restore. |
| **Monitoring + alerting** | Uptime checks, resource dashboards, alert routing to email/Slack/Telegram. |
| **Handover + runbook** | Documented access, "how to deploy," "how to restore," "who to call" — so the client is never trapped. |

### What the client receives

- A live, owned VPS running all their apps on Coolify, every app green and verified.
- The **Migration Blueprint** PDF (their stack, documented — valuable even on its own).
- A **Runbook** (deploy / restore / scale / troubleshoot).
- Backup + monitoring dashboards with their alerts wired in.
- A before/after **cost comparison sheet** they can show their own clients or partners.

### Reused across clients vs. customized per client

| Reused across clients (your IP / leverage) | Customized per client |
|---|---|
| Hardened VPS base image + provisioning script | App inventory & the Blueprint itself |
| Coolify install/secure checklist | Per-app build configs & env mapping |
| Backup-to-object-storage template | DNS/domain cutover plan |
| Monitoring/alerting stack config | Database sizes & migration windows |
| Runbook template (fill-in-the-blanks) | Risk list & rollback plan |
| Outreach, proposal, cost-comparison templates | Final cost-comparison numbers |

The first migration is ~70% custom learning; by client three you're ~70% templated. That ratio is the business.

---

## 3. Outreach Sequence

**Cold email, 3 touches (Day 0 / 3 / 7).** One CTA throughout: a 10-minute call. Plain text, no images, signature implied.

### Touch 1 — Day 0

**Subject:** quick math on your hosting bill
**Subject (alt):** [Agency name]'s Vercel bill

> Hi {{first_name}},
>
> Most shops your size overpay Vercel/Heroku $300+/mo for hosting you could run for about $40 on your own server.
>
> I do done-for-you migrations for Austin dev shops: I move your client apps onto your own VPS running Coolify (open-source Heroku, basically), wire up CI/CD, SSL, backups and monitoring, and then manage it. No terminal work on your end.
>
> Worth a 10-minute call to see if the math works for {{company}}? I'll bring a rough before/after of your likely savings.
>
> — {{your_name}}
>
> Not a fit? Reply "no" and I'll close the loop.

### Touch 2 — Day 3

**Subject:** re: quick math on your hosting bill

> Hi {{first_name}},
>
> Following up with the actual numbers. A typical 8-10 app setup on Vercel/Heroku runs $300-450/mo. The same apps on one Coolify VPS: ~$40-60/mo of infrastructure. Even with a managed retainer, most shops land 50-60% net lower — and they *own* the stack instead of renting it.
>
> The migration is staged and reversible: old hosting stays live until each app is verified on the new server, so there's no risky big-bang switch.
>
> Still happy to walk through it in 10 minutes — {{calendar_link}}.
>
> — {{your_name}}
>
> If now's not the time, reply "no" and I'll stop here.

### Touch 3 — Day 7

**Subject:** last note — keeping your stack portable

> Hi {{first_name}},
>
> Last one from me. Beyond the savings, the real win is portability: when the next PaaS pricing change lands (and it will), you're not scrambling — your apps are on infrastructure you control and can move anywhere in an afternoon.
>
> If hosting costs aren't on your radar this quarter, no problem. If they are, grab any 10-minute slot here: {{calendar_link}}.
>
> — {{your_name}}
>
> Either way I'll leave you be after this — just reply "no" to close it out.

---

## 4. Landing Copy

### Hero

# Cut Your Vercel and Heroku Bill by 70% — Without Touching a Terminal

**We migrate your client apps onto your own server running Coolify, then manage it for you. Same speed, same git-push deploys — a fraction of the cost, and you own the stack.**

`[ Book a 10-minute call ]`

*Done-for-you migration + managed hosting for Austin dev shops. $897 setup, $297/mo.*

### The problem

Your PaaS bill started reasonable. Then you onboarded more clients, shipped more apps, and the invoice quietly crept past $300/mo — bandwidth overages, build minutes, a managed Postgres here, another seat there. You're paying rental prices for infrastructure you could own outright for ~$40/mo. But ripping it out means a weekend of server config, SSL, CI/CD, and backups — work nobody on your team wants to own. So the bill keeps climbing.

### The offer

We do that weekend for you. **Coolify** is the open-source Heroku: push to git, it builds and deploys, handles SSL, databases, and previews — all on a server you control.

- **We provision** a hardened VPS sized to your apps.
- **We migrate** every app off Vercel/Heroku/Render — staged and reversible, zero downtime.
- **We wire up** CI/CD, SSL, backups, and monitoring.
- **We manage** it on retainer, so you never touch a terminal.

You get the DX you love, the bill you want, and a stack you actually own.

### Why trust us

- **Reversible by design.** Your old hosting stays live until every app is verified green on the new server. No big-bang cutover.
- **You own everything.** The server, the accounts, the documented runbooks — all yours. The retainer is convenience, not lock-in. Fire us and you still run.
- **Austin-local.** We work with dev shops in your city, in your timezone, who answer the phone.
- **You see the math first.** Every engagement starts with a before/after cost comparison. If it doesn't save you money, we'll tell you.

### Pricing

**$897 one-time setup** — discovery, Migration Blueprint, VPS provisioning, full migration of your apps, CI/CD, SSL, backups, monitoring, and handover runbook.

**$297/mo managed retainer** — updates, patching, backup monitoring, uptime alerting, deploy support, and "something's wrong" coverage.

> Typical shop: ~$350/mo on PaaS → ~$50/mo infrastructure + $297 retainer. Setup pays for itself in about 4-5 months; you're cash-positive every month after.

`[ Book a 10-minute call ]`

### FAQ

**Will my apps be slower on a self-hosted server?**
No — usually faster. We right-size the VPS to your actual load, and a dedicated server typically outperforms shared PaaS tiers. We benchmark before/after as part of the migration.

**What happens if something breaks at 2am?**
Uptime monitoring and alerting are in scope from day one — we're notified before your client is. The retainer covers incident response. And because everything's documented, you're never dependent on a single person.

**Am I locked into you?**
The opposite. Everything runs on your server, under your accounts, with full runbooks handed over. Cancel the retainer anytime and keep running the stack yourself — or hand it to anyone else.

**How risky is migrating live client apps?**
Low. We stand up the new server in parallel and cut over one app at a time behind DNS. Your existing hosting stays live and untouched until each app is verified working. Anything off, we roll back instantly.

### Final CTA

## Stop renting your infrastructure.

Book a 10-minute call. We'll look at your current setup and show you the before/after numbers — no commitment.

`[ Book a 10-minute call ]`

---

## 5. Proposal Template

> **Migration & Managed Hosting Proposal**
> Prepared for **{{client_company}}** by **{{your_name}}, {{your_company}}**
> Date: {{date}} · Valid through: {{valid_through}}

### Outcome

By the end of this engagement, **{{client_company}}** will run all **{{app_count}}** of your applications on a **{{vps_provider}}** server you own, managed through Coolify — cutting your hosting spend from approximately **${{current_monthly_cost}}/mo** to **~${{target_infra_cost}}/mo of infrastructure**, with CI/CD, SSL, backups, and monitoring fully configured. Projected all-in monthly (infrastructure + retainer): **~${{projected_all_in}}/mo** — an estimated **{{savings_pct}}% reduction**, and you own the stack outright.

### Scope

**Included:**
- Discovery and **Migration Blueprint** for all {{app_count}} apps (inventory, mapping, risk + rollback plan)
- VPS provisioning and security hardening
- Coolify install, configuration, and project setup
- Migration of each app: builds, env vars, databases ({{database_list}}), volumes, file storage
- CI/CD (git-push-to-deploy) per app
- SSL certificates and DNS cutover for {{domain_count}} domains
- Scheduled backups to off-server storage, with a tested restore
- Uptime monitoring + alerting routed to {{alert_channel}}
- Handover runbook and a walkthrough session

**Not included (available on request):** new feature development, application code refactoring, design work, third-party license costs, the VPS hosting bill itself (~${{target_infra_cost}}/mo, billed by {{vps_provider}} directly to you).

### Timeline

| Phase | Work | Duration |
|---|---|---|
| 1 | Discovery + Migration Blueprint | {{phase1_days}} (≈2-3 days) |
| 2 | Provision + configure server | ≈1 day |
| 3 | Staged app migration + verification | {{phase3_days}} (≈3-5 days) |
| 4 | DNS cutover, backups, monitoring, handover | ≈1-2 days |

**Estimated total: {{total_timeline}} (typically 7-10 business days)**, scheduled around your client deadlines.

### Investment

| Item | Amount |
|---|---|
| One-time setup & migration | **$897** |
| Managed hosting retainer | **$297/mo** |
| VPS infrastructure (paid to {{vps_provider}}) | ~${{target_infra_cost}}/mo |

*Setup is due to begin; retainer begins at first successful cutover. Month-to-month — cancel anytime with 30 days' notice.*

### Risk reversal / guarantee

**Cutover guarantee:** Your existing hosting stays live and paid until every app is verified green on the new server. If we can't deliver a working migration, **you pay nothing for setup** and walk away on your current stack with no disruption.

**No lock-in guarantee:** Everything runs on infrastructure you own, with full runbooks handed over. Cancel the retainer anytime — you keep the working stack and the documentation.

### Next step

1. Reply **"approved"** to this proposal (or e-sign at {{signature_link}}).
2. We schedule a 30-minute discovery call and kick off the Migration Blueprint.
3. First app is live on your new server within {{first_app_eta}}.

> Questions before you decide? Grab 10 minutes: {{calendar_link}}.
>
> — {{your_name}}, {{your_company}} · {{your_email}} · {{your_phone}}