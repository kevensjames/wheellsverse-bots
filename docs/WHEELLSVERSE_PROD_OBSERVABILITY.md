# WHEELLSVERSE PRODUCTION — OBSERVABILITY & ALERT DELIVERY
## 2026-08-29 · External monitor for the live governed KAI stack · Money mode MOCK

Makes the production stack (App A `app.wheellsverse.com` ⇄ App B `kai-prod`) actively self-monitoring:
`failure → detection → classification → alert → owner notification → recovery/escalation → auditable evidence`.
No new KAI capabilities, no widened permissions, no financial mutations, no deployment-architecture change.

## Architecture — EXTERNAL monitor (reuses existing infrastructure)
`ops/monitor/` is a standalone, read-only monitor. It touches **neither app's request path**; it runs with App A's
env injected (`railway run … -s wheellsverse-v2`), which provides the **existing Telegram owner channel**
(`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` — the same channel `backend/app/services/observability.py` uses) and the
shared `SESSION_SIGNING_SECRET` (matches App B) for owner-scoped probes.

Why external, not in-process: (1) honors "do not change the production deployment architecture" — no App A/B rebuild;
(2) fails honestly — an in-process monitor cannot report on its own process dying, an external one can; (3) reuses the
already-certified telemetry endpoints instead of adding surface to the governed apps.

| Module | Responsibility | Testable offline |
|---|---|---|
| `ops/monitor/core.py` | Alert envelope, **redaction**, severity, thresholds, dedup/cooldown/recovery state | ✅ pure |
| `ops/monitor/delivery.py` | Telegram + Test adapters; **delivery-failure surfaced** | ✅ (Test adapter) |
| `ops/monitor/collectors.py` | Live signal collection (App A/B public + owner-scoped `/admin/spend` + canaries) | live |
| `ops/monitor/run.py` | `evaluate()` (pure snapshot→alerts), `tick()`, CLI (`--once/--live/--send-test/--send-recovery/--soak`) | ✅ evaluate() |
| `ops/monitor/test_monitor.py` | 44 deterministic tests | ✅ |

## Signal sources (9 families)
| # | Family | Source | Detection |
|---|--------|--------|-----------|
| A | App A 5xx | `GET /api/health` | status 0/≥500 → HIGH |
| B | App B 5xx | `GET /health` | status 0/≥500 → HIGH; fail-closed 404 is **not** a B 5xx |
| C | Auth anomalies / **bypass** | auth-matrix canary through bridge | anon 200 or operator 200 → **CRITICAL**; owner denied → HIGH |
| D | OpenAI / provider + spend | owner `GET /admin/spend` | cost >$5 warn / >$20 HIGH; failures_24h ≥5 warn / ≥20 HIGH |
| E | Postgres / Redis | `/admin/spend` reads `llm_call_log` (PG proxy) | spend fails for valid owner → HIGH `db_redis` |
| F | **Audit-write failure** | governed canary → re-read `/admin/spend` | stream 200 but usage **not** incremented → **CRITICAL** `audit_gap` |
| G | Workers | (governed KAI is **synchronous** — no worker dependency) | N/A for governed path; Celery serves market-data only |
| H | SSE / streaming | governed stream canary | 502/504 → HIGH; 200 w/ 0 frames → WARNING |
| I | Latency | health probe timings | p95 >2000ms warn / >5000ms HIGH (baseline A~274ms / B~209ms) |

Plus control-plane signals: **kill-switch intent distinction** (bridge disabled → WARNING labeled "intentional/kill-switch";
bridge enabled but governed path failing → HIGH "unexpected unavailability"), and registry drift (≠39 → WARNING).

## Severity model
`INFO · WARNING · HIGH · CRITICAL`. CRITICAL = authorization bypass, audit-integrity failure (audit_gap), Postgres
unavailable, bridge unexpectedly fails open. HIGH = sustained 5xx, provider unavailable, SSE 502/504, owner-access
regression. WARNING = elevated latency/provider errors, spend approaching cap, bridge intentionally disabled, drift.
Expected 401/403 governance denials are **never** an incident by themselves.

