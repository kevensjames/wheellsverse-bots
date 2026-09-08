# KAI Computer Operations — Rollback and Recovery

**Nothing in this document is executed during development.** It is the procedure to
follow if this feature is ever enabled and has to be withdrawn.

## Why `git reset --hard` is not the procedure

An earlier status report of mine suggested `git reset --hard <sha>` to undo this work.
That was wrong and is corrected here. `reset --hard` destroys uncommitted work in the
worktree, discards commits without leaving a trace for anyone else who fetched them, and
on a shared branch invites a force-push that rewrites history other people have based
work on. It also does nothing about the parts of a rollback that actually matter — a
running connector, an enrolled device credential, an applied migration — so it creates
the *appearance* of a rollback while the real exposure continues.

Rollback here is ordered by blast radius: stop the behaviour first, revoke authority
second, and only then touch code or schema.

## Order of operations

### 1. Preserve the current state before changing anything

```sh
cd /Users/jhonwheeler/wheellsverse-kai-compute
git tag -a computer-ops-rollback-$(date +%Y%m%d-%H%M) -m "state at rollback decision"
git branch backup/computer-ops-$(date +%Y%m%d-%H%M)
```

A tag and a branch cost nothing and mean the decision is reversible. Do this even when
the rollback feels obvious — a rollback made under pressure is exactly when the evidence
of what happened is most likely to be needed later.

### 2. Disable the feature flags (fastest effective control)

Flags are the only step that takes effect without a deploy, so they come first.

```
KAI_COMPUTER_OPS_ENABLED=false
KAI_CAPABILITY_EXECUTION_ENABLED=false
```

Both default to `false`. Disabling removes the HTTP surface entirely: the routers are
mounted only when the flag is on. `/health` continues to answer and reports the
subsystem as `DISABLED`.

### 3. Stop the local connector

```sh
ops/computer-ops/runtime/kai-harness-ctl.sh stop
ops/computer-ops/runtime/kai-connector-ctl.sh stop      # if the connector was started
mount | grep KAI                                        # expect no output
```

If a mission volume is still mounted, the connector did not tear down cleanly:

```sh
hdiutil detach /Volumes/KAI-<mission-id> -force
rm -f /Users/jhonwheeler/kai-harness-runtime/volumes/<mission-id>.sparseimage
```

The image contains mission output. Copy it somewhere durable first if it is evidence.

### 4. Revoke the device credential

Disabling a flag stops KAI handing out work; it does not invalidate a credential the
device already holds. Revoke explicitly:

- Holding Command → KAI Computer Operations → Devices → **REVOKE DEVICE**, or
- `POST /admin/kai/computer-operations/devices/{device_id}/revoke`

Revocation sets status `REVOKED` **and** clears granted scopes, so code that checks only
scopes still denies. Then remove the device-side key so a restored backup cannot
re-authenticate:

```sh
security delete-generic-password -s com.wheellsverse.kai.device -a <device_id>
```

### 5. Revert merged code

For commits already merged to a shared branch:

```sh
git revert --no-commit <oldest-sha>^..<newest-sha>
git commit -m "revert: withdraw KAI computer operations (see docs/computer-ops/50-ROLLBACK.md)"
```

`revert` records the withdrawal as history rather than erasing it, which keeps anyone
who already fetched the commits consistent with the remote.

For an **unmerged** feature branch, nothing needs reverting: stop using it and leave the
branch in place. Deleting it is optional cleanup, not rollback, and the backup branch
from step 1 exists precisely so that choice stays reversible.

### 6. Database — only if migration 0008 was actually applied

Check first. Do not "roll back" a migration that never ran:

```sh
cd backend && alembic current
```

If it reports `0008_add_kai_devices`, **back up before touching it**:

```sh
pg_dump "$DATABASE_URL" -Fc -f kai-pre-rollback-$(date +%Y%m%d-%H%M).dump
```

Then read the next section before running `alembic downgrade`, because the downgrade is
deliberately partial.

## Migration 0008 downgrade is PARTIAL — by design

`alembic downgrade 0007` drops only the three indexes. **The tables
`kai_devices`, `kai_device_pairings` and `kai_device_nonces` remain.** This is
intentional, and it means the downgrade does NOT restore the 0007 schema byte for byte.

The reason is that these rows are the audit trail of which machines were trusted, when,
by whom, and which device authentications were spent. A code rollback exists to withdraw
behaviour; destroying the record of what that behaviour did while it was enabled is a
different and irreversible act. The tables are additive and unreferenced, so application
code that predates 0008 sees three unread tables rather than a broken schema — the
downgrade restores *compatibility*, not the exact schema.

If the tables genuinely must go — decommissioning the feature entirely, or a data-
retention obligation — that is a separate, deliberate operator step after the backup:

```sql
DROP TABLE IF EXISTS kai_device_nonces;
DROP TABLE IF EXISTS kai_device_pairings;
DROP TABLE IF EXISTS kai_devices;
```

Do not describe the standard downgrade as a full schema rollback. It is not one.

## What rollback does NOT undo

State these plainly rather than letting them be discovered later:

- **Actions already taken.** Evidence of completed work is retained deliberately;
  rollback halts future work, it does not rewrite what happened.
- **macOS TCC grants.** If Screen Recording or Accessibility were ever granted, they
  persist until removed by hand in System Settings → Privacy & Security. No code path
  can revoke them.
- **A launchd service**, if one was ever loaded: `launchctl bootout gui/$(id -u)/com.wheellsverse.kai-harness`.
- **The pinned harness runtime** at `/Users/jhonwheeler/kai-harness-runtime`, which is
  outside the repository. Remove with `kai-harness-ctl.sh uninstall`.

## Verification after rollback

```sh
curl -s $BASE/health | jq '.status, .subsystems'      # capability_execution: DISABLED
curl -s -o /dev/null -w '%{http_code}\n' $BASE/admin/kai/computer-operations/devices   # 404 or 401/403
mount | grep KAI                                       # no output
pgrep -f "dsh --profile acp" || echo "no harness workers"
cd backend && alembic current                          # expected revision
```

A rollback is complete when the flags are off, no connector or worker process is
running, no mission volume is mounted, the device credential is revoked, and the routes
are gone.
