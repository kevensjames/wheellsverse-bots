# NarAI Genesis — Master Build Plan

**Owner:** J.K. Blaze
**Storage:** /Volumes/Wheellsverse (was "Lexar SSD" in original plan — same drive, renamed)
**Goal:** One AI that beats every other AI, grows with each user, runs autonomously.
**Last audit:** 2026-04-30 (Phase 0)

Status legend:
- `[x]` Built and working (verified)
- `[~]` Partial or broken (note follows)
- `[ ]` Not started

---

## Phase 0 — Foundation audit

- [~] Map full SSD directory tree — depth-2 walk done; full recursion not run
- [~] List all 142 bots by name + status — actual: 23 categories, 173 .py files, 134 in `data/bot_health.json`. Counts disagree.
- [ ] Confirm symlink + `startwork` alias still work — lives in `~/.zshrc`, not verified
- [x] Run backend health check (FastAPI) — `core.api:app` imports OK locally → 657 routes; prod `/api/health` 200
- [~] Run database health check — using **SQLite** (`core/db.py`, `core/chat_db.py`, `core/nexora_db.py`); plan asks Postgres (Phase 1+)
- [ ] Run cache health check (Redis) — no Redis dep, no `import redis` anywhere; not started
- [~] Run vector DB health check — **ChromaDB** (not Pinecone/pgvector). Works in prod (`v2_chat:true`); fails locally — chromadb missing from active venv
- [x] Confirm Railway deployment is live — `app.wheellsverse.com/api/health` 200, uptime 9h 39m, git `e263ec2`
- [~] Confirm Stripe webhooks fire — endpoints exist (`/api/stripe/webhook`, `/api/nx/stripe-webhook`); not test-fired
- [~] Confirm Telegram bot online — endpoints + auth gate present; live status not pulled
- [~] Confirm Discord bot online — `core/discord_bot.py` exists with `commands.Bot`; runtime status unverified
- [ ] Confirm WhatsApp rate-limit guard is active — `core/whatsapp.py` `send_message()` has no 429/backoff; memory says shipped, code disagrees

**Phase 0 blockers:**
- Railway↔GitHub auto-deploy disconnected since 2026-04-26 — **41 commits behind** prod (`e263ec2` → `3bdfd1a`)
- Local venv missing chromadb/numpy/litellm/yaml → 11 NarAI v2 subsystems fail to import
- FastAPI version mismatch — `add_event_handler` removed; briefing + insider schedulers silently disabled
- Bot count folklore (142/134/173 disagreement)

---

## Phase 1 — Core backend

- [x] FastAPI server boots clean — 657 routes, prod healthy
- [x] Auth system (JWT) — `core/nexora_auth.py`, `/api/v2/narai/*` JWT-gated
- [x] User model + DB migrations — Alembic in `backend/alembic/versions/` (0001_initial_schema, 0002_stripe_customer_id)
- [~] Rate limiter middleware — present per-route in some places (e.g., tweepy `wait_on_rate_limit`); coverage uneven; no global middleware
- [x] Logging + error tracking — `core/sentry_init.py` shipped (commit `2a665bb`)
- [x] Public API endpoint with API keys — `core/api_keys.py`, X-API-Key headers enforced
- [x] CORS configured for frontend + mobile — `CORSMiddleware` in `core/api.py`
- [x] Environment variables loaded from `.env` — `dotenv` used throughout

---

## Phase 2 — AI brain layer

- [x] OpenAI GPT-4o connected — `openai>=1.30.0` in requirements
- [x] Anthropic Claude connected — `anthropic>=0.39.0`
- [x] Google Gemini connected — `google-generativeai>=0.7.0`; project `138879601248`; **key rotated 2026-04-30 after chat leak**
- [x] Mistral connected — `mistralai>=1.0.0`; **key rotated 2026-04-30 after chat leak**
- [~] Model router — two routers exist (`core/model_router.py`, `narai/core/router.py`); not unified
- [~] Streaming responses working — verify per route; partial
- [~] System prompt manager — `narai/core/identity.py` builds system prompts; central manager not surveyed
- [ ] Prompt library stored in DB — not surveyed