## Redaction (secret-free by construction)
`core.redact()` fully redacts values of `SECRET_KEYS` (authorization, cookie, set-cookie, x-api-key, api_key,
session_signing_secret, openai_api_key, database_url, redis_url, telegram_bot_token, stripe_secret_key, wv_session)
and scrubs `SECRET_PATTERNS` (wv_session=…, api_key=…, bearer …, postgres://…, redis://…, sk-…, telegram id:hash,
40+ hex) from every free-text field. Every payload passes through `safe_payload()`/`render_text()` before delivery.
Tested against Authorization/Cookie/Set-Cookie/X-API-Key/API_KEY/SESSION_SIGNING_SECRET/OPENAI_API_KEY/DATABASE_URL/REDIS_URL.

## Deduplication / cooldown / recovery
State keyed by `env:service:signal:severity` (JSON file). First breach → ALERT; continued breach within `cooldown`
(default 900s) → suppressed; past cooldown → re-notify; signal clears → single RECOVERY; later re-breach → NEW alert.
Escalation to CRITICAL always delivers immediately, even inside another signal's cooldown. Distinct CRITICALs are never
mutually suppressed.

## Delivery + self-failure (item 14)
Delivery via the existing Telegram channel; a failed send returns `ok=False` (never swallowed) and is surfaced as a
`monitor_self` HIGH alert + flips `tick.healthy=False`. Collection errors on core probes likewise raise `monitor_self`.
The monitor never reports "healthy" when collection or delivery evidence is missing — it fails honestly.

## Kill-switch (item 9, reconfirmed — NOT flipped)
`KAI_BRIDGE_ENABLED=false` on App A → governed route fail-closes to 404 (`core/kai_bridge.py:168`, first gate, no
fallback), Command Center intact, App B independently healthy. Every HIGH/CRITICAL runbook routes here. The monitor
distinguishes intentional disable (WARNING) from unexpected unavailability (HIGH) so an operator kill-switch is not
misread as an incident. See `docs/WHEELLSVERSE_PROD_ALERT_RUNBOOKS.md`.

## Continuous operation — DEFINED ≠ IMPLEMENTED ≠ DELIVERED ≠ CERTIFIED
- **DEFINED + IMPLEMENTED + DELIVERED + CERTIFIED (now):** the full pipeline runs against live prod, delivers a real
  alert + recovery to the owner Telegram, and a soak observed the live system (below). One-shot / soak invocation is
  `railway run -s wheellsverse-v2 python3 -m ops.monitor.run …`.
- **NOT yet activated (needs an operator decision — prod-touching, so gated):** continuous scheduling. Two options,
  both reuse existing patterns:
  1. **Railway cron service** in the App A project running `python3 -m ops.monitor.run --live` every N minutes
     (inherits App A env → Telegram + secret). No App A/B code change. Recommended.
  2. **App B in-process scheduler** (`backend/app/services/monitor/scheduler.py`, mirroring digest/checkin/sol at
     `backend/app/main.py` lifespan) — requires adding `TELEGRAM_BOT_TOKEN`/`CHAT_ID` to App B env + an App B redeploy.
  Neither was activated in this pass (would rebuild/redeploy prod); both are documented for a gated go.

## Testing evidence
- `python3 -m ops.monitor.test_monitor` → **44/44 PASS** (thresholds, severity, dedup, cooldown, recovery, redaction,
  delivery adapter, collection-failure, auth-anomaly, provider, db/redis, audit, sse, latency, self-failure).
- Live dry tick vs prod → `healthy:true`, 0 alerts, 0 false positives.
- **Real delivery certification** → INFO alert Telegram HTTP 200, `leaked_secret_tokens:[]`.
- **Recovery certification** → recovery notification Telegram HTTP 200, secret-free.
- **Capability boundary** (item 10) → 8/8; `empire`/`payloads`/`seclists` `.selectable()==False` via real prod code.

## Known limitations
1. **Audit-write swallow (in-process):** `router.py:_log_failure_safe` and `governance/audit_log.py` swallow persistence
   failures (WARNING log only) — a governed call can return 200 while its audit write fails. The monitor **detects this
   externally** (canary + usage-increment check → `audit_gap` CRITICAL). Recommended future hardening (gated App B change,
   NOT done here per "do not redesign audit architecture"): have those except-branches also call `observability.notify()`
   so the swallow is alerted at the source.
2. **Redis** has no direct external probe; inferred via governed-canary success + PG reachability. Direct probe would
   need an in-App-B health change.
3. **Worker signal (#7)** is N/A for governed KAI (synchronous path); the Celery worker serves market-data tasks only.
4. **Continuous scheduling** not yet activated (one-shot + soak certified); see above.
