# Dedicated Railway cron monitor — deployment

A separate, least-privilege Railway service that runs `ops/monitor` on a schedule. It is **isolated** from
App A, App B, web traffic, and financial workers. Observational only — it detects + alerts, never remediates.

## Topology
```
Railway cron service (kai-prod-monitor)
  → git source: kevensjames/wheellsverse-bots @ feat/kai-capability-fabric
  → build: Dockerfile  ops/monitor/Dockerfile  (context = repo root; pulls core/operator_session.py + ops/)
  → schedule: */5 * * * *   (config-as-code: ops/monitor/railway.json → deploy.cronSchedule)
  → command: python -m ops.monitor.run --cron
  → volume:  mounted at /data  (durable dedup/cooldown/recovery + heartbeat state)
  → env (below)
```

## Cadence (Phase C)
- Every **5 min**: lightweight tick — App A/B health, latency, 5xx, bridge, registry, owner `/admin/spend`
  (spend/provider/PG signals). **No OpenAI call.**
- **Once/hour** (top-of-hour window, `--canary-minute 5`): full governed canary — auth-matrix + governed SSE stream
  + audit-gap check. **One OpenAI call/hour.**

## Environment (Phase D — least privilege, secrets by REFERENCE, never committed/printed)
Set on the monitor service. If the service lives in the **App A project** (`grateful-flexibility-production`),
inject the three secrets as **Railway variable references** so their raw values never leave App A:
```
ENVIRONMENT           = production
MONITOR_STATE_DIR     = /data
RAILWAY_DOCKERFILE_PATH = ops/monitor/Dockerfile        # if not using ops/monitor/railway.json as config path
TELEGRAM_BOT_TOKEN    = ${{wheellsverse-v2.TELEGRAM_BOT_TOKEN}}
TELEGRAM_CHAT_ID      = ${{wheellsverse-v2.TELEGRAM_CHAT_ID}}
SESSION_SIGNING_SECRET= ${{wheellsverse-v2.SESSION_SIGNING_SECRET}}
```
The monitor receives ONLY these. It gets **no** DATABASE_URL/REDIS_URL, no deploy/restart token, no financial
credential, no capability-privilege secret. It cannot mutate money, deploy, restart, flush, or rotate.

## Steps
1. **Create the service** in the App A project (isolated service, not inside App A/B):
   `railway add --service kai-prod-monitor` (in the linked App A project).
2. **Connect git** (dashboard): source = `kevensjames/wheellsverse-bots`, branch `feat/kai-capability-fabric`.
   Set the service **Config-as-code path** to `ops/monitor/railway.json` (carries the Dockerfile path + cron schedule),
   OR set `RAILWAY_DOCKERFILE_PATH=ops/monitor/Dockerfile` + the cron schedule `*/5 * * * *` in Settings.
3. **Add a volume** (dashboard or `railway volume add`): mount path `/data`.
4. **Set env** (above) via `railway variables --set …` (references keep secrets in App A).
5. **Deploy** — Railway builds the Dockerfile and runs `--cron` on the schedule.

## Verify (Phase H)
- Service exists + schedule active.
- Wait for **two** actual scheduler-triggered runs (do not substitute manual runs).
- Each run: `environment=production`, App A + App B probes succeed, audit/usage check on the hourly canary,
  no financial action, no capability change, no secret in logs.
- Heartbeat at `/data/wv_monitor_heartbeat.json` advances each run.

## Monitor-the-monitor (Phase G)
- The monitor writes a heartbeat each tick (`last_tick_at`, status, delivery, `consecutive_failures`, version).
- On resume after a gap > 2× interval it emits `MONITOR_STALE` (catches restarts/missed ticks).
- **Limitation:** a *permanently dead* cron (scheduler never fires) cannot self-alert. Enable **Railway deploy/cron
  failure notifications** on this service as the independent watchdog, or add an external dead-man's-switch that
  expects the heartbeat to advance. Documented, not silently assumed.

## Durability note
Prefer the **git-connected** source above (reproducible, matches the App A/B git-authoritative model). Do **not**
run this as a `railway up` snapshot-only prod service — that is the fragile pattern the App A deployment-source
incident eliminated.
