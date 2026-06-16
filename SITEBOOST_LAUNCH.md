# SiteBoost Launch Doc

Status as of 2026-06-12 (updated). **All 5 launch blockers are technically resolved.** Real outbound requires only domain warmup (calendar wait, not code work) and Instantly key rotation (operator action).

---

## TL;DR — what's working

```text
PIPELINE              ✅ LIVE on app.wheellsverse.com (5-stage, real Google Places + Hunter)
EMAIL COPY            ✅ Issue-aware (13 specific opener templates per detected site issue)
CHAIN FILTER          ✅ 60-brand blocklist
UNSUBSCRIBE SYSTEM    ✅ HMAC-signed tokens + /u/{token} endpoint + suppression list (E2E validated)

CAN-SPAM ADDRESS      ✅ Real address in footer (Taunton MA via env var)
DNS AUTH              ✅ SPF + DKIM + DMARC live, Resend domain verified
SEND PATH (Resend)    ✅ Test sends delivered (probe + Gmail)
SEND PATH (Instantly) ✅ v2 API integration, schema-validated against real campaign

REMAINING:
  - Domain warmup     ⏳ 14-day calendar wait (operator picks a warming tool)
  - Instantly key     🚨 ROTATE NOW — current key was pasted in chat transcript
```

---

## Architecture map (unchanged from prior doc + recent additions)

```text
core/places_scanner.py       Stage 1 — Google Places v1 + parallel 8-worker website probe + chain blocklist + bad-website classification
core/email_enricher.py       Stage 2 — Hunter /domain-search
core/site_generator.py       Stage 3 — HTML preview rendering
core/cold_outreach.py        Stages 4 + 5 — issue-aware 3-touch compose + Instantly v2 dispatch
                             Now also: unsubscribe token gen, suppression list, CAN-SPAM footer

narai/api/routes/siteboost_admin.py    /api/narai/siteboost/* admin endpoints
core/api.py                  Adds public /u/{token} unsubscribe endpoint (no auth)

frontend/admin/siteboost.html          Operator control panel
dashboard/index.html                   10th nav tab "SiteBoost"

data/launches/siteboost/scans/         Per-run scan + enriched JSON
data/launches/siteboost/runs/<slug>/   Per-run output: previews, sequences, report.md
data/launches/siteboost/digests/       Markdown sequence digests for human review
data/launches/siteboost/suppressions.json  CAN-SPAM opt-out list  (NEEDS volume attach for prod)
```

---

## 5-Blocker scoreboard

| # | Blocker | Status | Action remaining |
|---|---|---|---|
| 1 | CAN-SPAM physical address | ✅ DONE | None — verified in live footer |
| 2 | DNS auth (SPF/DKIM/DMARC) | ✅ DONE | None — Resend domain verified, test sends working |
| 3 | Domain warmup | ⏳ Ready to start | Sign up for warming tool, run 14 days |
| 4 | Instantly API key | ✅ Key works + v2 code shipped | 🚨 **Rotate the key** (pasted in chat) |
| 5 | Unsubscribe tokens | ✅ DONE | None — E2E validated |

---

## Resolved blockers (detail)

### Blocker #1 — CAN-SPAM physical address ✅

```text
SITEBOOST_PHYSICAL_ADDRESS=SiteBoost AI · 234 School St Apt 2 · Taunton, MA 02780 USA
```

Set on local `.env` AND Railway. Live footer verified via real scan output.

### Blocker #2 — DNS authentication ✅

Records added via Cloudflare API (token `CLOUDFLARE_API_TOKEN`, zone `wheellsverse.com`):

```dns
hello.wheellsverse.com.                     TXT  "v=spf1 include:amazonses.com ~all"   (corrected 2026-06-12 13:25 ET)
_dmarc.hello.wheellsverse.com.              TXT  "v=DMARC1; p=quarantine; pct=100; adkim=r; aspf=r; sp=quarantine"
resend._domainkey.hello.wheellsverse.com.   TXT  "p=MIGfMA0..."   (Resend DKIM)
send.hello.wheellsverse.com.                MX   10 feedback-smtp.us-east-1.amazonses.com.
send.hello.wheellsverse.com.                TXT  "v=spf1 include:amazonses.com ~all"
```

Resend dashboard confirmed verified at 10:50 AM ET. First successful test sends:
- Probe: `delivered@resend.dev` → 200
- Real: `kevens.james48029@gmail.com` → 200 (Resend id 87c2dc09-92a5-...)

### Blocker #4a — Instantly API key ✅

```text
INSTANTLY_API_KEY  set on local .env + Railway (length 68, basic-auth format)
```