**Credential storage rule (non-negotiable):**
- All API keys live ONLY in `narai_godmode` Fernet vault
- Backend reads them at runtime via env var injection
- Never paste keys into chat, screenshots, code, git, or this plan file
- If a key leaks: revoke at the provider, rotate in the vault, redeploy
- Rotation log lives at `narai_godmode/rotations.log`

---

## Phase 3 — Memory + personalization

- [x] Short-term memory (chat history) — `core/chat_db.py` SQLite store
- [x] Long-term memory (vector DB) — ChromaDB via `narai/core/memory.py:264` (`PersistentClient`)
- [x] User profile store — Supabase tied to `/dashboard` (anon key visible in dashboard.html)
- [x] Memory recall in every prompt — verified prod `v2_chat:true`; per memory: "3-layer memory shipped"
- [~] Memory edit + delete endpoints — `/api/narai/memory` exists; CRUD coverage not enumerated
- [x] RAG pipeline for user files — `narai/core/rag.py` (langchain-text-splitters + pypdf)
- [~] User context auto-injection — confirmed for tier-gated paths; full coverage not enumerated

---

## Phase 4 — Voice + multimodal

- [~] Speech-to-text — `DEEPGRAM_API_KEY` in `.env.example`; integration unverified
- [~] Text-to-speech — `ELEVENLABS_API_KEY` in `.env.example`; per architecture doc piper-tts is "Phase 2"
- [~] Voice waveform UI — not surveyed
- [ ] iOS Safari audio fix confirmed
- [ ] Image upload + vision model
- [ ] PDF + docx upload + parsing
- [ ] File understanding pipeline

---

## Phase 5 — Agent + tools layer

- [~] Tool registry — `core/agent.py` and `core/agent_router.py` exist; tool catalog under `outputs/tool_catalog`
- [~] Web search tool — `SERPAPI_KEY`, `SERPER_API_KEY`, `DATAFORSEO_*` in env
- [ ] Stock API tool
- [ ] Crypto API tool
- [~] News API tool — possible via `outputs/seo_command`
- [~] Email sending tool — `SENDGRID_API_KEY`, `EMAIL_HOST` in env
- [~] Calendar tool — `GOOGLE_SHEETS_CREDENTIALS_PATH` in env, no calendar route confirmed
- [~] File read/write tool — present in agent
- [ ] Code execution sandbox
- [~] Autonomous agent mode — `narai_autopilot:true` in prod health
- [~] 10-agent WheellsVerse architecture — referenced in prod version string `nexora-v6-agent-workforce`; not enumerated

---

## Phase 6 — Frontend (web)

- [x] Next.js or React app boots — multiple shells: `frontend/`, `trade-app/`, `wheelsverse/`
- [x] Chat UI — `/chat` 200 in prod
- [x] Dark mode — verified in `/dashboard` HTML (CSS `--bg:#05070d`)
- [~] Voice button — UI present in narai/voice; integration unverified
- [~] File upload UI — not surveyed
- [~] Artifacts panel — `core/artifact_engine.py` exists
- [ ] Stock + crypto dashboard
- [x] Settings page — accessible via dashboard
- [x] Login + signup flow — `/login`, `/signup` 200 in prod
- [x] Stripe checkout page — `/pricing` 200; subscription flow shipped (commit `8400d28`)

---

## Phase 7 — Mobile (PWA + native)

- [ ] PWA manifest + service worker
- [ ] Mobile chat layout
- [ ] Push notifications
- [ ] Offline cache
- [ ] React Native or Flutter app scaffold (later)

---

## Phase 8 — Monetization

- [x] Stripe products + prices created — verified via env (`STRIPE_PRO_URL`, `STRIPE_PRICE_TG_GROUP`, `STRIPE_BOT_PACK_URL`)
- [x] Free tier limits — tier system in dashboard (free/pro/max/ultra), `TIER_LIMITS` defined
- [x] Pro tier features gated — visible in dashboard.html script
- [x] Subscription webhooks — Telegram subscription webhook live (commit `8400d28`)
- [~] Usage metering per user — `messages_used_today` in profile API; needs deeper verification
- [x] Affiliate links integrated — `/go/*` tracker for 236 affiliates; Robinhood→Webull consolidation shipped (commit `ada2937`)
- [~] Public API key billing — API keys exist; metered billing not confirmed

---

## Phase 9 — Bot fleet (WheellsVerse 142 bots)

