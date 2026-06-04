# Meta App Review — Submission Packet for app `862248986827522`

**Status:** all artifacts prepared. Submit when ready.
**Estimated time at the console:** ~15 minutes (paste values + record screencast)
**Review wait time:** 3–7 business days after submit.

This packet contains every field you need to paste into the App Review form at https://developers.facebook.com/apps/862248986827522/app-review/. Work top-to-bottom — each section maps to one panel in the dashboard.

---

## 0. Pre-flight: deploy the data-deletion endpoint

This is the only piece that has to be live BEFORE submitting. Meta's reviewers will hit it.

### What I've built
- Code: [narai/api/routes/meta.py](../narai/api/routes/meta.py)
- Mounted in: [narai/api/main.py](../narai/api/main.py) at root (no `/api/v2/narai` prefix)
- Three routes:
  - `POST /meta/data-deletion` — receives signed_request, returns confirmation_code
  - `GET /meta/data-deletion/status?code=<code>` — public status lookup
  - `GET /meta/data-deletion/health` — pre-flight ping for reviewers

### What you do
1. Add `META_APP_SECRET` to `.env` — generate at https://developers.facebook.com/apps/862248986827522/settings/basic/
2. Add `APP_BASE_URL=https://<your public host>` to `.env` — see step 3
3. Make the daemon reachable from the public internet. Three options:
   - **Cloudflare Tunnel** (recommended, free, ~5 min setup): `brew install cloudflared && cloudflared tunnel --url http://localhost:5051`
   - **ngrok** (free tier, URL changes on restart): `ngrok http 5051`
   - **VPS or Railway redeploy**: real public domain, but more setup
4. Verify the endpoint is reachable:
   ```bash
   curl https://<your-public-host>/meta/data-deletion/health
   # expected: {"ok":true,"app_secret_configured":true,"now_utc":"..."}
   ```
5. Copy that public host URL — you'll paste it as the **Data Deletion Callback URL** in section 1 below.

---

## 1. App Dashboard → Settings → Basic

Paste these values:

| Field | Value |
|---|---|
| Privacy Policy URL | `https://wheellsverse-bots.pages.dev/privacy` |
| Terms of Service URL | `https://wheellsverse-bots.pages.dev/terms` |
| User Data Deletion → **Callback URL** | `https://<your-public-host>/meta/data-deletion` |
| App Domains | `wheellsverse-bots.pages.dev` |
| Category | Business and Pages |
| Contact Email | kevens.james48029@gmail.com |
| Site URL | `https://wheellsverse-bots.pages.dev` |

---

## 2. Business Verification

Required for `ads_management`, `business_management`, `ads_read`. Open https://business.facebook.com/settings/security and verify the **WheellsVerse** business with:

- Government-issued ID for Kevens James
- Business registration document (sole proprietor declaration if applicable in your jurisdiction)
- Proof of address (utility bill or bank statement, last 90 days)

Allow up to 3 business days. App Review submission below can be drafted in parallel but won't be reviewed until verification completes.

---

## 3. App Review → Permissions and Features

For each permission, paste the listed answers verbatim. Each permission needs a screencast — see section 4 for the screencast script that covers all of them in one ~3-min recording.

### `ads_management`

**How will you use this permission?**
> WheellsVerse runs a self-serve marketing automation product (codename: Toodle) that creates Meta ads programmatically for the account owner. The user authenticates with their own Facebook account, grants ads_management permission to our app, and the app creates campaigns, ad sets, and ads in their own ad account. Campaigns are always created in PAUSED state — the user reviews and activates them manually in Ads Manager. We never spend the user's budget without their explicit activation.

**Step-by-step instructions for testing:**
> 1. Visit https://wheellsverse-bots.pages.dev and click "Connect Meta Account"
> 2. Log in with a Test User account (provided below)
> 3. Grant ads_management permission when prompted
> 4. Open the dashboard at /dashboard — confirm the user's ad accounts are listed
> 5. Click "Create Test Campaign" — verify a PAUSED campaign appears in the test ad account
> 6. The campaign uses objective=OUTCOME_TRAFFIC, daily_budget=$5.00, never activates without user click

### `ads_read`

**How will you use this permission?**
> To read back the campaign / ad set / ad we just created, verify they're in PAUSED state, and surface delivery metrics (impressions, clicks, CPC) once the user activates the campaign. Used exclusively for verification and reporting — never for cross-account ad intelligence.

**Step-by-step instructions for testing:**
> Same screencast as ads_management. After campaign creation, the dashboard fetches and displays the campaign's status, name, and budget via the ads_read permission.

### `business_management`

**How will you use this permission?**
> To list the user's ad accounts (so they can pick which one to use) and verify the ad account is owned by their Business Manager. Used only at connect time and for showing the picker UI — we don't modify any business assets.

**Step-by-step instructions for testing:**
> During the Connect Meta Account flow, the dashboard calls /me/businesses and /me/adaccounts to populate the account picker. The user picks one and we never touch the others.