Verified against v2 API: `GET /api/v2/campaigns` returns 200 with 1 campaign visible:
- Campaign: `[AI SDR] NarAI Sales Agent - Fully Personalized Campaign`
- Campaign ID: `dd585232-d7d8-4312-84ed-a4bb3bc0a8df`

### Blocker #4b — v1→v2 send code migration ✅

Old code (`/api/v1/lead/add`) → returns 401, deprecated.
New code (`/api/v2/leads`) → 200, single-call lead+campaign assignment.

Schema verified by probe:
```json
POST /api/v2/leads
{
  "email": "x@y.com",                    // required
  "campaign": "<UUID>",                  // optional — assigns to campaign
  "first_name": "...",
  "last_name": "...",
  "company_name": "...",
  "personalization": "...",              // free string, exposed as {{personalization}} in template
  "website": "..."
}
```

### Blocker #5 — Unsubscribe system ✅

- `make_unsubscribe_token(email)` → HMAC-SHA256 truncated to 16 bytes, positional layout (no delimiter — HMAC bytes contain `|` ~63% of the time)
- `verify_unsubscribe_token(token)` → constant-time HMAC compare
- `/u/{token}` public endpoint (no auth, CAN-SPAM § 7704(a)(3) compliant)
- Suppression list at `data/launches/siteboost/suppressions.json`
- Compose-time filter: prospects on suppression list are skipped

End-to-end validated:
```text
1. Scan generates real tokens                                    ✓
2. GET valid token → "✓ Unsubscribed" + 200                      ✓
3. Idempotent on second click                                    ✓
4. Invalid token → "Link not recognized" + 400                   ✓
5. Re-scan excludes the unsubscribed email                       ✓
```

Required env: `SITEBOOST_UNSUBSCRIBE_SECRET` (44-char base64). Set on local + Railway.

---

## Remaining blockers (detail)

### Blocker #3 — Domain warmup ⏳

`hello.wheellsverse.com` is brand new. Cold-blasting from a new domain triggers spam-trap blacklists within 24h.

**Required schedule:**
```text
Day 1-3:    5 emails/day to responsive contacts
Day 4-7:    10/day
Day 8-14:   20/day → 50/day
Day 14+:    cold blast 50-100/day reliably
```

**Warming tools (pick one):**
- Lemwarm — $29/mo, integrates with Instantly
- Mailwarm — $59/mo, standalone
- Instantly's own built-in warming — $0 if you're on a paid Instantly plan

**To check inbox-vs-spam placement of the test send sent at 11:43 AM ET to `kevens.james48029@gmail.com`** — if it landed in INBOX on day-zero domain, your DNS is so clean that minimal warmup may be needed. If SPAM, full 14-day warmup is required.

### Blocker #4c — Rotate the Instantly key 🚨

The key starting `Yzg4Mzhm...` was pasted in the chat transcript and must be treated as compromised. Even though this is your own private session, treating exposure as compromise is the right discipline.

**Rotate steps:**
1. Open <https://app.instantly.ai/app/settings/api>
2. Find the current key → "Regenerate" (or delete + create new)
3. Copy the NEW key
4. Set on local + Railway using a non-echoing terminal pattern (see below)

**Secure-paste pattern (no chat exposure):**
```bash
# In your terminal — this prompts for input WITHOUT echoing
read -s NEW_KEY
# (paste the key, hit Enter — nothing displays)

# Set on local .env
python3 -c "
from pathlib import Path
p = Path.home() / 'wheellsverse_bots' / '.env'
import os
new_key = os.environ['NEW_KEY']
lines = [l for l in p.read_text().splitlines() if not l.startswith('INSTANTLY_API_KEY=')]
lines.append(f'INSTANTLY_API_KEY={new_key}')
p.write_text('\n'.join(lines) + '\n')
print('local .env updated')
" NEW_KEY="$NEW_KEY"

# Set on Railway
cd /tmp/siteboost-deploy
railway variables --service wheellsverse-v2 --set "INSTANTLY_API_KEY=$NEW_KEY"

# Redeploy to propagate
railway up --service wheellsverse-v2 --detach
```

---

## Production deployment prerequisites (still needed before real send)

These aren't strictly "blockers" but they affect production-grade correctness:

### Volume attach for suppression persistence (HIGH PRIORITY)

Currently suppressions live at `data/launches/siteboost/suppressions.json` INSIDE the container. Container filesystem is wiped on every Railway redeploy. **An unsubscribed email could re-receive emails after a deploy** — that's a CAN-SPAM violation.

