# Task 4 — Getting Your API Keys (15 minutes total)

Two API keys needed. Both have free tiers that cover your first 2-3 months easily.

---

## A. Google Places API Key (8 minutes, $0 to start)

The Places API is part of Google Cloud Platform. Free tier = $200/month credit
covers ~6,000 detail lookups, way more than you'll need in the early phase.

### Step 1 — Sign in to Google Cloud Console

Go to **https://console.cloud.google.com**

Sign in with the Gmail you want to use for billing (same Google account that has Google Workspace later is fine — or a separate personal Gmail).

### Step 2 — Create a project

1. Top-left → project dropdown → **NEW PROJECT**
2. Project name: `siteboost-prod` (or anything)
3. Click **CREATE**
4. Wait 30 seconds for the project to provision
5. Top-left dropdown → select `siteboost-prod`

### Step 3 — Enable billing

Even though the free tier covers you, Google requires a billing account on file.

1. Left sidebar → **Billing**
2. **LINK A BILLING ACCOUNT** → set up a new one if you don't have one
3. Enter card details (you will NOT be charged for normal usage — $200 free credit/mo)
4. Confirm

### Step 4 — Enable the right APIs

1. Top search bar → search `Places API`
2. Click **Places API (New)** — this is the v1 API the scanner uses
3. Click **ENABLE**
4. Wait 30 seconds
5. Top search bar again → search `Geocoding API`
6. Click **Geocoding API** → **ENABLE**

(The scanner needs both — Geocoding turns "Boston, MA" into lat/lng, then Places searches by lat/lng.)

### Step 5 — Generate the API key

1. Left sidebar → **APIs & Services** → **Credentials**
2. Top → **+ CREATE CREDENTIALS** → **API key**
3. Google shows a popup with the key. **COPY IT NOW.**
4. Click **EDIT API KEY**
5. Name it `SiteBoost Places + Geocoding`
6. Under **API restrictions** → **Restrict key** → check `Places API (New)` and `Geocoding API` only
7. **SAVE**

### Step 6 — Add to your .env

Open `.env` in your repo:

```bash
cd /Volumes/Wheellsverse/wheellsverse-bots
nano .env
# or
code .env
```

Add this line (paste the key from step 5):

```
GOOGLE_PLACES_API_KEY=AIza...your_key_here
```

### Step 7 — Test it

```bash
python3 -c "
import os
os.environ.setdefault('GOOGLE_PLACES_API_KEY', open('.env').read().split('GOOGLE_PLACES_API_KEY=')[1].split('\n')[0].strip())
import sys; sys.path.insert(0, '.')
from core.places_scanner import _geocode, _api_key
lat, lng, country = _geocode('Boston, MA', _api_key())
print(f'OK · Boston is at ({lat}, {lng}), country={country}')
"
```

Expected output:
```
OK · Boston is at (42.3601, -71.0589), country=US
```

If you see that, the key works.

### Cost check after first test

In Cloud Console → Billing → Reports. After 5 test queries you should see ~$0.05 spent. The $200/mo free credit refills automatically.

---

## B. Hunter.io API Key (3 minutes, $0 to start)

Free tier: 50 lookups/month. Enough for testing — upgrade to $49/mo (5,000 lookups) once you scale past Boston.

### Step 1 — Sign up

Go to **https://hunter.io/sign-up**

Sign up with your **outbound email** (e.g. `jay@hello.wheellsverse.com` once you have it, or your Gmail for now — you can change later).

Verify the email link they send you.

### Step 2 — Grab the key

1. After login → click your avatar (top-right) → **API**
2. Direct URL: **https://hunter.io/api-keys**
3. Copy the value under **Production API Key**

### Step 3 — Add to your .env

```
HUNTER_API_KEY=...your_key_here...
```

### Step 4 — Test it

```bash
python3 -c "
import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('HUNTER_API_KEY', open('.env').read().split('HUNTER_API_KEY=')[1].split('\n')[0].strip())
from core.email_enricher import _hunter_company_search, _hunter_key
result = _hunter_company_search('Microsoft', _hunter_key())
print(f'OK · Hunter test result: {result}')
"
```

If you see any non-None result, the key works.

(Note: this test burns 1 of your 50 free lookups. Don't run it more than once.)

---

## C. Anthropic API Key (optional, $0 to start, only for live site personalization)

The `site_generator.py` module uses Claude to write personalized site copy when running in `--live` mode. In dry-run, defaults are used (no API call). If you want polished copy on the LIVE pipeline, add an Anthropic key.

### Step 1 — Sign up

Go to **https://console.anthropic.com/sign-up**

Free credit: typically $5 on signup — enough to personalize ~500 sites.

### Step 2 — Generate key

1. Console → **API Keys** → **Create Key**
2. Name it `SiteBoost`
3. Copy the `sk-ant-...` key

### Step 3 — Add to .env

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Step 4 — Test

```bash
python3 -c "
import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('ANTHROPIC_API_KEY', open('.env').read().split('ANTHROPIC_API_KEY=')[1].split('\n')[0].strip())
from core.site_generator import _llm_personalize
result = _llm_personalize({'name': 'Mama Lupita Tortilleria', 'category': 'restaurant', 'address': 'Boston, MA'})
print(f'Headline: {result[\"hero_headline\"]}')
print(f'Sub: {result[\"hero_sub\"]}')
"
```

---

## All three keys at once — quick verification

After adding all 3 to `.env`:

```bash
cd /Volumes/Wheellsverse/wheellsverse-bots
python3 -c "
import os
env = {l.split('=')[0]: l.split('=',1)[1].strip() for l in open('.env').read().split('\n') if '=' in l and not l.startswith('#')}
checks = ['GOOGLE_PLACES_API_KEY', 'HUNTER_API_KEY', 'ANTHROPIC_API_KEY']
for k in checks:
    v = env.get(k, '')
    print(f'  {k}: ' + ('✓ set' if v else '✗ MISSING'))
"
```

Once Google + Hunter both say `✓ set`, you can run the first LIVE scan:

```bash
python3 scripts/local_prospect_run.py --scan --location "your city, ST" --limit 5 --live
```

That'll cost ~$0.05-0.10 and produce 5 real prospects. From there, the pipeline is alive.

---

## Cost ceiling for first 90 days

| API | Free tier covers | When to upgrade |
|---|---|---|
| Google Places | ~6,000 scans/mo | After scanning ~5 cities × 100 prospects/each |
| Hunter | 50 lookups/mo | Immediately upgrade ($49/mo for 5k) if you scan more than 1 city |
| Anthropic | $5 credit (~500 sites) | After 500 personalizations — bump to pay-as-you-go |

Total ongoing cost in month 1: $0 (Google + Anthropic free, Hunter 50/mo free). Month 2+: $49 (Hunter only) until you scale past 5k lookups/month.