### `pages_show_list`

**How will you use this permission?**
> To list the Facebook Pages the user owns so they can pick which Page the ad will publish from. Required because Meta ads must publish "as" a Page — the user selects which one.

### `pages_read_engagement`

**How will you use this permission?**
> To verify the selected Page is active and can publish ads (Meta requires this permission to create ads that reference a Page in their object_story_spec).

---

## 4. Screencast script (covers all 5 permissions in ~3 minutes)

Record at 1280×720 minimum. Use any screen recorder (QuickTime ⌘+⇧+5, OBS, Loom).

```
[0:00] Open https://wheellsverse-bots.pages.dev — show landing page briefly.
[0:10] Click "Connect Meta Account" — show the FB login dialog.
       Log in as the Test User (credentials in section 5).
[0:25] Show the permissions dialog clearly — every requested scope visible.
       Click "Allow".
[0:40] Show the dashboard at /dashboard. Point out the list of ad accounts
       (pages_show_list, business_management, ads_read in action).
[1:00] Click "Create Test Campaign" — show the form filled in with:
       - Campaign name: app_review_demo
       - Daily budget: $5.00
       - Country: US, Age: 25-55
       - Image: any placeholder
       - CTA: Learn More
[1:30] Click Submit — wait for the success screen showing the new
       campaign_id, adset_id, ad_id (ads_management in action).
[2:00] Navigate to https://business.facebook.com/adsmanager — find the
       new PAUSED campaign by name. Show that status is PAUSED.
       (This proves we don't activate without consent — critical.)
[2:30] Back to the dashboard. Click "Refresh Stats" — show the campaign
       status flowing back into the UI (ads_read in action).
[2:50] Click "Disconnect Meta Account" — show that data is removed and
       user is redirected to the data deletion confirmation page.
[3:00] End.
```

If you don't have a UI built for this flow yet, record it with the existing API smoke test (run `scripts/meta_first_ad_sdk.py` in a terminal next to Ads Manager). Less polished but acceptable — Meta cares that you actually use each permission for the stated purpose, not that the demo is beautiful.

---

## 5. Test User Account

Create at https://developers.facebook.com/apps/862248986827522/roles/test-users/. Generate one test user, add it to the Test Users list, give the credentials to Meta in this field:

```
Test User credentials for review:
  Email: <test_user_email_meta_generates>
  Password: <test_user_password_meta_generates>

Login flow: visit https://wheellsverse-bots.pages.dev → "Connect Meta Account"
After login, all requested permissions can be exercised through the dashboard.
```

The test user is automatically granted access to your app — Meta's reviewers use this exact account.

---

## 6. Data Use Checkup

Meta will ask:

> Will this data leave Meta's platform?

**Answer:** "Yes. We store the user's ad account ID, Page ID, and the IDs of campaigns/ad sets/ads we create on their behalf in our own database (PostgreSQL on Supabase). We do NOT store user tokens — we use them at request-time only. We do NOT store any personal data about the user's customers, leads, or audience. We retain the IDs only as long as the user's account is active; on disconnect or data deletion request, we purge all stored IDs within 30 days."

> Will you share the data with third parties?

**Answer:** "No."

---

## 7. Submission checklist

Before clicking **Submit for Review** in the App Dashboard:

- [ ] Privacy Policy URL loads (200) and mentions Facebook data
- [ ] Terms of Service URL loads (200)
- [ ] Data Deletion Callback URL loads (POST returns 400 without signed_request — that's expected)
- [ ] Business Verification: at least submitted, ideally complete
- [ ] All 5 permission justifications pasted from section 3
- [ ] Screencast uploaded (one video covers all permissions)
- [ ] Test User created in the app's Test Users list
- [ ] Test User credentials pasted in the App Review form
- [ ] App icon uploaded (1024×1024 PNG — Cloudflare cover image at `assets/ai_entrepreneur_blueprint_cover.png` works in a pinch; ideally a clean app icon)
- [ ] App switched to Live mode is NOT YET required — only after review passes

---

## After Submission

Track status at https://developers.facebook.com/apps/862248986827522/app-review/submissions/.

Meta reviewers may come back with one of:

- **Approved**: switch the app to Live mode in Settings → Basic. `scripts/meta_first_ad_sdk.py` will now succeed at all 5 steps (step 4 was the blocker tonight). The full Toodle Ads Agent runs end-to-end.
- **Changes Requested**: usually a screencast issue (didn't clearly show the permission being used). Re-record + resubmit — usually approved within 24h of resubmit.
- **Rejected**: rare for legitimate use cases. Usually means the permission's use case is too vague. Tighten the language in section 3 and resubmit.

Until Live mode is granted, the manual Ads Manager UI path (see [marketing/META_ADS_MANUAL_FINISH.md](META_ADS_MANUAL_FINISH.md)) is the daily-driver workflow.