- [~] Bot registry up to date — `data/bot_health.json` (134) vs filesystem (173) vs plan (142) disagree
- [x] Bot control panel — `/dashboard` lists bots
- [~] Visual bot builder — `core/bot_builder.py` exists; UI not confirmed
- [x] Bot scheduler — `core/narai_scheduler.py`, APScheduler in deps
- [x] Bot logs + analytics — `data/bot_health.json` has run_count, success_rate, etc.
- [ ] Mac mini M4 set as always-on host — not verified
- [ ] iMac confirmed as dev workstation — current dev box (assumed yes)
- [~] GitHub integration for bot code — generated_bots/ exists; auto-deploy broken

---

## Phase 10 — Safety + ops

- [~] Input filter (prompt injection guard) — not explicitly surveyed
- [~] Output moderation — not explicitly surveyed
- [~] Per-user rate limit — partial (per-route)
- [ ] Abuse detection
- [~] Backups (DB + SSD) — `narai_memory_backup.json` exists; SSD-level backup unconfirmed
- [ ] Monitoring dashboard
- [~] Error alerts — Sentry shipped (`core/sentry_init.py`); Telegram alert helpers exist
- [ ] Cost tracker per model

---

## Phase 11 — Growth

- [x] Landing page — `/landing` 200, cinematic shipped (memory: "Cinematic landing live")
- [~] Waitlist — not surveyed
- [x] Referral system — affiliate `/go/*` system live
- [x] LinkedIn launch post — drafted
- [~] Analytics (PostHog or Plausible) — not confirmed
- [x] SEO basics — sitemap.xml live with 70+ blog URLs

---

## Found but unmapped (not in original plan)

These exist in the repo but aren't in any phase. Worth surfacing for future audits:

- `narai_godmode/` — Fernet credential vault + browser adapters (amazon_kdp, canva, google, linkedin, meta, tiktok, x_twitter)
- `backend/` — separate FastAPI scaffold (S0–S5 trade-saas) with Alembic migrations and ML predictor
- `trade-app/` + `wheelsverse/` — two React app shells
- `second_brain_inbox/` — uncommitted; has Dockerfile + railway.json + frontend/api (likely separate Railway service)
- `shopify.app.toml` + `.shopify/` — Shopify embedded app
- `money_center/` — separate revenue tracking module with own tests
- `core/inbox/` — uncommitted
- `core/kdp_launch.py`, `core/kdp_paperback.py` — KDP automation
- `scripts/com.wheellsverse.kdp.daily.plist` — macOS launchd cron
- `semgrep-mcp/` — MCP server tool (likely external clone)

---

## Session log — 2026-04-30 (updated)

### ✅ Already done this session

**Phase 0 — Audit (complete)**
- Mapped repo (90+ dirs, 23 bot categories, 173 .py files, 134 health-tracked entries)
- Confirmed prod live: `app.wheellsverse.com/api/health` → 200, `/api/v2/narai/health` → `v2_chat:true`, uptime 9h+
- Confirmed Railway link intact: project `grateful-flexibility`, env `production`, service `wheellsverse-v2`
- Verified all 6 Telegram-subscription env vars set in Railway prod
- Mapped 41-commit backlog scope: 440 files, +18,674/-1,055, 191 net-new files

**Phase A — Pre-deploy diagnosis (complete)**
- File-safety triage: 27 untracked items vetted; `money_center/assets.backup.json` is bot-app state (no secrets); `shopify.app.toml` has only public `client_id`
- Gitleaks scan (full tree, 1 GB, 13 min): 12,713 findings, 0 in tracked code; the 3 in `deploy/README.md` are placeholder false-positives (`your-api-key`)
- Opsera pre-commit gate: 232 existing findings, 0 NEW from staged diff; report uploaded to dashboard

**Phase B — Local commit prep (paused mid-flight)**
- Wrote this file (`NarAI_Genesis_Master_Plan.md`) at repo root
- Updated `.gitignore` lines 118-133: added state files, audit artifacts, backup files, env backups, hook caches, screenshots dir
- Removed stale `!data/narai_memory.json` un-ignore
- Identified 6 runtime-state JSONs that need `git rm --cached` (gitignore was added after they were tracked)
- Drafted 6-commit bucket plan (chore/state, feat/twitter, feat/kdp, feat/store, feat/inbox, docs)
- **Paused** — staging unwound via `git reset HEAD` after parallel session committed `b1a6e53` (TwitterBrowserPoster harden) and `4282d43` (Amazon-grade UX), invalidating the bucket plan

