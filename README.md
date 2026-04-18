# 🤖 WheellsVerse Bot Ecosystem

**70 Autonomous AI Bots — Built for Jhon Kevens D Wheeler / J.K. Blaze**

Production-ready, modular, and fully automated. Runs locally on your Mac.

---

## 🗺️ FOLDER STRUCTURE

```
wheellsverse_bots/
├── main.py                        ← MASTER ENTRY POINT
├── setup.sh                       ← ONE-CLICK INSTALL
├── requirements.txt
├── .env.example                   ← Copy to .env + add API keys
├── launch.sh                      ← Quick launcher
├── dashboard.sh                   ← Web dashboard launcher
├── setup_cron.sh                  ← Auto-schedule setup
│
├── core/
│   ├── base_bot.py                ← Base class (all bots inherit this)
│   ├── orchestrator.py            ← Master controller
│   ├── scheduler.py               ← Cron/loop scheduler
│   └── dashboard.py               ← CLI + Web dashboard
│
├── bots/
│   ├── marketing/                 ← 20 bots (#1-20)
│   │   ├── 01_content_generator/
│   │   │   ├── bot.py
│   │   │   └── config.json
│   │   ├── 02_seo_optimizer/
│   │   └── ... (all 20)
│   │
│   ├── business/                  ← 8 bots (#21-28)
│   ├── customer_support/          ← 3 bots (#29-31)
│   ├── sales/                     ← 5 bots (#32-36)
│   ├── social_media/              ← 9 bots (#37-45)
│   ├── writing/                   ← 8 bots (#46-53)
│   ├── assistant/                 ← 3 bots (#54-56)
│   ├── problem_solving/           ← 2 bots (#57-58)
│   ├── time_management/           ← 2 bots (#59-60)
│   ├── ecommerce/                 ← 2 bots (#61-62)
│   ├── specialized/               ← 8 bots (#63-70)
│   └── core/
│       └── bug_hunter/            ← Autonomous static bug scanner
│           ├── bot.py             ← BaseBot + argparse CLI
│           ├── scanner.py         ← Static source scanner
│           ├── detector.py        ← Finding classifier
│           ├── fixer.py           ← Safe auto-fixer
│           ├── reporter.py        ← Markdown/JSON report generator
│           ├── watchdog.py        ← Real-time file watchdog
│           └── scheduler.py      ← Daily cron integration
│
├── narai/marketing/               ← 30-day KDP ebook launch autopilot
│   ├── marketing_autopilot.py    ← Core engine + CLI
│   ├── api.py                     ← FastAPI router (GET/POST /marketing/*)
│   └── schedule.yaml             ← 59 tasks across 30 days
│
├── AUDIT_REPORT.md               ← Static audit findings
├── UPGRADES.md                   ← 10 implemented upgrades
├── CHANGELOG.md                  ← All changes
│
├── logs/                          ← Auto-created log files
│   └── bug_hunter/               ← Bug scanner reports (Markdown + JSON)
├── outputs/                       ← All bot outputs saved here
│   ├── marketing/
│   ├── business/
│   └── ...
└── data/                          ← Persistent data (tasks, invoices, etc.)
```

---

## ⚡ QUICK START (3 Steps)

```bash
# Step 1 — Setup (one time)
bash setup.sh

# Step 2 — Add your OpenAI API key
nano .env
# Set: OPENAI_API_KEY=sk-your-key-here

# Step 3 — Launch
./launch.sh
```

That's it. The interactive menu opens.

---

## 🚀 ALL LAUNCH COMMANDS

```bash
# Interactive menu (recommended first time)
./launch.sh

# Check status of all 70 bots
./launch.sh --status

# List all bot names
./launch.sh --list

# Run ONE bot
./launch.sh --run marketing/01_content_generator
./launch.sh --run business/21_business_plan
./launch.sh --run assistant/54_task_assistant

# Run a whole CATEGORY
./launch.sh --category marketing
./launch.sh --category business
./launch.sh --category social_media

# Run ALL 70 bots (sequential)
./launch.sh --all

# Run ALL bots in PARALLEL (faster, uses more memory)
./launch.sh --all --parallel

# Launch Web Dashboard (http://localhost:5050)
./dashboard.sh
./launch.sh --dashboard --port 5050

# Start the Scheduler (runs bots on their schedules)
./launch.sh --schedule

# Check setup & .env status
./launch.sh --check
```

