# Holding daily-briefing cron — deploy runbook (Option 1)

Adds a lightweight **daily** job that runs the report-only briefing with `persist=True`, so a KPI
snapshot is stored each day and the on-demand `/admin/holding/briefing` movement shows real
day-over-day deltas (instead of a baseline note). Matches the observability-monitor pattern
(a Railway cron, not a long-running Celery worker/beat). Report-only — never sends externally.

Deployed as a **second service in the existing kai-production project**, so it shares the same
Postgres that kai-prod reads. `railway up`/service-create and the cron schedule are operator steps
(prod mutations are classifier-gated; Railway cron schedule is dashboard-only for new services).

## 1) Create the cron service in kai-production
From an isolated worktree linked to kai-production (like the prod deploy), or via the dashboard:
```
railway add --service kai-briefing-cron
```

## 2) Set env (shares Postgres with kai-prod; flag ON here, not on the web service)
```
railway variables --service kai-briefing-cron \
  --set "APP_ENV=production" \
  --set "RAILWAY_DOCKERFILE_PATH=backend/Dockerfile.staging" \
  --set "KAI_HOLDING_ENABLED=true" \
  --set "KAI_HOLDING_BRIEFING_ENABLED=true" \
  --set "OPENAI_API_KEY=sk-cron-unused" \
  --set "DATABASE_URL=\${{Postgres.DATABASE_URL}}" \
  --set "REDIS_URL=\${{Redis.REDIS_URL}}"
```
`railway.json` sets `startCommand` = `python /app/ops/holding-briefing-cron/run.py` and
`restartPolicyType: NEVER` (a cron job runs once then exits). No alembic needed (kai-prod already
migrated; `kpi_history` self-creates its table).

## 3) Deploy + set the daily schedule (dashboard)
```
railway up --service kai-briefing-cron --detach
```
Then in the Railway dashboard → kai-briefing-cron → Settings → **Cron Schedule**: `0 11 * * *`
(11:00 UTC = 07:00 America/New_York EDT; use `0 12 * * *` for EST — matches KAI_HOLDING_BRIEFING_UTC_HOUR).

## 4) Verify
- Trigger once (dashboard "Deploy" / "Run now", or wait for the tick). Logs should show
  `holding-briefing-cron: {'generated': True, ...}`.
- The next day, `/admin/holding/briefing` `kpi_movement` shows numeric deltas (not the baseline note).

## Rollback / disable
- Pause or delete the `kai-briefing-cron` service (kai-prod endpoint is unaffected).
- Or set `KAI_HOLDING_BRIEFING_ENABLED=false` on the cron service (the task no-ops).

## Note
This is optional polish: the on-demand briefing (priorities, live signals, KPI snapshot) is already
live on kai-prod. Only movement/deltas need this daily persistence.
