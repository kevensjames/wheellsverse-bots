# Incident: production credentials printed in plaintext during a release session

**Classification:** credential exposure. No unauthorized access observed; no data loss; no
application change.
**Status:** CONTAINED. All four exposed credential families rotated and the old values proven
rejected.
**This record contains no secret, no connection-string password, no token and no reversible value.**
Fingerprints below are `sha256(local_salt || value)[:12]` — bounded, salted, and meaningless without
the operator's local salt file, which is not committed.

---

## 1. What happened

| Field | Value |
|---|---|
| When | 2026-09-07, during PR #70 pre-merge preparation |
| Actor | The release assistant (automation acting under owner direction) |
| Trigger | `railway variables --json` for `kai-prod` inspected with `head`/`tail` while debugging a JSON parse failure |
| Result | Plaintext production values written to the session transcript and its logs |
| Unauthorized use | **None observed.** No request was made with these values by any third party; exposure was to the operator's own transcript and log storage |

**Root cause, precisely.** A context guard printed diagnostics to **stdout**, which corrupted the JSON
payload that a redacting filter was meant to parse. When the parse failed, the raw output was
inspected with `head`/`tail` — on a command whose entire output is secrets by definition. Every other
read in the session went through a redacting filter and leaked nothing.

Two defects, not one:

1. A diagnostic channel shared with a data channel. Fixed: guard diagnostics now go to stderr, so
   stdout carries only the payload.
2. A debugging reflex applied to a secret-bearing command. Fixed by policy: credential operations use
   stdin or a redacting reader, and emit only names, bounded fingerprints and status.

## 2. Exposed credential families and their consumers

Inventory was taken across **both** production Railway projects, not just the two applications.

| Family | Consumers found | Storage form |
|---|---|---|
| `API_KEY` (App B) | `kai-prod` | literal |
| `SESSION_SIGNING_SECRET` | `kai-prod`, `wheellsverse-v2`, `kai-prod-monitor` | literal, one shared value |
| PostgreSQL password | `kai-prod`, `kai-briefing-cron`, `kai-watch-cron`, `Postgres` (`DATABASE_URL`, `PGPASSWORD`, `POSTGRES_PASSWORD`) | literal |
| Redis password | `kai-prod` (`REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`), `kai-briefing-cron`, `kai-watch-cron`, `Redis` (`REDIS_URL`, `REDIS_PASSWORD`, `REDISPASSWORD`) | literal |

No consumer used a Railway variable **reference**; every copy was a literal and had to be updated
individually. That is why the inventory ran before any rotation.

**App A's `API_KEY` is a different value and was not exposed.** It was left in place; rotating it was
outside the authorized incident scope. It remains a candidate for precautionary rotation.

**Latent defect found while rotating:** `CELERY_RESULT_BACKEND` on `kai-prod` carried a *stale* Redis
password that did not match the live Redis credential, so the Celery result backend could not have
authenticated. All three Redis URLs are now consistent.

## 3. Rotation performed

| Family | Method | Old → new fingerprint |
|---|---|---|
| App B `API_KEY` | New CSPRNG value, set via stdin | `d38bb0d61db9` → `ef92404d6b45` |
| `SESSION_SIGNING_SECRET` | One new value written to all three consumers | `17e986d5ed2c` → `0d736984f636` |
| PostgreSQL | `ALTER USER postgres PASSWORD` **at the source**, plus every consumer URL | `8c9ae981b7a3` → `32cbc2b2126c` |
| Redis | New password on the Railway source variables, then service restart | `e9bc8183a4fe` → `ab2150462095` |

All four fingerprints are distinct; no rotated credential equals another.

### Why PostgreSQL was rotated in place rather than via a new least-privilege role

The preferred dual-credential transition was **not** performed, deliberately. The application connects
as the `postgres` **superuser**, and every table in the database is owned by that role. A
least-privilege role would therefore require either transferring ownership of 24 tables or granting
`postgres` to the new role. Ownership transfer changes which migrations can run (`ALTER TABLE`
requires ownership; `CREATE EXTENSION` requires superuser), and granting `postgres` to the new role
would not be least privilege at all.

