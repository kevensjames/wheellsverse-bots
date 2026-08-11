# Deployment Gate

**Status: `BLOCKED_BY_EXTERNAL_CREDENTIAL_GATE`.**

Merging the ten PRs to `istanbul` does **not** deploy anything — the deploy workflows
(`docker-push.yml`, `brain-feedback-ingest.yml`) trigger only on push to `main`. Deployment
is a separate, deliberate step, and it stays blocked until every item below is verified.

Do not deploy on assumption. The following are **valid blockers**, not routine questions:
missing verified credentials, a broken auto-deploy path, the Supabase bootstrap dependency
(see the DB-bootstrap issue), and uncertain money-mode configuration.

## Required evidence (all must be verified, not assumed)

| Area | What must be confirmed | Status |
|---|---|---|
| Railway | account + project resolved; authenticated CLI/session; exact service name | **UNVERIFIED** |
| Cloudflare | account + tunnel resolved; exact tunnel/route names | **UNVERIFIED** |
| Deploy trigger | how prod actually deploys (recorded: manual `cd backend && railway up`; auto-deploy webhook recorded broken — **verify**) | **UNVERIFIED** |
| Current prod commit | what is running now, for a known rollback target | **UNVERIFIED** |
| Env vars | full inventory present on the target (`PRODUCTION_ENV_CHECKLIST.md`) | **UNVERIFIED** |
| Backups | DB backup taken immediately before migration | **UNVERIFIED** |
| Rollback | exact command + target verified (`ROLLBACK_RUNBOOK.md`) | **UNVERIFIED** |
| Health / alerts | `/health` reachable; alert delivery works end-to-end | **UNVERIFIED** |
| **Money mode** | Stripe mode (test/live); Dwolla mode (sandbox/prod); Sol money mode (recorded: **MOCK** money in prod, `DWOLLA_ALLOW_PRODUCTION` is the latch) | **UNVERIFIED — verify explicitly** |
| Migration target | prod DB is at `0006` (or known state); `0007`→`0008` will apply from there | **UNVERIFIED** |
| DB bootstrap | prod `profiles`/`conversations` exist (Supabase-provisioned) — migrations assume them | see DB-bootstrap issue |

> "Recorded" values come from the operator's own prior notes and **must be re-verified with a
> live check before trusting them** — they were true at some past point, not necessarily now.

## Gate scripts

- `scripts/predeploy_check.py` — fail-closed; run with the **target** env loaded. Blocks on
  weak admin token, `DEBUG` on, missing `DATABASE_URL`, missing required deps, ambiguous
  money mode, missing webhook secret when Stripe is on.
- `scripts/postdeploy_smoke.py` — read-only; `/health`, `/version`, and confirms an admin
  route refuses an unauthenticated request. No money movement.

## Order (only after every UNVERIFIED above is resolved)

1. `istanbul` → `main` (this is what triggers the build).
2. Back up prod DB.
3. `predeploy_check.py` PASS on the prod env.
4. Deploy to staging → `postdeploy_smoke.py` → auth/admin/provider checks.
5. Apply migration `0007`→`0008` (additive; `kai_code_chunks`, `kai_swe_tasks`).
6. Canary / limited prod rollout → monitor.
7. Expand → `postdeploy_smoke.py` on prod → keep rollback ready.

Automatic rollback triggers and the exact procedure: `ROLLBACK_RUNBOOK.md`.
