# WHEELLSVERSE CONTINUOUS OBSERVABILITY CERTIFICATION
## 2026-08-29 · Dedicated Railway cron monitor LIVE · Money mode MOCK

Continuous, isolated, least-privilege self-monitoring of the live governed KAI stack. Observational only —
detect → classify → alert (owner Telegram) → provide runbook. No autonomous remediation.

## GIT
```
Branch                = feat/kai-capability-fabric   (pushed to origin; NOT merged to production)
Observability SHA     = 065679e   (44c9a7f monitor · 00d5e69 cron · 065679e staleness fix)
Secrets committed     = 0         (synthetic REDACTME/deadbeef redaction fixtures only)
Tests                 = 48/48 PASS
Failures              = 0
```

## SCHEDULER
```
Railway resource      = kai-prod-monitor  (service 8462e478, project grateful-flexibility, env production)
                        ISOLATED service — separate from App A, App B, web traffic, financial workers
Environment           = production
Cadence               = */5 * * * *  (lightweight)  +  governed canary at top-of-hour (~hourly)
Build                 = Dockerfile ops/monitor/Dockerfile (pure-stdlib image; repo-root context)
Volume                = kai-prod-monitor-volume @ /data (durable dedup/cooldown/recovery + heartbeat)
Scheduler active      = PASS   (cronSchedule=*/5 * * * *, nextCronRunAt advancing)
Scheduled tick #1     = PASS   (22:51:07Z · healthy · env=production · stale=false · 0 delivery failures)
Scheduled tick #2     = PASS   (22:55:09Z · healthy · env=production · stale=false · 0 delivery failures)
Scheduled canary tick = PASS   (23:00Z top-of-hour · did_canary=true · governed audit/usage check)   [see below]
```

## MONITORING  (live, from scheduled ticks + certified soak)
```
App A                 PASS    /api/health status+latency every tick
App B                 PASS    /health status+latency every tick
Auth anomaly monitor  PASS    auth-matrix canary (hourly) — anon 401 / operator 403 / owner 200; bypass=CRITICAL
Provider monitor      PASS    /admin/spend failures + cost thresholds
PostgreSQL monitor    PASS    /admin/spend read = PG reachability proxy
Redis monitor         PARTIAL inferred via governed-canary success (no direct external probe — documented)
Audit-gap monitor     PASS    governed canary + usage-increment check (executed-but-unaudited → CRITICAL)
SSE monitor           PASS    governed stream canary; 502/504→HIGH, 0-frames→WARNING
Latency monitor       PASS    p95 warn>2000ms / high>5000ms (baseline A~274 / B~209)
```

## ALERTING
```
Telegram delivery         PASS   real INFO alert + recovery certified (HTTP 200, secret-free)
Deduplication across ticks PASS  state on /data volume, key env:service:signal:severity (persists across cron runs)
Cooldown across ticks     PASS   900s; CRITICAL escalation bypasses cooldown
Recovery across ticks     PASS   single recovery on clear; re-breach = new alert
Delivery failure detection PASS  failed send → healthy=false + monitor_self HIGH (surfaced, never swallowed)
Monitor-stale detection   PASS   resume-gap detection (fixed: interval 300s matches */5) + 15-min stale cooldown
                          PARTIAL for PERMANENT cron death: a scheduler that never fires can't self-alert —
                          enable Railway deploy/cron failure notifications as the independent watchdog (documented).
```

## SECURITY
```
App A changed                     NO
App B changed                     NO
Production branch changed         NO   (monitor lives on feat/kai-capability-fabric; production untouched)
Money mode                        MOCK
Financial mutations               0    (monitor writes = governed canary + Telegram only; no financial endpoint)
Privileges widened                NO
Privileged capabilities enabled   0
Restricted capabilities enabled   0
Secrets exposed                   0    (Telegram/session via ${{wheellsverse-v2.*}} references; log lines secret-free)
CSP weakened                      NO
Least privilege                   monitor holds ONLY ENVIRONMENT, MONITOR_STATE_DIR, RAILWAY_DOCKERFILE_PATH +
                                  3 secret references — no DATABASE_URL/REDIS_URL, no deploy/restart/financial creds
```

## COST
```
Runs/day              288   (*/5)
Provider calls/day    24    (hourly governed canary only)
Estimated daily cost  ~$0.01 OpenAI + minimal Railway compute (~5s/run × 288)
Estimated monthly     <$5   (~$0.15 OpenAI + ~$1–5 Railway + small /data volume; Telegram free)
```

## DEFECTS
```
Critical  0
High      0
Medium    0
Low       1   (Cloudflare beacon CSP console entry — pre-existing infra, CSP intentionally not weakened)
Found+fixed during certification: staleness false-positive (default interval 240s < 300s cadence) — caught by the
  live 2-tick Phase H verification, fixed in 065679e (+ stale cooldown), re-verified clean. Not an open defect.
```

## KNOWN LIMITATIONS
1. **Permanent cron-death** isn't self-detectable (a dead scheduler can't alert). Mitigation: enable Railway's
   deploy/cron failure notifications on kai-prod-monitor as the independent watchdog. Resume-gap staleness IS detected.
2. **Redis** inferred, not directly probed (would need an App-B health change).
3. **Audit-write swallow** is in-process (router.py) — monitor detects the effect externally (audit_gap); fixing at
   source is a gated App-B change, not done.
4. Config-as-code (railway.json) is deprecated for new Railway services (post-2026-08-28); this service is configured
   via dashboard settings + `RAILWAY_DOCKERFILE_PATH` env instead. The committed `ops/monitor/railway.json` documents intent.

## FINAL GATE: **CONTINUOUS PRODUCTION OBSERVABILITY ACTIVE**
A dedicated, isolated, least-privilege Railway cron monitor runs every 5 minutes against production, delivers to the
owner's Telegram, persists dedup/cooldown/recovery state on a volume, and self-reports health. Two clean
scheduler-triggered ticks verified (plus the hourly governed audit/usage canary). No App A/B change, no production-branch
change, money MOCK, 0 financial mutations, 0 privilege changes, 0 secrets exposed, CSP intact.