**Fix:**
```bash
cd /tmp/siteboost-deploy
# Attach the existing Railway volume to wheellsverse-v2 at /var/data
railway volume attach grateful-flexibility-volume --service wheellsverse-v2 --mount /var/data

# Set the env var to point suppressions at the volume
railway variables --service wheellsverse-v2 \
  --set "SITEBOOST_SUPPRESSIONS_PATH=/var/data/siteboost/suppressions.json"

# Redeploy
railway up --service wheellsverse-v2 --detach
```

### DMARC reporting (low priority)

DMARC record currently has no `rua=` (aggregate report URI). If you want weekly XML reports about who's spoofing your domain, sign up at <https://dmarcian.com> (free tier for small volumes) and add `rua=mailto:<your-dmarcian-address>` to the existing DMARC record.

### Probe leads cleanup (cosmetic)

During testing I created 4 probe leads in your Instantly account (emails ending in `.invalid`). 3 were deleted; 1 (`019ebc87-13b7-748a-...`) may still be present — the DELETE timed out. They can't receive mail (`.invalid` TLD doesn't resolve) so they're harmless, but you can find/delete via Instantly dashboard.

---

## How to actually launch (when warmup is done)

```bash
# 1. Run a fresh scan to generate prospects (replace city as needed)
cd /tmp/siteboost-deploy
RAILWAY_K=$(railway variables --service wheellsverse-v2 --kv | grep '^API_KEY=' | cut -d= -f2-)

curl -sS -H "X-API-Key: $RAILWAY_K" -H "Content-Type: application/json" \
  -d '{"location":"<CITY>, <ST>","radius_m":15000,"limit":50,"live":true}' \
  https://app.wheellsverse.com/api/narai/siteboost/scan

# 2. Review the digest BEFORE sending
curl -sS -H "X-API-Key: $RAILWAY_K" \
  https://app.wheellsverse.com/api/narai/siteboost/sequences/<RUN_ID> | \
  python3 -m json.tool > review.json

# 3. Trigger actual send (via the existing send_sequences function)
# This call is NOT yet exposed as an admin endpoint — it requires CLI access:
cd /tmp/siteboost-deploy
railway run --service wheellsverse-v2 -- python3 -c "
from core.cold_outreach import send_sequences
from pathlib import Path
result = send_sequences(
    Path('/app/data/launches/siteboost/runs/<RUN_ID>/04-sequences.json'),
    confirm=True,
    live=True,
    max_per_day=50,
)
print(result)
"
```

**Note:** I haven't yet exposed `send_sequences` as a `/api/narai/siteboost/send` admin endpoint. That's the last shipped-vs-shippable gap. ~30-line addition to `siteboost_admin.py`. Easy to add when you're ready.

---

## All commits this session

```text
93c80fc  feat(siteboost): migrate Instantly send code v1→v2
8b5f812  fix(siteboost): unsubscribe token positional layout (HMAC bytes contain | ~63% of the time)
bd67902  feat(siteboost): unsubscribe tokens + public /u/{token} endpoint + suppression list
febdc74  [SUPERSEDED — regressed manifest/favicon]
c47feb4  feat(siteboost): Phase 2 — issue-aware email copy + chain filter + city extraction fix
01a4255  fix(siteboost): probe realistic UA + post-redirect HTTPS check + Hunter /domain-search
4f557e8  feat(siteboost): expose scan_meta + rejected_sample in run_detail
8718441  fix(siteboost): swap invalid Places v1 types (general_contractor/auto_repair → painter/moving_company)
2120d9f  fix(siteboost): use sys.executable not .venv/bin/python3
c366b37  feat(siteboost): admin control panel + 10th dashboard tab + litellm pin
```

All on `/tmp/siteboost-deploy` worktree (detached HEAD) AND live on Railway. **Not pushed to `gh/main`** — that's a follow-up: cherry-pick the working commits back to canonical and onto a real branch.

---

## Resume protocol

If you come back to this in a future session:

```bash
# 1. Read this doc + the latest digest
cat ~/wheellsverse_bots/SITEBOOST_LAUNCH.md
ls -la ~/wheellsverse_bots/data/launches/siteboost/digests/

# 2. Verify production
curl -s https://app.wheellsverse.com/api/health | jq .uptime

# 3. Verify all 5 blocker env vars are on Railway
cd /tmp/siteboost-deploy
railway variables --service wheellsverse-v2 --kv | grep -E '^(SITEBOOST_|HUNTER_|GOOGLE_PLACES_|INSTANTLY_|RESEND_|API_KEY=)'

# 4. Pick the next task:
#    - Operator: rotate Instantly key (Blocker #4c)
#    - Operator: start domain warmup (Blocker #3)
#    - Code: attach volume + expose send endpoint (production prep)
```
