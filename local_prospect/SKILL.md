---
name: market-local-prospect
description: "Find local businesses without a website, generate a custom site preview for each, draft a personalized cold email, and route replies to a sales pipeline. End-to-end lead-gen for the SiteBoost product. Use when user says: scan for local prospects, find businesses without websites, prospect local businesses, run SiteBoost campaign, generate cold emails for local biz, build site previews for prospects, or local outbound campaign."
user-invokable: true
tested_date: 2026-06-02
tested_with: claude-code v2.x
---

# Market: Local Prospect — SiteBoost Outbound Engine

End-to-end pipeline that finds local businesses without websites, generates
custom site previews, and queues personalized cold-email outreach offering to
sell them the site. Designed for human-in-the-loop approval before send.

## Process

This skill orchestrates 5 stages. Each stage writes to disk so you can
inspect/edit between stages. Default mode is `--dry-run` (uses fake data,
no API calls, no emails sent) until you flip `--live` flags explicitly.

### Stage 1 — Scan (Google Places API)

```bash
python scripts/local_prospect_run.py --scan \
    --location "Boston, MA" --radius 5000 \
    --categories restaurant,salon,plumber,electrician,dentist --limit 100
```

Writes `data/launches/siteboost/scans/<date>-<location>.json`. Filters to
businesses with no `website` field.

### Stage 2 — Enrich (Hunter.io / Apollo)

```bash
python scripts/local_prospect_run.py --enrich --scan <scan-file>
```

### Stage 3 — Generate (Site previews)

```bash
python scripts/local_prospect_run.py --generate --enriched <enriched-file>
```

Picks template by category, personalizes copy, hosts under
`https://preview.wheellsverse.com/<slug>` (Cloudflare Pages).

### Stage 4 — Compose (Cold emails)

```bash
python scripts/local_prospect_run.py --compose --generated <final-file>
```

3-email sequence per prospect with CAN-SPAM compliant footer.

### Stage 5 — Send

```bash
python scripts/local_prospect_run.py --send --sequences <seq-file> --confirm
```

Refuses without `--confirm` AND active domain warmup.

## Required env vars

- `GOOGLE_PLACES_API_KEY`
- `HUNTER_API_KEY`
- `SITEBOOST_OUTBOUND_DOMAIN` (separate from wheellsverse.com)
- `INSTANTLY_API_KEY` (optional — can export CSV instead)
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (for personalization)

## Quality gates (auto-enforced)

- Dry-run default; `--live` required per stage
- Send gate: `--confirm` + warmup status check
- Max 50 emails/day per domain
- CAN-SPAM footer hardcoded
- Auto-skips EU/UK/DE/FR businesses (GDPR)

## Output

For each campaign in `data/launches/siteboost/runs/<date>-<location>/`:
- `01-scan.json` · `02-enriched.json` · `03-previews/` · `04-sequences.json` · `05-report.md`

## See also
- [PRODUCT-BRIEF.md](../data/launches/siteboost/PRODUCT-BRIEF.md)
- [README-MORNING.md](../data/launches/siteboost/README-MORNING.md)
- [scripts/local_prospect_run.py](../scripts/local_prospect_run.py)
- [narai/tools/local_prospect_tool.py](../narai/tools/local_prospect_tool.py)