---

## 🤖 ALL 70 BOTS

### 📣 MARKETING (Bots 1-20)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 01 | Content Generator | Blog posts, articles, social content | Daily 8am |
| 02 | SEO Optimizer | SEO audit + rewrite for any content | Daily 9am |
| 03 | Email Campaign | Full email sequences (welcome, sales, nurture) | Weekly Mon |
| 04 | Ad Copy | Facebook, Google, Instagram ads | Weekly Wed |
| 05 | Funnel Builder | Complete marketing funnels | Weekly Fri |
| 06 | Lead Magnet | Checklists, ebooks, templates | Daily |
| 07 | Keyword Scraper | SEO keyword research + clusters | Daily |
| 08 | Competitor Analyzer | Competitive intelligence | Weekly |
| 09 | Landing Page | Full landing page HTML + copy | Weekly |
| 10 | Analytics Reporter | Performance analytics reports | Daily |
| 11 | A/B Testing | Test variants for any element | Weekly |
| 12 | Brand Voice | Brand voice and style guide | Monthly |
| 13 | Trend Analyzer | Market and content trends | Weekly Mon |
| 14 | Hashtag Generator | Hashtag strategy by platform | Daily |
| 15 | Outreach Automation | Cold outreach templates | Weekly |
| 16 | Blog Publisher | Publish-ready blog posts | Daily |
| 17 | Newsletter Generator | Weekly newsletter content | Weekly Fri |
| 18 | Conversion Optimizer | CRO audit and fixes | Weekly |
| 19 | Marketing Strategy | Full marketing strategy | Monthly |
| 20 | Growth Hacking | Growth experiments and tactics | Weekly |

### 🏢 BUSINESS (Bots 21-28)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 21 | Business Plan | Investor-ready business plan | Monthly |
| 22 | Financial Projection | 36-month financial model | Monthly |
| 23 | KPI Tracker | Track and analyze business KPIs | Weekly Mon |
| 24 | Expense Tracker | Expense analysis and reporting | Monthly |
| 25 | Workflow Automation | Process automation design | Weekly |
| 26 | Hiring Assistant | Job descriptions + interview questions | Weekly |
| 27 | Legal Document | Basic legal templates | Monthly |
| 28 | Operations Optimizer | Ops efficiency analysis | Monthly |

### 🎧 CUSTOMER SUPPORT (Bots 29-31)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 29 | Auto-Reply Email | AI customer support replies | Every hour |
| 30 | FAQ Chatbot | Interactive local FAQ bot | Every hour |
| 31 | Ticket Classifier | Auto-triage support tickets | Every 30min |

### 💼 SALES (Bots 32-36)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 32 | Cold Email | Personalized cold outreach | Daily 9am |
| 33 | Follow-up | Sales follow-up sequences | Daily 10am |
| 34 | CRM Updater | CRM data management | Daily 8am |
| 35 | Proposal Generator | Professional sales proposals | Weekly |
| 36 | Negotiation Assistant | Negotiation scripts and strategy | Weekly |

### 📱 SOCIAL MEDIA (Bots 37-45)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 37 | Auto Post | 7-day social media calendar | Weekly Sun |
| 38 | Content Scheduler | Platform posting schedule | Weekly Mon |
| 39 | Engagement Reply | Comment/DM response templates | Every 6h |
| 40 | DM Automation | Direct message campaigns | Daily |
| 41 | Viral Analyzer | Viral content research | Daily |
| 42 | Caption Generator | Social media captions | Daily |
| 43 | Video Script | Short-form video scripts | Weekly |
| 44 | Trend Scraper | Social trending topics | Daily 6am |
| 45 | Multi-Platform Poster | Cross-platform content | Daily |

### ✍️ WRITING (Bots 46-53)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 46 | Blog Writer | Full blog articles | Daily |
| 47 | Book Writer | Book chapters and outlines | Weekly |
| 48 | Script Writer | Video/podcast scripts | Weekly |
| 49 | Resume Generator | ATS-optimized resumes | Monthly |
| 50 | Cover Letter | Personalized cover letters | Monthly |
| 51 | Copywriter | Sales and marketing copy | Daily |
| 52 | Technical Writer | Documentation and guides | Weekly |
| 53 | Proofreader | Grammar and style editing | Daily |

