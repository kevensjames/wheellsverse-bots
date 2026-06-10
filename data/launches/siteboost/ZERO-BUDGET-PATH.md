# Zero-Budget Launch Path — SiteBoost on $0/mo

The standard SiteBoost stack costs **~$36-100/mo** (Google Workspace + Instantly).
This document shows the **$0/mo path** — same pipeline, free alternatives for
the paid pieces. Trade-off: lower send volume (~50/day cap vs 200+ paid) and
more manual work. But it WORKS, and you can upgrade piece-by-piece as revenue
arrives.

---

## Cost comparison

| Item | Standard stack | $0 stack | Notes |
|---|---|---|---|
| Domain registration | ✓ already owned | ✓ already owned | wheellsverse.com — $0 incremental |
| DNS hosting | Cloudflare (free) | Cloudflare (free) | Same |
| Email receiving (hello@…) | Google Workspace $6/mo | **Cloudflare Email Routing $0** | Forwards to your existing Gmail |
| Email sending | Google Workspace $6/mo | **Existing Gmail + "Send mail as"** | Use the Gmail you already have warmed |
| Cold sending tool + warmup | Instantly.ai $30-90/mo | **Mailmeteor free (50/day)** OR **manual Gmail** | No automated warmup — leverages your already-warm Gmail |
| Preview hosting | Cloudflare Pages (free) | Cloudflare Pages (free) | Same |
| Calendar booking | Calendly free | Calendly free | 1 event type covers Discovery |
| Stripe checkout | 2.9% + $0.30 per sale | 2.9% + $0.30 per sale | Same (no monthly fee) |
| Notion product delivery | Free | Free | Same |
| Google Places API | $200/mo free credit | $200/mo free credit | Covers ~6,000 lookups |
| Hunter.io enrichment | 50/mo free, $49/mo paid | 50/mo free | Stay on free tier — limits volume but unblocks proof of concept |
| Anthropic API (optional) | $5 free credit (~500 sites) | Skip — use defaults | Site copy uses template defaults instead of LLM personalization |
| **MONTHLY TOTAL** | **$36-90 + ~$50 enrich at scale** | **$0** | |

---

## The $0 Stack — step-by-step setup

### 1. Email receiving: Cloudflare Email Routing (free, ~5 min)

Cloudflare lets you create unlimited `@wheellsverse.com` addresses that
forward into ANY existing inbox (your personal Gmail, Hotmail, anything).

