# Holding daily-briefing cron — deploy runbook (Option 1)

Adds a lightweight **daily** job that runs the report-only briefing with `persist=True`, so a KPI
snapshot is stored each day and the on-demand `/admin/holding/briefing` movement shows real
day-over-day deltas (instead of a baseline note). Matches the observability-monitor pattern
(a Railway cron, not a long-running Celery worker/beat). Report-only — never sends externally.

Runs as a **second service in the existing kai-production project**, sharing the same Postgres that
kai-prod reads. It builds `ops/holding-briefing-cron/Dockerfile` (same deps as App B; CMD runs the
one-shot briefing and exits). `railway up` and the cron schedule are operator steps (prod mutations
are classifier-gated; the Railway cron schedule is dashboard-only).

> NOTE: config-as-code (`railway.json`) is deprecated and cannot be opted into for new Railway
> services, so the Dockerfile is selected via the `RAILWAY_DOCKERFILE_PATH` **env var** (not a config
> file), and the cron schedule is set in the dashboard.

## 1) Create the cron service + env (once)
```
railway add --service kai-briefing-cron \
  --variables 'APP_ENV=production' \
  --variables 'KAI_HOLDING_ENABLED=true' \
  --variables 'KAI_HOLDING_BRIEFING_ENABLED=true' \
  --variables 'OPENAI_API_KEY=sk-cron-unused' \
  --variables 'DATABASE_URL=${{Postgres.DATABASE_URL}}' \
  --variables 'REDIS_URL=${{Redis.REDIS_URL}}'
```

## 2) Point it at the cron Dockerfile (env var, not config-as-code)
```
railway variables --service kai-briefing-cron --set "RAILWAY_DOCKERFILE_PATH=ops/holding-briefing-cron/Dockerfile"
```

## 3) Deploy (from a worktree that has ops/holding-briefing-cron/Dockerfile)
```
railway up --service kai-briefing-cron --detach
```
The image's CMD is `python /app/ops/holding-briefing-cron/run.py` (one-shot; no custom start command
needed). No alembic (kai-prod already migrated; `kpi_history` self-creates its table).

## 4) Set the daily schedule (dashboard)
Railway dashboard → **kai-briefing-cron** → Settings → **Cron Schedule**: `0 11 * * *`
(11:00 UTC = 07:00 America/New_York EDT; `0 12 * * *` for EST — matches KAI_HOLDING_BRIEFING_UTC_HOUR).
Leave **Restart Policy** = Never. Then "Run now" (or wait for the tick) to fire the first run.

## 5) Verify
- Cron run logs show `holding-briefing-cron: {'generated': True, ...}`.
- After a run, `/admin/holding/briefing` `kpi_movement` shows numeric deltas (not the baseline note).

## Rollback / disable
- Pause or delete `kai-briefing-cron` (kai-prod endpoint unaffected), or set
  `KAI_HOLDING_BRIEFING_ENABLED=false` on it (the task no-ops).

## Note
Optional polish: the on-demand briefing (priorities, live signals, KPI snapshot) is already live on
kai-prod; only movement/deltas need this daily persistence.