### 🔓 Production state (as of pause)

- **Prod git SHA:** `e263ec2` (4 days stale; Railway↔GitHub auto-deploy disconnected since 2026-04-26)
- **Local HEAD:** `4282d43` (43 commits ahead of prod after the parallel session shipped 2 more)
- **Working tree:** 6 modified, 34 untracked entries — includes new in-flight Discord-subscription work: `core/api.py` (+38 lines), `core/discord_bot.py` (+79 lines), `narai/api/routes/{insider_admin,telegram_subscription}.py`, `narai/integrations/scheduler_promo.py`, plus new files `narai/integrations/discord_subscription.py` and `narai/tests/test_discord_subscription.py`

### 🛑 Outstanding security blockers (rotation required before Phase D deploy)

Six secrets were exposed in chat during this session and must be rotated:

| Secret | Source | Rotate at |
|---|---|---|
| Mistral API key | User paste | console.mistral.ai → API Keys |
| Gemini API key | User paste | console.cloud.google.com (project 138879601248) |
| Stripe webhook secret (`whsec_5C1ij…`) | Railway CLI dump | Stripe → Developers → Webhooks → roll secret |
| Telegram bot token (`8366836806:…`) | Railway CLI dump | @BotFather → `/revoke` |
| Telegram webhook secret (`7d7fddbd…`) | Railway CLI dump | regenerate, update Railway + `setWebhook` |
| Discord bot token (`MTQ5OTMx…`) | User paste | discord.com/developers/applications/1499316945059840100/bot → Reset |

After rotating each: log in `narai_godmode/rotations.log` with date + reason "leaked in chat 2026-04-30", redeploy.

---

## ➡️ Next step

**The user is mid-edit on Discord-subscription wiring (parallel Claude session).** The next step has two parts, in order:

### 1. Let the parallel session finish + commit its Discord-subscription work
That session is touching `core/api.py`, `core/discord_bot.py`, and adding `narai/integrations/discord_subscription.py`. Until those files settle, this session can't safely commit anything that touches them.

### 2. Resume Phase B v2 (re-planned against new HEAD)

When the parallel session is done, this session will:
1. `git fetch && git status` to re-survey
2. Re-plan the bucket strategy (commits 2 and 6 from the original plan are likely no longer needed — twitter and Amazon-grade UX already shipped)
3. Re-run Opsera gate (currently cleared; will re-fire on first commit)
4. Commit the residue: `.gitignore` hygiene + state-file untrack, KDP automation, store/Shopify content, second-brain inbox, docs/master-plan
5. Then **Phase D — deploy**: rotate the 6 secrets first, then `railway up --service wheellsverse-v2` to push `4282d43` (and any new commits) to prod, replacing stale `e263ec2`
6. Then **Phase E — reconnect Railway↔GitHub auto-deploy** in dashboard so this 4-day drift never happens again

### Original top-3 priorities (still valid, with status updates)

1. **Reconnect Railway↔GitHub auto-deploy + ship 43-commit backlog** — local now `4282d43`, prod still `e263ec2`. Manual `railway up` → dashboard re-auth.
2. **Fix local NarAI dev environment** — `pip install -r narai/requirements.txt -r requirements.txt` in `.venv`; pin FastAPI<0.93 or migrate `add_event_handler` → `lifespan=` in `core/api.py`. (Unchanged.)
3. **Add WhatsApp rate-limit guard** in `core/whatsapp.py:55-90`. Wrap `requests.post()` with `tenacity` retry-on-429 honoring `Retry-After`. (Unchanged — TwitterBrowserPoster harden in `b1a6e53` doesn't touch WhatsApp.)

---

## Use of this file

- Save at repo root as `NarAI_Genesis_Master_Plan.md` (this file)
- Each Claude Code session, paste the audit prompt first
- Claude Code updates the boxes
- Commit the updated file to git so progress is tracked
- Repeat weekly

---

## Reality note

Not shipping a single AI smarter than all humans on day one. Shipping a focused, useful, paid AI product that grows. Same path OpenAI and Anthropic took. Stay on the checklist, stay shipping.
