# WheellsVerse Deployment Guide

Full deployment instructions for local, Docker, and cloud platforms.

---

## Prerequisites

- Python 3.11+ (local) or Docker
- OpenAI API key (`OPENAI_API_KEY`)
- Optional: Slack webhook, email credentials, affiliate tags

---

## 1. Local Run (macOS / Linux)

```bash
# Install dependencies
cd wheellsverse_bots
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY

# Launch
python main.py --dashboard
# Dashboard: http://localhost:5050
# Landing page: http://localhost:5050/landing
```

---

## 2. Docker Build + Run

```bash
# Build image
docker build -t wheellsverse-bots .

# Run container
docker run -d \
  --name wheellsverse \
  -p 5050:5050 \
  -e OPENAI_API_KEY=sk-your-key-here \
  -e DECISION_ENGINE_ENABLED=true \
  -e DECISION_ENGINE_INTERVAL=15 \
  -v $(pwd)/outputs:/app/outputs \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/memory:/app/memory \
  -v $(pwd)/logs:/app/logs \
  wheellsverse-bots

# Check health
curl http://localhost:5050/api/health
```

Or with `docker-compose`:

```bash
cd deploy
cp ../.env .env   # copy your .env here
docker-compose up -d
```

---

## 3. Deploy to Cloud

### Railway (Recommended — easiest)

1. Push your code to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Railway auto-detects `Dockerfile`
4. Add environment variables in **Variables** tab:
   ```
   OPENAI_API_KEY=sk-your-key-here
   DECISION_ENGINE_ENABLED=true
   DECISION_ENGINE_INTERVAL=15
   API_KEY=your-secure-dashboard-key
   PORT=8080
   ```
5. Add a **Volume** at `/app/data` for persistence
6. Deploy — Railway gives you a public HTTPS URL

Verify: `curl https://your-app.railway.app/api/health`

---

### Render

1. Push your code to GitHub
2. Go to [render.com](https://render.com) → **New** → **Web Service**
3. Connect your GitHub repo
4. Settings:
   - **Environment**: Docker
   - **Dockerfile Path**: `./Dockerfile`
   - **Health Check Path**: `/api/health`
5. Add environment variables:
   ```
   OPENAI_API_KEY=sk-your-key-here
   DECISION_ENGINE_ENABLED=true
   DECISION_ENGINE_INTERVAL=15
   API_KEY=your-secure-dashboard-key
   PORT=10000
   ```
6. Add a **Disk**:
   - Mount Path: `/app/data`
   - Size: 1 GB
7. Click **Create Web Service**

Verify: `curl https://your-app.onrender.com/api/health`

---

### Fly.io

```bash
# Install flyctl
brew install flyctl

# Login
flyctl auth login

# Initialize (from project root)
flyctl launch --config deploy/fly.toml

# Set secrets
flyctl secrets set OPENAI_API_KEY=sk-your-key-here
flyctl secrets set API_KEY=your-secure-dashboard-key
flyctl secrets set DECISION_ENGINE_ENABLED=true

# Create persistent volume
flyctl volumes create wheellsverse_data --size 1 --region iad

# Deploy
flyctl deploy --config deploy/fly.toml
```

Verify: `curl https://wheellsverse-bots.fly.dev/api/health`

---

## 4. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ Yes | — | OpenAI API key |
| `API_KEY` | Optional | (none) | Dashboard API key (leave blank to disable auth) |
| `PORT` | Optional | 5050 | HTTP port |
| `DECISION_ENGINE_ENABLED` | Optional | true | Auto-run intelligence every N minutes |
| `DECISION_ENGINE_INTERVAL` | Optional | 15 | Minutes between intelligence cycles |
| `BRAND_NAME` | Optional | WheellsVerse | Your brand name |
| `BRAND_NICHE` | Optional | AI automation | Your content niche |
| `AUTHOR_NAME` | Optional | J.K. Blaze | Blog post author name |
| `CTA_URL` | Optional | https://wheellsverse.com | Your primary CTA URL |
| `AMAZON_AFFILIATE_TAG` | Optional | — | Amazon Associates tag |
| `SLACK_WEBHOOK_URL` | Optional | — | Slack webhook for alerts |
| `EMAIL_HOST` | Optional | — | SMTP host for email alerts |
| `EMAIL_USER` | Optional | — | SMTP username |
| `EMAIL_PASS` | Optional | — | SMTP password |
| `WORDPRESS_URL` | Optional | — | WordPress site URL |
| `WORDPRESS_USER` | Optional | — | WordPress username |
| `WORDPRESS_APP_PASSWORD` | Optional | — | WordPress application password |
| `MEDIUM_TOKEN` | Optional | — | Medium Integration Token |
| `GHOST_URL` | Optional | — | Ghost site URL |
| `GHOST_ADMIN_KEY` | Optional | — | Ghost Admin API key (id:secret) |

---

## 5. Verify System Is Running

```bash
# Health check
curl https://your-app.com/api/health
# → {"status":"ok","uptime":123}

# Landing page
curl https://your-app.com/landing
# → Returns landing page HTML

# Bot count
curl https://your-app.com/api/overview
# → Returns system overview with bot count

# Trigger intelligence cycle
curl -X POST https://your-app.com/api/decision/run \
  -H "X-API-Key: your-api-key"
# → {"status":"started"}

# Check leads
curl https://your-app.com/api/leads/stats \
  -H "X-API-Key: your-api-key"
# → {"total_leads":0,"leads_today":0,...}
```

---

## 6. Access Dashboard Remotely

The dashboard is protected by `API_KEY` when set.

**Direct access:**
```
https://your-app.com/
```
The server injects the API key into the dashboard HTML automatically.

**API access (from external tools):**
```bash
curl https://your-app.com/api/decisions \
  -H "X-API-Key: your-api-key"
```

---

## 7. Key Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard (protected) |
| `/landing` | GET | Public landing page |
| `/api/health` | GET | Health check |
| `/api/lead` | POST | Capture email lead |
| `/api/leads/stats` | GET | Lead stats |
| `/api/analytics` | GET | Full analytics |
| `/api/content/run` | POST | Run content pipeline |
| `/api/decision/run` | POST | Run intelligence cycle |
| `/api/intelligence/summary` | GET | Intelligence overview |
| `/api/intelligence/conversions` | GET | Conversion stats |
| `/api/integrations/crypto` | GET | Live crypto prices |
| `/api/integrations/market` | GET | Full market snapshot |

---

## 8. Persistent Data Directories

All important data is stored in these directories (mount as volumes in Docker/cloud):

| Directory | Purpose |
|---|---|
| `/app/data/` | Intelligence records, leads, analytics |
| `/app/outputs/` | Generated content, reports, PDFs |
| `/app/memory/` | Bot memory entries |
| `/app/logs/` | Rotating system logs |

---

## Troubleshooting

**Bots not loading:**
```bash
# Check bot count
curl http://localhost:5050/api/health/bots
```

**Content pipeline not running:**
```bash
# Check OpenAI key is set
echo $OPENAI_API_KEY

# Run manually
curl -X POST http://localhost:5050/api/content/run \
  -H "Content-Type: application/json" \
  -d '{"top_n":1}'
```

**Decision engine not running:**
Check `DECISION_ENGINE_ENABLED=true` in your environment.

**Disk space issues:**
Old content outputs accumulate in `/app/outputs/content/`.
The system keeps the last 500 analytics entries but does not auto-delete content files.
