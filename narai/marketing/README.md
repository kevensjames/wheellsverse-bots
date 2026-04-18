# NarAI Marketing Autopilot

30-day launch engine for **"AI for Traders & Creators"** — Amazon KDP, Gumroad, Payhip, plus Instagram/Facebook audience growth. Generates content via Claude claude-opus-4-7, tracks tasks in SQLite, and optionally auto-posts to Meta.

---

## Setup

```bash
cd /Volumes/Wheellsverse/narai_marketing

# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Open .env and fill in ANTHROPIC_API_KEY and LAUNCH_DATE at minimum

# 4. Load the 30-day schedule into SQLite
python marketing_autopilot.py load
# Expected: "Loaded 59 new tasks into DB."

# 5. Verify
python marketing_autopilot.py status
# Expected: 59 rows, all status=pending
```

---

## Daily Workflow

```bash
# Run today's pending tasks (generates content, saves to output/)
python marketing_autopilot.py run

# Review what was generated
ls output/
cat output/reel-why-traders-lose.json

# Check all task statuses
python marketing_autopilot.py status

# Approve a task (makes it "approved"; with AUTO_POST=true, also posts to Meta)
python marketing_autopilot.py approve 3
```

Output files are saved as `output/{slug}.json`. Review them, edit if needed, then post manually or set `AUTO_POST=true` in `.env`.

---

## Auto-Posting to Instagram/Facebook

1. Set `AUTO_POST=true` in `.env`
2. Add `INSTAGRAM_PAGE_TOKEN`, `INSTAGRAM_ACCOUNT_ID`, `FACEBOOK_PAGE_TOKEN`, `FACEBOOK_PAGE_ID`
3. Run as normal — reel, carousel, and ad_copy tasks will auto-post after generation

> Note: Meta requires an actual hosted image URL for IG image posts. The reel/carousel output JSON will include a `cover_image_url` field if you add one to the payload, or you can post manually using the generated script text.

---

## Plug Into NarAI Backend

Add these 3 lines near the **bottom** of `/Volumes/Wheellsverse/wheellsverse_bots/core/api.py`, after the `app = FastAPI(...)` line:

```python
import sys
sys.path.insert(0, "/Volumes/Wheellsverse")
from narai_marketing.api import router as marketing_router
app.include_router(marketing_router)
```

This exposes these endpoints on your NarAI server:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/marketing/status` | All 59 tasks + status |
| POST | `/marketing/run` | Run today's tasks (background) |
| POST | `/marketing/approve/{id}` | Approve a task |
| GET | `/marketing/task/{id}` | Full task details + output |
| POST | `/marketing/reload-schedule` | Reload schedule.yaml |

---

## Run as macOS Daemon (launchd)

```bash
# Install
cp com.jkblaze.narai.marketing.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jkblaze.narai.marketing.plist

# Start immediately
launchctl start com.jkblaze.narai.marketing

# Check logs
tail -f logs/autopilot.log

# Stop
launchctl stop com.jkblaze.narai.marketing
launchctl unload ~/Library/LaunchAgents/com.jkblaze.narai.marketing.plist
```

The daemon runs `marketing_autopilot.py daemon` — checks for pending tasks every **6 hours**. On each tick it runs today's tasks and emails a digest to `wheelerjhonkevensd@gmail.com`.

---

## Cost Estimate

| Item | Cost |
|------|------|
| Claude claude-opus-4-7 — 59 tasks × ~3k tokens avg | ~$5–8/full run |
| Meta Graph API | Free |
| ConvertKit v3 API | Free (<300 subs) |
| Gumroad API | Free |
| SMTP (Gmail App Password) | Free |
| **Total / 30-day launch** | **~$5–8** |

Running the daemon daily for 30 days (1 run/day) stays well under $20/month.

---

## Schedule Overview

| Week | Days | Theme | Tasks |
|------|------|-------|-------|
| 1 | 1–7 | Foundation | Cover, KDP keywords, first reels, carousels |
| 2 | 8–14 | Pre-launch | Lead magnet, NarAI demo, countdown emails |
| 3 | 15–21 | Launch | Launch email, reel, ads, review asks, bundle upsell |
| 4 | 22–30 | Scale | Repost top content, newsletter, Amazon Ads, retro |

**59 total tasks** across 30 days.

---

## Task Types

| Type | What it generates |
|------|------------------|
| `reel` | Short-form video script (hook, lines, CTA) |
| `carousel` | Multi-slide Instagram post (headline + body per slide) |
| `email` | Full email (subject, preview, HTML body, CTA) |
| `ad_copy` | Paid ad (headline, primary text, description, CTA) |
| `amazon_keywords` | KDP keywords + backend string + categories |
| `analytics_pull` | Fetches Gumroad sales + ConvertKit subscribers |
| `reminder` | Logged reminder + digest email |
