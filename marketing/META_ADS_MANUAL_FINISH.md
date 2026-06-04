# Path A — Finish the $5/day Meta Ad in Ads Manager UI (~60 seconds)

**Use this until App Review approves the app and the SDK script clears all 5 steps.** See [META_APP_REVIEW_SUBMISSION.md](META_APP_REVIEW_SUBMISSION.md) for the path to unlocking full API automation.

You have THREE orphan campaigns the script already created. You can either reuse one (saves clicks) or create a fresh one. Reusing is faster.

| Campaign ID | Account | What's there | Recommended action |
|---|---|---|---|
| `120249191180470279` | wheellsverse's ad account `2184028352358996` | campaign only (no adset) | delete |
| `120249191226470279` | wheellsverse's ad account `2184028352358996` | campaign + adset (PAUSED, $5/day, US 25-55) | **REUSE** — just add the ad creative |
| `120249191226830279` (adset under above) | same | adset PAUSED, all targeting + budget configured | finish here |
| `52523425279491`, `52523425328291`, `52523428078091`, `52523428100891` | sandbox account `1645608886719041` | sandbox orphans | delete (sandbox accounts can't serve real ads) |

The recommended path: **finish the existing PAUSED adset `120249191226830279`** by adding one ad to it. You've already paid $0 — campaign + adset are PAUSED and stay that way until you flip to Active.

---

## The 9 clicks

1. **Open Ads Manager** → https://business.facebook.com/adsmanager
2. **Top-right account picker** → select **wheellsverse's ad account** (id `act_2184028352358996`)
3. **Top-left Campaigns tab** → search **toodle_test_01** → click into the row that has an ad set under it (not the orphan)
4. **Click into the Ad Set tab** for that campaign → confirm:
   - Daily budget: $5.00
   - Optimization: Link clicks
   - Targeting: US, age 25-55
   - Status: PAUSED ← this stays PAUSED until step 9
5. **Click "+ Create Ad"** at the top of the Ad Set view
6. **Format** → **Single image or video** → upload **`assets/meta_ad_creative_v1.png`** from your repo
   *(or click "Choose from media library" — Meta should have the image already; hash `7f303a0e18336f79c2f805dbd455093f` from earlier uploads)*
7. **Fill the ad fields exactly:**
   | Field | Value |
   |---|---|
   | Identity → Facebook Page | **Wheellsverse** (the main brand Page, id `828774486991832`) |
   | Identity → Instagram account | optional — pick if you have one connected |
   | Primary text | `Build with AI. Not just read about it. The 4-tool method to your first product. Free Blueprint inside.` |
   | Headline | `Get the Free Blueprint` *(or leave blank — Meta will auto-pull from the URL)* |
   | Description | leave blank |
   | Website URL | `https://wheellsverse-bots.pages.dev/blueprint.pdf?utm_source=meta&utm_medium=cpc&utm_campaign=toodle_test_01` |
   | Call to action | **Learn More** |
   | Display link | leave default |
8. **Preview** the ad on the right pane → confirm:
   - The cyan ad creative renders cleanly
   - The "Learn More" button shows
   - The destination URL has UTMs (hover the link)
9. **Publish** → because the ad set is PAUSED, the ad will land as PAUSED inside a PAUSED ad set. **No spend.** Confirm "Status: Off" on the Ads row.

---

## When you're ready for traffic

1. Open the campaign in Ads Manager.
2. Toggle the **campaign** → on.
3. Toggle the **ad set** → on.
4. Toggle the **ad** → on.

Meta will queue an ad review (~30 minutes typical, up to 24h). Once Meta approves the ad, it starts serving. First clicks will hit the Toodle Capture endpoint on `:5052/toodle/capture` and trigger the full nurture loop you've already verified end-to-end.

---

## What's already verified end-to-end (no need to retest)

| Stage | Verified by |
|---|---|
| Landing: `blueprint.pdf` serves real PDF | `curl -sI https://wheellsverse-bots.pages.dev/blueprint.pdf` → `content-type: application/pdf` |
| Capture endpoint creates real Kit subscriber | Live test created subscriber_id `4145058365` in your Kit account |
| Queue scheduling | 7 rows scheduled across 2 captures (5 KDP + 2 Welcome) with proper +0/+1/+3/+5/+7 day timing |
| SMTP dispatch | Email 1 actually arrived at `kevens.james48029+toodlefirst@gmail.com` |
| Cron | `*/15 * * * *` installed — Email 2 fires automatically ~23h after Email 1 |

So the only thing waiting on you is steps 1-9 above. After step 4 (toggle to Active), traffic begins, captures flow in, the funnel runs.

---

## Killing the orphans (cleanup, when convenient)

```text
Ads Manager → Campaigns tab → filter by name "toodle_"
Select all PAUSED orphans EXCEPT toodle_test_01 (the one with the new ad)
→ ... menu → Delete

Sandbox account orphans:
Ads Manager → Account picker → New Sandbox Ad Account
→ select all → Delete
(Sandbox campaigns never serve real ads regardless — pure cleanup.)
```

Doesn't affect anything functional.
