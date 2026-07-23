# Deployment Runbook

Prerequisite: [`DEPLOYMENT_GATE.md`](./DEPLOYMENT_GATE.md) fully satisfied (every
`UNVERIFIED` resolved with a live check). Do not start otherwise.

Values in `<angle brackets>` are **UNVERIFIED** — the operator fills them from the real
Railway/Cloudflare environment. This runbook does not invent them.

## 0. Baseline
- Record current prod commit: `<prod_commit>` (rollback target).
- Confirm `origin/istanbul` == `40fdf90` + any later fixes, and `verify_post_merge.py` PASS.

## 1. Backup
- Take a DB snapshot NOW: `<backup command / Railway snapshot>`.
- Confirm the snapshot exists and its restore path is known (see `ROLLBACK_RUNBOOK.md`).

## 2. Env + deps
```bash
set -a; source <path to prod env file>; set +a
python scripts/predeploy_check.py        # must not print BLOCKED
```
Confirm the venv/image installs `PyYAML`, `alembic`, and all of `requirements.txt`
(the deploy image build is the real check — this repo's dev venv was missing several).

## 3. Promote to main (this triggers the build)
- `istanbul` → `main` via the normal mechanism. `docker-push.yml` builds+pushes the image.

## 4. Staging
- Deploy the built image to staging: `<staging deploy command>`.
- `python scripts/postdeploy_smoke.py --base-url <staging_url>` → SMOKE OK.
- Auth: a real signup+login round-trip returns 201/200 (PR #46 makes this actually work).
- Admin: an admin route with a bad token returns 403; with the real token, 200.
- Provider: one model round-trip succeeds; a forced fallback emits an alert.

## 5. Migration
- Confirm prod DB current head: `<alembic current on prod>` (expect `0006` or known).
- Apply: `<alembic upgrade head against prod>` → head becomes `0008_add_kai_swe_tasks`.
- Both new tables are additive (`kai_code_chunks`, `kai_swe_tasks`); no destructive DDL.
- If `profiles`/`conversations` are absent, STOP — see the DB-bootstrap issue.

## 6. Canary → expand
- Limited prod rollout: `<canary mechanism>`; monitor error rate, latency, `/health`.
- `python scripts/postdeploy_smoke.py --base-url <prod_url>` → SMOKE OK.
- Expand to full rollout only after the canary is clean for `<N>` minutes.

## 7. Confirm feature flags stay OFF
The SWE runtime + agent (PRs #41/#42) are feature-flagged OFF and must remain so in prod:
`KAI_SWE_RUNTIME_ENABLED=0`, no `KAI_SCOPE_SWE_*`/`KAI_SCOPE_SWEPUSH_EXECUTE` set. The mount
guard already refuses to expose them on a prod `APP_ENV`.

## 8. Record
- Deployment commit, migration head, smoke results, timestamp → `EXECUTION_LEDGER`.
- Keep the rollback target and command ready until the deploy is confirmed stable.
