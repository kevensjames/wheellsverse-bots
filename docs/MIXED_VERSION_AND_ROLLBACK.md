# Deployment order, mixed-version safety, and rollback

This release adds a required action-bound confirmation to proposal execution, plus one additive
table. Both apps change, so the order matters and there is one **operator-critical** step in the
rollback that is not obvious.

---

## 1. What actually differs between production and this release

Verified against production merge `5e767a4e8df9e49f4a43a69c07e3464e8477a04f`:

| Capability | Production App B | This release |
|---|---|---|
| `POST /proposals/{id}/confirm-execute` | **absent** | present |
| `action_confirmation` module | **absent** | present |
| Any reference to `holding_action_nonces` | **none** | required |
| Execute requires a fresh confirmation | no | yes |

So production App B does not know the table exists, and production App A never asks for a
confirmation.

## 2. Deploy App B **before** App A

| Combination | Result |
|---|---|
| old App A → **new App B** | Reads work. Execute arrives with no confirmation and is refused **403 `CONFIRMATION_MISSING`** — fails closed. **Verified live on staging.** |
| **new App A** → old App B | The UI calls `confirm-execute`, which does not exist on old App B → **404**. Execution is impossible and the operator sees a broken control, not a governed refusal. |

Both mixed states are safe in the sense that nothing executes without a confirmation. Only the first
is *coherent*, so App B goes first and is the state the system may sit in between the two deploys.

Live evidence for the first row, staging, App B new / App A not yet redeployed:

```
GET  /admin/kai/holding/proposals?status=proposed   -> 200   (read through the bridge)
POST /admin/kai/holding/proposals/10/execute        -> 403   {"detail":"CONFIRMATION_MISSING"}
```

## 3. Roll back App A **before** App B

The reverse, for the same reason: rolling App B back first would leave new App A calling a
`confirm-execute` route that no longer exists (404). Rolling App A back first returns the system to
the *proven* mixed state in row 1 — old App A, new App B, execution refused closed.

## 4. ⚠ The migration step the rollback needs

`backend/Dockerfile.staging` boots with:

```
... && (cd /app/backend && alembic upgrade head) && uvicorn app.main:app ...
```

It is an `&&` chain, so **if the migration command fails, uvicorn never starts.**

After this release the database is at `0007_add_holding_action_nonces`. Production code does not
contain that revision file. Running its boot command against a `0007` database gives:

```
ERROR [alembic.util.messaging] Can't locate revision identified by '0007_add_holding_action_nonces'
FAILED: Can't locate revision identified by '0007_add_holding_action_nonces'
```

**App B would fail to boot.** This is standard alembic behaviour and applies to every migration in
this project, not only this one — but it makes a naive "redeploy the previous image" rollback fail.

### The correct rollback, in order

```bash
# 1. Roll App A back first (see §3).

# 2. Downgrade the DB while the NEW App B image is still deployed — it is the only one
#    that has the 0007 revision file and can execute its downgrade.
railway ssh --service <appB> -e <env> "cd /app/backend && alembic downgrade 0006_add_kai_api_keys"

# 3. Now roll App B back. Its boot command sees head = 0006 and is a clean no-op.
```

### Why this is safe for evidence

`0007`'s `downgrade()` deliberately **does not drop the table**. It removes only the two indexes this
revision added. The nonce rows are audit evidence of executions that really happened, and rolling
application code back must never destroy evidence.

Full cycle exercised against Postgres, with a row present throughout:

| Step | table | rows | indexes | alembic |
|---|---|---|---|---|
| after deploy | present | 1 | 3 | `0007` |
| after `downgrade 0006` | **present** | **1** | 1 | `0006` |
| old code boots (`upgrade head`, 0007 absent) | present | 1 | 1 | `0006` — **no error** |
| roll forward again | present | **1** | 3 | `0007` |

The table survives, the rows survive, and re-applying `0007` adopts the existing table rather than
failing (`IF NOT EXISTS` throughout, plus `ADD COLUMN IF NOT EXISTS` for `action_digest`).

## 5. Migration compatibility with both code versions

- **New code** requires the table; it is created by `0007`.
- **Old code** contains no reference to `holding_action_nonces` at all (verified: zero matches in
  `backend/` at the production merge). Left in place, the table is inert — an unread table, not a
  broken constraint. Nothing references it, so there is no FK to violate.
- Therefore the only incompatibility is the alembic **version pointer**, handled by §4.
