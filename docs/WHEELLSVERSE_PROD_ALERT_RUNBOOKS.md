# WHEELLSVERSE PRODUCTION — ALERT RUNBOOKS
## 2026-08-29 · Actionable response for every HIGH/CRITICAL signal · Money mode MOCK

Principles: **contain first, investigate second**; never auto-remediate destructively; money stays MOCK in every
response (no financial action is ever part of remediation). The universal containment is the kill-switch:
`KAI_BRIDGE_ENABLED=false` on prod App A (grateful-flexibility-production / wheellsverse-v2) → governed route
fail-closes to 404, Command Center stays up, App B stays independently healthy.

---
### AUTHORIZATION_BYPASS — CRITICAL
Trigger: anon reached governed KAI (≠401), or operator reached `kai.ultra` (≠403), or owner denied (401/403 on stream).
1. `KAI_BRIDGE_ENABLED=false` on App A **immediately** (contain).
2. Preserve evidence: correlation IDs, `llm_call_log`, governance `audit_log`, App A access logs. Do not delete.
3. Investigate the auth path (`core/operator_session*`, `core/kai_bridge.py`, App B `require_kai_ultra`).
4. Do **not** re-enable the bridge until the bypass is root-caused and a regression test added.

### AUDIT_WRITE_FAILURE (audit_gap) — CRITICAL
Trigger: governed call returned 200 but its usage/audit row did not persist (executed-but-unaudited).
1. `KAI_BRIDGE_ENABLED=false` (stop privileged governed execution — no execution without durable audit).
2. Preserve logs; check Postgres health (kai-production PG), `llm_call_log` writes, disk/connection limits.
3. Root-cause the persistence failure before resuming governed traffic.
4. Follow-up hardening: make `router._log_failure_safe` / `audit_log` alert on swallow (see OBSERVABILITY known-limitation #1).

### DATABASE_UNAVAILABLE (db_redis) — HIGH
Trigger: `/admin/spend` fails for a valid owner session (Postgres unreachable), or Redis failure.
1. Do **not** perform destructive recovery automatically.
2. Verify Railway PG/Redis in the `kai-production` project (status, connections, storage).
3. If governed path is unstable, `KAI_BRIDGE_ENABLED=false` (fail closed) while investigating.

### APP_B_UNAVAILABLE (app_b_5xx) — HIGH
Trigger: App B `/health` unreachable/5xx, or bridge ENABLED but governed path failing (unexpected).
1. Check App B `/health` + Railway kai-prod logs; inspect correlation IDs for the failing calls.
2. Distinguish provider vs app vs DB vs Redis (see PROVIDER_DEGRADED / DATABASE_UNAVAILABLE).
3. If the governance path is unstable, `KAI_BRIDGE_ENABLED=false` → App A degrades gracefully to fail-closed 404.

### APP_A_5XX — HIGH
Trigger: App A `/api/health` unreachable/5xx.
1. Check Railway wheellsverse-v2 logs + `/api/health`.
2. If bridge-linked, `KAI_BRIDGE_ENABLED=false`; if App A core is broken, redeploy git `production@462adff`
   (git-authoritative — a var change safely rebuilds the same source).

### PROVIDER_DEGRADED (provider) — HIGH/WARNING
Trigger: elevated `failures_24h`, OpenAI 429/5xx/timeouts.
1. Check OpenAI key budget/validity + rate limits. Provider failure must **not** become fake KAI success.
2. If runaway, `KAI_BRIDGE_ENABLED=false` to halt governed traffic; resume when the provider recovers.

### SPEND_THRESHOLD (spend) — HIGH/WARNING
Trigger: OpenAI daily cost > $5 (warn) / > $20 (high), or hourly acceleration.
1. Review `/admin/spend`. This is API cost, **not** user money — money mode is MOCK.
2. If runaway (compromise/loop), `KAI_BRIDGE_ENABLED=false` to contain, then investigate the driver.

### SSE_DEGRADED (sse) — HIGH/WARNING
Trigger: governed stream 502/504, or 200 with 0 frames.
1. Check App B health + bridge timeout config. 502/504 sustained → `KAI_BRIDGE_ENABLED=false`.
2. Normal client cancellations are a feature — exclude them; only abnormal patterns alert.

### LATENCY (latency) — HIGH/WARNING
Trigger: health p95 > 2000ms (warn) / > 5000ms (high). Baseline A~274ms / B~209ms.
1. Investigate App B / OpenAI latency; check Railway CPU/mem. Contain only if user-facing and worsening.

### BRIDGE_DISABLED — WARNING (informational)
Trigger: `KAI_BRIDGE_ENABLED=false` observed. This may be an **intentional kill-switch**. Confirm whether an operator
disabled it; if unexpected, treat as an incident and investigate why governed KAI is down.

### MONITOR_SELF_FAILURE (monitor_self) — HIGH
Trigger: the monitor's own collection or delivery failed. **Do not trust a "healthy" verdict.**
1. Check the monitor host/cron; verify the Telegram channel creds resolve; re-run `--once` manually.
2. A silent monitor is worse than a loud failure — restore evidence collection before relying on green.
