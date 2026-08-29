# WHEELLSVERSE PRODUCTION — ALERT THRESHOLDS (post-Phase-4 hardening, item 2)
## 2026-08-29 · Governed KAI stack (App A app.wheellsverse.com ⇄ App B kai-prod) · Money mode MOCK

Scope: define WHAT to alert on and at WHAT threshold for the live governed KAI stack. Wiring the delivery
(Railway alerts / an external cron checker / a dashboard) is operator-side infra — this spec is the contract it
implements. Two classes of signal:
- **Public-surface** (synthetic probes, Railway HTTP metrics) — observable without credentials.
- **Governed-internal** (`llm_call_log`, governance `audit_log`, `/admin/spend`) — requires an owner-scoped read
  or DB access; poll from an operator-run monitor, not an anonymous probe.

Every "immediate STOP + contain" below is the **kill-switch**: `KAI_BRIDGE_ENABLED=false` on prod App A → governed
route fail-closes to 404, Command Center intact (proven Phase 3). Contain first, investigate second. Money mode
stays MOCK in every response — no financial action is ever part of remediation.

| # | Signal | Source | WARNING | CRITICAL | Response |
|---|--------|--------|---------|----------|----------|
| 1 | **App A 5xx** | Railway HTTP metrics (wheellsverse-v2); synthetic `GET /api/health` | any 5xx in 5 min, or 1 non-200 health probe | health non-200 ×2 consecutive (~3 min), or 5xx > 2% req/5 min | If bridge-linked → kill-switch. If App A core → redeploy `production@462adff`. |
| 2 | **App B 5xx** | Railway metrics (kai-prod); synthetic `GET /health` | any 5xx, or 1 non-200 health | health non-200 ×2, or 5xx > 2% req/5 min | Kill-switch (App A degrades to fail-closed 404), then investigate App B (DB/Redis/OpenAI). |
| 3 | **Auth anomalies** | governance `audit_log` + `llm_call_log` 401/403 denials; App A access logs | >10 auth failures/5 min from one principal/IP | **ANY** privileged 200 by operator/anon, or **ANY** 200 on `/admin/kai/*` without a valid owner session = authorization bypass | CRITICAL → immediate STOP + kill-switch + contain. This is the top stop-condition. |
| 4 | **OpenAI failures / spend** | `llm_call_log` (adapter=openai: calls/cost_usd/failures); `/admin/spend` | daily OpenAI cost > **$5**, or provider-failure rate > 10%/15 min | daily cost > **$20** or > **$2/hour** (runaway), or failure rate > 30%/15 min, or 100% failing (key invalid/outage) | Check key budget/validity; runaway → kill-switch to halt governed traffic. Cost = API spend, **not** user money (MOCK holds). |
| 5 | **DB / Redis errors** | App B logs; `llm_call_log` write path; Railway PG/Redis (kai-production) | any DB conn error; Redis latency spike | `/health` failing on DB, or sustained PG/Redis unreachable (governed calls 5xx) | Kill-switch; check kai-production PG + Redis service health. |
| 6 | **Audit-write failures** | Pass-4 durable failure audit (`router.py _log_failure_safe`, isolated committed session); `llm_call_log` rows vs. calls | any audit-write error logged | **executed-but-unaudited**: calls succeeding while audit writes fail | **SAFETY-CRITICAL** → immediate STOP + kill-switch. Governed execution must never proceed without durable audit. |
| 7 | **Worker failures** | Railway worker status; Celery retry/failure counts; Redis queue depth | task retry rate elevated; queue depth rising | worker down (queue not draining), or task failure > 30% | Restart worker. **N/A precondition:** confirm a prod worker is deployed — if prod governed KAI is synchronous-only, async jobs are inert and this signal does not apply until a worker is added (separately certified). |
| 8 | **SSE disconnects** | streaming `/admin/kai/kai-chat/stream`: 504 (bridge→App B timeout), 502 (App B unreachable), client aborts | elevated 504/502 rate on streaming | sustained 502/504 (drawer unusable) | Check App B health + bridge timeout; App B degraded → kill-switch. Note: user-initiated cancellations are a **feature**, not an error — exclude them. |
| 9 | **Latency** | synthetic probes (App A `/api/health`, App B `/health`); bridge round-trip; governed time-to-first-token | health p95 > 2s; governed first-token > 10s | health p95 > 5s; governed calls hitting bridge 504 timeout | Investigate App B / OpenAI latency; contain if user-facing. Baseline: see soak report. |

## Telemetry sources (all exist + certified)
- `llm_call_log` (App B prod PG): per-call adapter, cost_usd, success/failure, tool executions, gate denials — the spine of #3/#4/#6.
- governance `audit_log`: authorization decisions + governed actions.
- `/admin/spend` (App B, owner-scoped): rolled-up spend + `failures_24h` — the cheapest #4/#6 poll.
- `/health` (App B) + `/api/health` (App A): liveness for #1/#2/#9.
- Railway per-service metrics/logs: 5xx rate, restarts, CPU/mem for #1/#2/#5/#7.

## Wiring recommendation (operator-side, not done here)
1. **Cheapest:** a small owner-authenticated cron (every 1–5 min) that reads `/admin/spend` + `/health` + `/api/health`
   and fires on the thresholds above. Owner scope is required for `/admin/spend` — use a dedicated monitoring
   principal, never embed the owner API_KEY in the checker.
2. **Railway-native:** enable Railway deploy/health alerts on both services (covers #1/#2/#5/#7 restarts + 5xx).
3. Route CRITICAL rows to a pager; WARNING rows to a log/dashboard.

Not wired from this session: alerting delivery requires infra credentials + an owner-scoped monitor this session does
not hold. The thresholds are specified so the operator (or a certified monitor) implements them without ambiguity.

---
## IMPLEMENTATION STATUS (updated 2026-08-29) — DEFINED → IMPLEMENTED → DELIVERED → CERTIFIED
These thresholds are now **implemented and certified** by the external monitor `ops/monitor/` (see
`docs/WHEELLSVERSE_PROD_OBSERVABILITY.md`). Per-alert attributes are now concrete:

- **SOURCE/SIGNAL/THRESHOLD/WINDOW/SEVERITY**: encoded in `ops/monitor/run.py:evaluate()` + `core.py:THRESHOLDS`.
- **DESTINATION**: the existing **Telegram** owner channel (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, App A env), via
  `ops/monitor/delivery.py` — same transport as `observability.notify()`.
- **DEDUPLICATION / COOLDOWN / RECOVERY**: `core.AlertState` — key `env:service:signal:severity`, 900s cooldown,
  single recovery on clear, CRITICAL escalation bypasses cooldown.
- **REDACTION**: `core.redact()` — no payload carries a secret (tested).
- **RUNBOOK**: `docs/WHEELLSVERSE_PROD_ALERT_RUNBOOKS.md`.
- **TEST METHOD**: `python3 -m ops.monitor.test_monitor` (44/44) + live tick + real Telegram delivery + recovery cert.

Status: **CERTIFIED** for one-shot invocation + real delivery + soak. **Continuous scheduling** (a Railway cron or an
App-B in-process scheduler) is DEFINED + IMPLEMENTED-in-pattern but **NOT yet activated** (activation redeploys/provisions
prod → gated operator decision). The DEFINED ≠ IMPLEMENTED ≠ DELIVERED ≠ CERTIFIED distinction holds: everything except
continuous scheduling is DELIVERED + CERTIFIED; continuous scheduling is DEFINED + ready.
