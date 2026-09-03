# Holding continuous-watch cron — deploy runbook (Wave 1)

A second cron service that runs the read-only holding **watch loop** every ~15 min: it senses current
state, diffs against the last-seen state, and pings your Telegram ONLY on material change (spam-free —
one alert when something breaks, one when it recovers, nothing in between). Complements the
observability monitor (infra) by watching the **portfolio/entity** layer (a product down, a scanner
stopped, a new risk/incident, Nexora subscribers/MRR drop, an entity losing VERIFIED status).

Runs as a service in kai-production, sharing kai-prod's Postgres (for its watch-state row) and the
same Telegram channel. `railway add`/`up` + cron schedule are operator steps (prod mutations are
classifier-gated). Builds `ops/holding-watch-cron/Dockerfile` (CMD runs the watch once, then exits).

## 1) Create the service + env
```
railway add --service kai-watch-cron \
  --variables 'APP_ENV=production' \
  --variables 'KAI_HOLDING_ENABLED=true' \
  --variables 'KAI_HOLDING_WATCH_ENABLED=true' \
  --variables 'KAI_HOLDING_DELIVERY_ENABLED=true' \
  --variables 'OPENAI_API_KEY=sk-cron-unused' \
  --variables 'DATABASE_URL=${{Postgres.DATABASE_URL}}' \
  --variables 'REDIS_URL=${{Redis.REDIS_URL}}'
```
Then add your real Telegram creds (copy from `kai-prod-monitor` → paste; never typed/exposed):
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## 2) Point at the watch Dockerfile
```
railway variables --service kai-watch-cron --set "RAILWAY_DOCKERFILE_PATH=ops/holding-watch-cron/Dockerfile"
```

## 3) Deploy (from a worktree that has ops/holding-watch-cron/)
```
railway up --service kai-watch-cron --detach
```

## 4) Set the schedule (dashboard)
Railway → **kai-watch-cron → Settings → Cron Schedule**: `*/15 * * * *` (every 15 min). Restart Policy = Never.

## 5) Verify
- First run logs `holding-watch-cron: {'ran': True, 'baseline': True, ...}` (silent baseline).
- Next run with no change: `events: []` (nothing sent). When something changes, you get one Telegram alert.

## Rollback / disable
- Set `KAI_HOLDING_WATCH_ENABLED=false` (watch no-ops), or pause/delete the service.
- Delivery is separately gated by `KAI_HOLDING_DELIVERY_ENABLED` — off = watch runs but sends nothing.

## Note
Read-only + report-only. The watch never acts on anything — it only tells you what changed. Acting on
those alerts (Waves 2–3: propose → approve → execute) is a later, approval-gated build.
