# Pre-`0007` recoverable snapshot — record and supersession

Railway's native volume backups and point-in-time recovery are **Pro-plan features and are not
available on this account**. The production approval gate allows *"a current database backup **or
recoverable snapshot**"*, so a tested logical snapshot stands in for the native backup.

This file records **both** snapshot references. The first is superseded, not erased.

---

## Reference 1 — SUPERSEDED (do not rely on)

| Field | Value |
|---|---|
| Name | `kai-prod_full_logical_2026-09-08T04-03-30Z_pre0007.json` |
| Captured | 2026-09-08T04:03:30.764909+00:00 |
| SHA-256 | `982320d012644d9599a9bf09476f692bf56f4a4087b0e5b6c9ca4830ba80c8d1` |
| Contents | 24 tables, 1 529 rows, 8 sequences, alembic `0006_add_kai_api_keys` |
| Restore rehearsal | 24/24 tables exact |
| **Status** | **SUPERSEDED — withdrawn as the gate reference** |

**Why superseded.** The capture ran on a connection at the PostgreSQL default isolation level,
`READ COMMITTED`, with `transaction_read_only = off`. In `READ COMMITTED` **every statement takes a
new MVCC snapshot**, so each of the 24 tables could have been read at a different database moment.
Nothing indicates the capture was actually torn — but the guarantee was absent, and a concurrent
commit during the capture window (the hourly briefing cron writes to `audit_log`) could have produced
an inconsistent set. A backup whose internal consistency cannot be demonstrated is not an acceptable
recovery point.

Its plaintext copies have been removed. This record is retained so the earlier acceptance remains
auditable.

## Reference 2 — OPERATIVE

| Field | Value |
|---|---|
| Name | `kai-prod_full_logical_2026-09-08T04-11-29Z_pre0007_consistent.json` |
| Captured | 2026-09-08T04:11:29.728445+00:00 |
| SHA-256 | `df91ebd0342a539370e91bedc9d6e30958256fe34185c1781ee9530610e93c2c` |
| Contents | 24 tables, 1 531 rows, 8 sequences, alembic `0006_add_kai_api_keys` |
| Restore rehearsal | **24/24 tables exact**, including all 8 release-critical tables |
| Status | **ACCEPTED as the pre-`0007` recovery point** |

### Consistency proof

Captured inside a single `REPEATABLE READ`, `READ ONLY` transaction opened before any read, so all 24
tables come from one MVCC snapshot. Proven rather than asserted, with the evidence stored inside the
snapshot under `consistency_proof`:

| Property | Observed |
|---|---|
| `transaction_isolation` | `repeatable read` |
| `transaction_read_only` | `on` (the server itself rejects writes) |
| `TimeZone` | `UTC` (canonical timestamp rendering) |
| `pg_current_snapshot()` before all reads | `2572:2572:` |
| `pg_current_snapshot()` after all reads | `2572:2572:` — **identical** |
| `now()` (transaction start) | fixed across the capture |
| `clock_timestamp()` | advanced 04:11:29.746262 → 04:11:29.939628 |
| Tables read in the transaction | 24 |

The advancing wall clock alongside an unchanged transaction snapshot is what rules out the trivial
explanation that no time passed.

### Fidelity

Values are serialized by PostgreSQL via `row_to_json` and restored with `json_populate_record`, so
`jsonb`, arrays, booleans, numerics and timestamps round-trip through their declared types. An earlier
attempt stringified values in Python and failed to restore `holding_proposals`, `audit_log`,
`holding_timeline` and `holding_kpi_history` — which is precisely why the rehearsal exists.

The rehearsal session is pinned to UTC. Without that, nine tables reported false digest mismatches
that were only timezone *rendering* (`…T04:26:09+00:00` vs `…T00:26:09-04:00` — the same instant).

## Storage

| Copy | Location | Protection |
|---|---|---|
| Plaintext (authoritative) | `~/wheellsverse-backups/…_consistent.json` | mode `600`, directory mode `700` |
| Encrypted (off-workstation) | `/Volumes/Wheellsverse/wheellsverse-backups/…_consistent.json.enc` | mode `600`, directory mode `700`, AES-256-CBC, PBKDF2 600 000 iterations, salted |

**Exactly one plaintext copy exists**, in the protected directory. Every other plaintext copy —
including three in the session scratchpad, one of which was world-readable at mode `644` — has been
removed.

**Key handling.** The passphrase was generated with a CSPRNG and written **only** to the macOS login
Keychain, passed through `security -i` on stdin so it never entered argv, shell history or a process
listing, and handed to `openssl` via `-pass env:`. It is not stored beside the backup, not in the
repository, and not in any transcript. Retrieve it with:

```bash
security find-generic-password -s kai-prod-backup-2026-09-08 -a wheellsverse -w
```

**Verified:** encrypted copy exists · decrypt test succeeds · decrypted SHA-256 equals the accepted
snapshot · no production data committed to git or uploaded to any external service.

## Limits of this recovery point

Honest scope, so nobody over-trusts it:

- **Logical, not physical.** It captures the `public` schema's tables, declared types, indexes and
  sequence positions. It does **not** capture roles, grants, extensions, or anything outside `public`.
- **Not PITR.** The recovery point is fixed at 2026-09-08T04:11:29Z. Anything written afterwards —
  the briefing cron adds roughly one `audit_log` row per hour — is not in it.
- **Single key, single machine.** If the Keychain is lost, the encrypted SSD copy cannot be decrypted.
  Keeping the passphrase in a password manager as well is advisable.

For migration `0007` specifically the exposure is small: it is `CREATE TABLE IF NOT EXISTS` plus two
indexes on a **new** table, its `downgrade()` drops no table, and the full up/down/up cycle has been
exercised against PostgreSQL with rows present.