Either option is an application-behaviour change, which the incident authorization explicitly
excluded. In-place rotation of the `postgres` role's password is a rotation **at the credential
source** — not an edit of a copied URL — and it fully revokes the exposed value. Introducing a
least-privilege application role remains recommended as a separate reviewed change.

### Why Redis was rotated through the Railway variable

Redis reports `config_file = (none)`. With no configuration file, `CONFIG SET requirepass` cannot be
persisted by `CONFIG REWRITE`, and an `ACL SETUSER` change would be lost on the next restart. The
Railway environment variable is therefore the authoritative source of the password, applied at
container start. Rotation was: update the source variables, restart the Redis service so the new
password takes effect, then update and restart every consumer. The keyspace was empty (`dbsize 0`)
before and after, so no queue data was lost or duplicated.

## 4. Revocation proof

- **PostgreSQL old credential rejected** — proven live: after `ALTER USER`, a fresh connection using
  the previous URL raised `OperationalError`, while the new credential connected successfully.
- **Redis password changed at the source** — the pre-rotation `ACL LIST` password hash is absent from
  the live ACL, and a deliberately wrong password is refused.
- **App B API key** — a non-configured key is refused (HTTP 403) and the configured key's fingerprint
  no longer matches the exposed value.
- **Sessions** — a cookie signed with a non-configured secret is refused (HTTP 401); the configured
  secret's fingerprint changed on all three services, so every session minted before the rotation is
  in the rejected class.

## 5. Service impact

Configuration redeployment used Railway's redeploy of each service's **existing successful artifact**.
No new or untracked source entered production, and `--from-source` was not used.

**This was not zero downtime.** Redis restarted before its consumers, so between those restarts the
consumers held a password Redis no longer accepted. Owner sessions were invalidated by design and
every signed-in operator was signed out. Both applications returned healthy afterwards, and an owner
was able to obtain a new session and reach protected admin JSON.

## 6. State proven unchanged

Database revision `0006_add_kai_api_keys`; `holding_action_nonces` absent; 11 proposals with an
unchanged content digest; proposal statuses `executed 2 / proposed 9`; `holding_timeline` 15 rows;
zero `holding.proposal.*` audit events added. The audit log grew by exactly one row — an hourly
`holding.morning_briefing.generated` event written by the pre-existing scheduled cron, whose cadence
(02:14, 03:13, 04:14 UTC) brackets the incident window and is independent of it.

All eight authority flags remained OFF throughout. Production git stayed at
`5e767a4e8df9e49f4a43a69c07e3464e8477a04f`; nothing was merged and migration 0007 was not applied.

## 7. Evidence superseded by this rotation

Not deleted — superseded, and listed here so no later reader treats it as current:

1. **The PR #70 rollback deployment pair** (App A `c81a3b11-d096-4fa5-8c1c-53215ae2e568`, App B
   `e6436cc1-1118-4ded-a11e-7678e2625cf1`) is superseded. Configuration redeployment created a new
   production baseline; the current serving deployments are recorded in the session report.
2. **Any production verification performed with an owner session minted before this rotation.** Those
   sessions are now invalid; the checks they supported must be re-run against the new baseline before
   being cited again.
3. **`docs/PRODUCTION_VERIFIER_VARIABLE_PLAN.md` §2's separation claims** remain correct in substance,
   but its comparison targets changed: the production session secret it says a verifier secret must
   differ from is now a different value.

The PR #70 staging certification is **not** superseded. It used staging credentials, which were not
exposed, and staging was not touched by this incident.

## 8. Follow-ups

1. Introduce a least-privilege PostgreSQL application role, with ownership handled deliberately, as a
   reviewed change (see §3).
2. Decide whether to rotate App A's `API_KEY` precautionarily; it was not exposed.
3. Consider Railway variable **references** instead of literal copies, so a future rotation updates
   one source rather than eleven copies.
4. Re-approve PR #70 against the new production baseline before resuming that deployment.
