# Post-Merge Verification

Run [`scripts/verify_post_merge.py`](../../scripts/verify_post_merge.py) immediately after
the ten PRs land on `istanbul`. It is **read-only / test-only**: it never deploys, pushes,
merges, mutates production, or touches secrets, and it only runs the suite against an
explicitly-configured disposable test database.

## Run

```bash
cd backend
export DATABASE_URL=postgresql://localhost:5432/wheellsverse_test
export TEST_DATABASE_URL=postgresql://localhost:5432/wheellsverse_test   # SEPARATE lines
export ADMIN_TOKEN=<non-empty test token, >=32 chars>
# venv must have PyYAML + alembic installed (see requirements.txt / DB bootstrap issue)
python ../scripts/verify_post_merge.py --ref origin/istanbul --suite
```

Flags: `--full` runs the governance regression subset; `--suite` also runs the entire
pytest suite; `--ref` lets you dry-run against `integration/verify-all` before the merge.

## What it checks (12)

1. `origin/istanbul` resolves.
2. All 10 PR heads (from `MERGE_MANIFEST.json`) are ancestors of the ref.
3. Exactly one migration head.
4. Migration head == `0008_add_kai_swe_tasks`.
5. No dangling `down_revision`.
6. Migration chain length == 8.
7. `PyYAML` pinned in `requirements.txt`.
8. `composio` documented as an optional extra.
9. `supreme.load_map()` raises instead of fabricating defaults.
10. No silent `return {}` on missing PyYAML.
11. composio misconfig logs ERROR (not a quiet skip).
12. Destructive scopes denied under a module wildcard (governance regression).

## Expected result

```
RESULT: PASS (12 checks)
```

Plus `1020 passed, 18 skipped, 0 failed` when `--suite` is used. If any check FAILs, do
**not** proceed to deployment — reconcile against the manifest first.

## Note on the DB-dependent checks

Checks 12 and the `--suite` run import `app.config`, which requires `DATABASE_URL`. Set the
env as shown; otherwise those checks fail with a config error (not a code defect). This is
the same env every test run needs.
