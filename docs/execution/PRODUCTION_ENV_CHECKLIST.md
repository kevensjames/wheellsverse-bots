# Production Environment Checklist

Confirm each variable on the **target** environment before deploy. `predeploy_check.py`
enforces the fail-closed subset; this is the full inventory. Grouped by risk.

Legend: **[req]** required to boot safely · **[money]** governs real funds ·
**[opt]** optional feature-gate.

## Identity / admin (fail-closed)
- `[req]` `ADMIN_TOKEN` — strong, ≥32 chars, not the example default. Guards all `/admin`.
- `[req]` `APP_ENV` — must be a production marker (NOT `development`/`test`); note the
  SWE mount guard treats non-`{development,dev,local,test,testing,ci}` as prod.
- `[req]` `DEBUG=false`.
- `SUPABASE_URL` / `SUPABASE_PUBLISHABLE_KEY` / `SUPABASE_SECRET_KEY` — user auth (JWKS/ES256).

## Data
- `[req]` `DATABASE_URL` — the prod Postgres. Must already contain the Supabase-provisioned
  `profiles` / `conversations` tables (migrations assume them — see DB-bootstrap issue).
- `REDIS_URL`.

## Money (verify mode EXPLICITLY — never assume)
- `[money]` `STRIPE_SECRET_KEY` — `sk_test_` (test) vs `sk_live_` (real charges).
- `[money]` `STRIPE_WEBHOOK_SECRET` — required if Stripe is configured (forgery guard).
- `[money]` `DWOLLA_KEY` / `DWOLLA_SECRET`.
- `[money]` `DWOLLA_ALLOW_PRODUCTION` — the single latch between sandbox and real ACH.
  Recorded default: prod runs **MOCK** money. **Re-verify before deploy.**
- Sol money mode — confirm sandbox vs production per the Sol config.

## Scopes (governance — PR #43)
- Destructive scopes require the **exact** name (e.g. `KAI_SCOPE_SOL_TRANSFER=1`); a module
  wildcard (`KAI_SCOPE_SOL=1`) no longer grants them. Leave destructive scopes UNSET in prod
  unless deliberately authorizing that action.

## SWE runtime / agent (PRs #41/#42 — keep OFF in prod)
- `KAI_SWE_RUNTIME_ENABLED=0` (default). Never enable on the prod daemon.
- `KAI_SCOPE_SWE_*`, `KAI_SCOPE_SWEPUSH_EXECUTE`, `KAI_SWE_PUSH_TOKEN` — unset in prod.

## Dependencies (PR #48)
- Deploy image installs `PyYAML==6.0.2` and `alembic==1.13.3` and all of `requirements.txt`.
  `composio` is optional — install+pin only if `COMPOSIO_API_KEY` is set.

## Observability
- `[opt]` `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — provider-fallback / deploy alerts.
- `KAI_AUDIT_LOG_PATH` — persistent path for the (now hash-chained, PR #44) audit log.

## Supervision (PR #33, already merged)
- LaunchDaemon for the daemon + supervised `cloudflared`; disk monitor; `/health` check.