1. Log into [dash.cloudflare.com](https://dash.cloudflare.com) → wheellsverse.com → **Email** (left sidebar) → **Email Routing**
2. Click **Enable Email Routing** — Cloudflare auto-adds the 3 required MX records for you (no manual DNS work)
3. Click **Routing rules** → **Create address**
4. Custom address: `hello@wheellsverse.com` (or `jay@`)
5. Destination: your personal Gmail address (the one you already use)
6. Verify Gmail confirmation email
7. Done — anyone emailing `hello@wheellsverse.com` lands in your Gmail

**Replaces**: $6/mo Google Workspace mailbox.
**Trade-off**: receiving only via Cloudflare — for sending see step 2.

### 2. Email sending: Gmail "Send mail as" (free, ~10 min)

Send outbound emails appearing to come from `hello@wheellsverse.com` while
actually using your existing Gmail account's reputation. **Critical** because
your existing Gmail is already "warm" — no 28-day warmup needed.

1. Sign up [SendGrid Free](https://signup.sendgrid.com) — 100 emails/day forever free. (Or use **Resend free tier** — 100/day, same idea.)
2. Verify your sender identity in SendGrid: add `hello@wheellsverse.com` as sender, complete domain auth (SPF + DKIM via Cloudflare DNS)
3. Create an API key in SendGrid → Settings → API Keys → Full Access
4. Open Gmail → Settings (gear) → **See all settings** → **Accounts and Import** tab → **Send mail as** → **Add another email address**
5. Name: `Jay (SiteBoost)` · Email: `hello@wheellsverse.com` · Treat as alias: NO (uncheck)
6. SMTP server: `smtp.sendgrid.net` · Port: `587` · Username: `apikey` · Password: paste your SendGrid API key · TLS: yes
7. Confirm via email Gmail sends to `hello@wheellsverse.com` (it'll route through Cloudflare to your inbox)
8. Now Gmail's "From" dropdown lets you pick `hello@wheellsverse.com` when composing

**Replaces**: $30-90/mo Instantly outbound.
**Trade-off**: no automated warmup, no built-in sequencing, no reply tracking dashboard. You do those manually (see steps 3-4).

### 3. Cold sending: Mailmeteor mail merge (free, 50/day cap)

[Mailmeteor](https://mailmeteor.com/) plugs into Google Sheets and sends merged
emails directly from your Gmail. Free tier = 50 sends/day. That's 250/week
which is exactly what you need at SiteBoost's early scale.

1. Install Mailmeteor from Google Workspace Marketplace (free)
2. Run pipeline: `python3 scripts/local_prospect_run.py --all --location "Boston, MA" --limit 30 --live`
3. Export to Mailmeteor format: `python3 scripts/export_mailmeteor.py --sequences <path>` (built below)
4. Upload CSV to a new Google Sheet
5. Open Mailmeteor add-on → start campaign → pick the sheet → send 1st touch
6. **3 days later**: open Mailmeteor again → select the same sheet → send touch 2
7. **4 more days later**: send touch 3

**Manual scheduling is the trade-off.** Set 2 calendar reminders per campaign for touch 2 and touch 3.

### 4. Reply handling: Gmail filters (free)

Cold replies arrive in your existing Gmail. Set 2 filters:

- Filter 1: `to:hello@wheellsverse.com AND subject:re:` → label `SiteBoost-Reply` + skip inbox + star
- Filter 2: `to:hello@wheellsverse.com AND from:noreply` → trash (filters Mailmeteor's own bounces)

Check the `SiteBoost-Reply` label 2× daily. Use the [SALES-PLAYBOOK.md](SALES-PLAYBOOK.md) reply scripts.

### 5. Calendar: Calendly free tier (5 min)

Calendly's free tier gives you ONE event type — perfect, since you only need
"SiteBoost Discovery 15-min."

1. Sign up [calendly.com](https://calendly.com)
2. Create event type → name `SiteBoost Discovery` → 15 min · 1-on-1 · Zoom/Phone
3. Set availability (e.g., Mon-Fri 10am-4pm)
4. Copy URL → paste into your cold-email replies + sales-playbook scripts

### 6. Preview hosting: Cloudflare Pages free (already set up in v3)

Free tier: 500 builds/month, unlimited bandwidth. Run
`bash scripts/deploy_previews.sh <previews-dir>` after each campaign — pushes
previews to `preview.wheellsverse.com/<slug>` for free.

### 7. Payment: Stripe (no monthly fee, pay-per-sale)

Use the existing Stripe setup. 2.9% + $0.30 per transaction is the only cost.
$497 sale = $14.71 in Stripe fees = $482.29 net. No upfront cost.

### 8. APIs

All free tier:

| API | Free tier limit | Covers |
|---|---|---|
| Google Places | $200/mo credit | ~6,000 scans |
| Hunter.io | 50 lookups/mo | First city's enrichment |
| Anthropic | Skip (use defaults) | Site copy still works without LLM |

---

## The $0 stack reality check

### What you give up vs paid

| Capability | Paid | Free | Impact |
|---|---|---|---|
| Send volume | 200-500/day | 50/day | Slower scaling. Stay under 50/day or get rate-limited. |
| Automated warmup | Instantly handles | Use existing Gmail reputation | Skip 28-day warmup entirely. Risk: your personal Gmail's reputation if you mess up. |
| Reply tracking dashboard | Instantly UI | Gmail labels | Manual triage. Works at <20 replies/wk. |
| Sequence scheduling | Auto Day-0/Day-3/Day-7 | Manual via Mailmeteor reschedules | Set calendar reminders. Easy at small volume. |
| A/B subject lines | Native in Instantly | Manual CSV variants | Run 2 campaigns instead of 1. |
| Bounce handling | Auto-suppression | Manual: `siteboost_state.block_email()` | Use the script we already built. |
| Deliverability monitoring | Postmaster Tools (still free!) | Postmaster Tools | Same — both stacks use Google's free tool. |

### Honest expectations on the $0 path

- **Volume cap = ~250 sends/week (50/day × 5 days).**
- **Expected replies/week: 12-20** (5-8% reply rate × 250 sends)
- **Expected sales/week: 3-7** ($1,500-$3,500 revenue at $497/sale)
- **Time investment: 2-3 hrs/week** (more manual than paid — sequencing, replies, deliverability)

At 3-7 sales/week, you generate $1,500-3,500 in revenue. **After 2-3 weeks of revenue, you can self-fund the upgrade to the paid stack** ($90/mo Instantly + $6/mo Google Workspace) and keep scaling.

---

## Migration path: $0 → paid (only when revenue justifies)

| Trigger | Upgrade | Cost | Why |
|---|---|---|---|
| 3+ sales in first 30 days | Buy Instantly Standard | +$30/mo | Removes 50/day cap, adds warmup, automates sequencing |
| Volume hits 100/day | Buy Google Workspace | +$6/mo | Direct mailbox instead of SendGrid relay (better deliverability ceiling) |
| Volume hits 250/day | Add Hunter.io Starter | +$49/mo | 5,000 enrichments/month — unblocks larger cities |
| Revenue $5k+/mo | Add Apollo.io ($79/mo) | +$79/mo | Better email find rate than Hunter at scale |

**Never upgrade pre-revenue.** Every upgrade only happens after a specific volume threshold + sales validation.

---

## Files added for the $0 path

This document covers strategy. The matching exporter:

- `scripts/export_mailmeteor.py` — exports sequences to a Google-Sheets-friendly CSV for Mailmeteor (similar to `export_sequences_csv.py` but optimized for Mailmeteor's column expectations)

Run it after generating a campaign:

```bash
python3 scripts/local_prospect_run.py --all --location "Boston, MA" --limit 30 --live
python3 scripts/export_mailmeteor.py \\
    --sequences data/launches/siteboost/runs/<date>/04-sequences.json \\
    --out mailmeteor_upload.csv

# Then: upload mailmeteor_upload.csv to Google Sheets → run Mailmeteor → send.
```

---

## TL;DR — what to do today on the zero-budget path

1. **Cloudflare** → enable Email Routing → forward `hello@wheellsverse.com` → your existing Gmail (5 min, free)
2. **SendGrid Free** → sign up → verify sender → add API key → wire into Gmail "Send mail as" (15 min, free)
3. **Mailmeteor** → install from Google Workspace marketplace (3 min, free)
4. **Calendly Free** → create 1 event type (5 min, free)
5. **Get Google Places + Hunter free-tier keys** ([TASK-4-API-KEYS.md](TASK-4-API-KEYS.md), 15 min, free)
6. **Add 4 env vars** to `.env`:
   ```
   SITEBOOST_OUTBOUND_DOMAIN=hello.wheellsverse.com
   SITEBOOST_SMTP_USER=hello@wheellsverse.com
   SITEBOOST_PHYSICAL_ADDRESS=Your Real Address · City, ST USA
   GOOGLE_PLACES_API_KEY=...
   HUNTER_API_KEY=...
   ```
7. **Run** `python3 scripts/siteboost_status.py` → expect 5 ✓ env, DNS partial, calendly URL needs replace
8. **Run a real scan**: `python3 scripts/local_prospect_run.py --scan --location "Boston, MA" --limit 30 --live` → 30 real prospects
9. **Export to Mailmeteor**: `python3 scripts/export_mailmeteor.py ...`
10. **Send 5-10 today** from Gmail via Mailmeteor (warmup yourself by starting small)

**Total monthly cost so far: $0. Total time to first cold email: ~1 hour.**
