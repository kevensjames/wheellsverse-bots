# Rollback Runbook

Keep this open during any deploy. Values in `<angle brackets>` are **UNVERIFIED** — fill
from the real environment before you need them (not during the incident).

## Roll back immediately if ANY of these occur

- authentication outage (signup/login failing)
- route-authorization regression (admin/public boundary wrong)
- payment or settlement regression
- migration error / partial migration
- audit-log write failure on a destructive path
- elevated 5xx rate or severe latency regression
- provider-router loop / runaway
- missing required dependency at boot
- repeated process crash / restart loop
- tenant-isolation failure
- health endpoint failing
- unexpected secret exposure
- database corruption signal

## Code rollback (redeploy previous image)

The migrations in this release are **additive** (two new tables), so the previous app
image runs fine against the migrated schema — a code-only rollback is safe and is the
first move.

```bash
# redeploy the last-known-good commit/image
<redeploy command targeting prod_commit = the value recorded in step 0 of the deploy>
python scripts/postdeploy_smoke.py --base-url <prod_url>
```

## Schema rollback (only if the migration itself is implicated)

`0008` and `0007` both have working `downgrade()` (verified: `0008`→`0007` downgrades and
re-upgrades cleanly on real PostgreSQL). Because the tables are new and unused when the
feature flags are OFF, dropping them is low-risk.

```bash
<alembic downgrade 0006_add_kai_api_keys against prod>   # drops kai_swe_tasks + kai_code_chunks
```

Prefer restoring the pre-deploy **backup snapshot** over a live downgrade if there is any
doubt about data written since the migration:

```bash
<restore snapshot taken in deploy step 1>
```

## After rollback

- Confirm `/health` and `postdeploy_smoke.py` are green on the restored version.
- Record what triggered the rollback in the incident log.
- Do not re-attempt the deploy until the trigger's root cause is fixed and re-verified.

## Reversibility of the merge itself (separate from deploy)

If the `istanbul` merge needs undoing (independent of any deploy): `git revert` the ten
merge commits, or reset `istanbul` to `2fe6e46` (the recorded base) **only** if no other
work has landed on top. Prefer revert on a shared branch.