### 🧠 ASSISTANT (Bots 54-56)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 54 | Task Assistant | Daily task planning | Daily 7am |
| 55 | Reminder Bot | Smart reminders + Mac notifications | Every 30min |
| 56 | File Organizer | Auto-organize Downloads folder | Daily 11pm |

### 🔬 PROBLEM-SOLVING (Bots 57-58)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 57 | Debugging Assistant | Code debugging and analysis | Every 2h |
| 58 | Research Bot | Deep research reports | Daily 9am |

### ⏰ TIME MANAGEMENT (Bots 59-60)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 59 | Schedule Optimizer | Optimized daily schedule | Daily 6:30am |
| 60 | Focus Session (Pomodoro) | Timed deep work sessions | On demand |

### 🛒 E-COMMERCE (Bots 61-62)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 61 | Product Description | Optimized product copy | Weekly |
| 62 | Pricing Optimization | Pricing strategy analysis | Monthly |

### 🎓 SPECIALIZED (Bots 63-70)
| # | Bot | Purpose | Schedule |
|---|-----|---------|----------|
| 63 | Course Creator | Online course curriculum | Monthly |
| 64 | Content Planning | 30/60/90-day content plan | Monthly |
| 65 | Pricing Strategy | Business pricing strategy | Monthly |
| 66 | Podcast Generator | Episode scripts and show notes | Weekly |
| 67 | Presentation Generator | Slide decks and presentations | Weekly |
| 68 | Designing Bot | Visual design briefs and prompts | Weekly |
| 69 | Invoice Management | Invoice tracking and reporting | Daily 8am |
| 70 | Reporting Dashboard | Weekly/monthly business reports | Weekly Mon |

---

## ⚙️ CONFIGURATION

### Adding API Keys (.env)
```bash
# Required for most bots
OPENAI_API_KEY=sk-proj-...

# Optional (enables more features)
EMAIL_USER=you@gmail.com
EMAIL_PASSWORD=your-app-password
STRIPE_SECRET_KEY=sk_test_...
TWITTER_BEARER_TOKEN=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

### Bot Config (each bot has config.json)
```json
{
  "description": "What this bot does",
  "enabled": true,
  "schedule": "@daily 09:00",
  "custom_setting": "value"
}
```

### Schedule Formats
```
@every_5min     — every 5 minutes
@every_30min    — every 30 minutes
@every_hour     — every hour
@every_6hours   — every 6 hours
@daily 09:00    — every day at 9am
@weekly mon 08:00 — every Monday at 8am
@monthly        — every 30 days
```

---

## 🏗️ BUILDING CUSTOM BOTS

Create a new bot by adding a folder and bot.py:

```python
# bots/marketing/21_my_new_bot/bot.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot

class MyNewBot(BaseBot):
    def __init__(self):
        super().__init__("21_my_new_bot", "marketing")
    
    def run(self, topic: str = "default topic", **kwargs):
        result = self.ai(f"Write about {topic}")
        path = self.save_output(result, "output.md")
        return {"file": str(path)}

if __name__ == "__main__":
    bot = MyNewBot()
    print(bot.execute(topic="AI automation"))
```

The orchestrator auto-discovers it on next launch. That's it.

---

## 🛠️ TROUBLESHOOTING

| Problem | Fix |
|---------|-----|
| `OPENAI_API_KEY not set` | Edit `.env` and add your key |
| `Module not found` | Run `source venv/bin/activate` then `pip install -r requirements.txt` |
| Bot fails silently | Check `logs/[bot_name].log` |
| Dashboard not loading | Check port 5050 is free: `lsof -i :5050` |
| Slow first run | Normal — orchestrator loads all 70 bots once |
| Mac notification not working | Allow Terminal notifications in System Preferences |

---

## 📞 CONTACT

**Jhon Kevens D Wheeler**
Email: wheelerjhonkevensd@gmail.com
Brand: J.K. Blaze / WheellsVerse
Location: Taunton, MA

---

*WheellsVerse Bot Ecosystem v1.0 — 70 Autonomous AI Bots*
