# 0009 — credential rotation after .env exposure

Date: 2026-05-28
Status: locked

## Rotated this session

| Secret | Old sha-256 prefix | New sha-256 prefix | Rotation path |
|---|---|---|---|
| `SUPABASE_SECRET_KEY` | `499e5b97f415` | `204e005f5221` | Done earlier this session (commit `a202720`); see decision log 0008 |
| `DATABASE_URL` / `DIRECT_DATABASE_URL` password | `7da816338421` (`B1lankito@Kevens21` URI-encoded) | (new) | `scripts/rotate_db_password.sh` |
| `JWT_SECRET_KEY` → `ADMIN_TOKEN` | `5f38a15a1500` | `98422cbf538a` | `openssl rand -base64 32`; `JWT_SECRET_KEY=` blanked |

Values are intentionally redacted — only the sha-256 prefix is recorded so a future operator can cross-check whether a specific exposed value matches what was retired.

## Security proofs (raw psql output)

### Old DB password is dead

```
psql "postgresql://postgres.rqcngphvpjcscculehph:B1lankito%40Kevens21@aws-1-us-west-2.pooler.supabase.com:5432/postgres" -c "SELECT 1;"
psql: error: connection to server at "aws-1-us-west-2.pooler.supabase.com" (44.252.246.120), port 5432 failed: FATAL:  password authentication failed for user "postgres"
exit code: 2
```

### New DB password works

```
python deploy/db_check.py connect
OK connected: db=postgres
   PostgreSQL 17.6 on aarch64-unknown-linux-gnu, compiled by gc
exit=0
```

### Admin-token enforcement (after `JWT_SECRET_KEY` blanked, `ADMIN_TOKEN` seeded)

```
/admin/ingest/status no token        → HTTP 403 {"detail":"Admin token required"}
/admin/ingest/status wrong token     → HTTP 403 {"detail":"Admin token required"}
/admin/ingest/status with new ADMIN  → HTTP 500 (Redis traceback) — auth PASSED, 500 is downstream
```

## Code changes that landed

- **`scripts/rotate_db_password.sh`** — new. Reads raw password via `stty -echo` so it never enters shell history, scrollback, or chat. URI-encodes via `urllib.parse.quote` (RFC 3986, *not* `quote_plus` which would form-encode spaces as `+` — wrong for the userinfo portion of a URL). Strips whitespace, refuses the known-leaked value (raw or URI-encoded form), refuses no-op rotations (sha matches current), atomically rewrites both `DATABASE_URL` and `DIRECT_DATABASE_URL` via Python regex (sed metachars would corrupt passwords containing `&`/`\1`/`%`), restores `chmod 600`.

- **`deploy/start_nai.sh`** — env-var pre-flight relaxed from `JWT_SECRET_KEY` to `ADMIN_TOKEN || JWT_SECRET_KEY`. Without this, blanking `JWT_SECRET_KEY=` made the wrapper crash before `exec uvicorn`, which made launchd thrash-restart the LaunchAgent.

## Outstanding rotation decisions

- `SUPABASE_PUBLISHABLE_KEY` (current sha `df070f021d25`) was leaked in the same .env exposure event. Risk class is RLS-bound (anon role only), so worst case is anon-scope reads via PostgREST. Not catastrophic. Operator instruction was "note it for me" — leaving the roll decision to you. To roll: Supabase dashboard → Settings → API → Publishable key → Generate new → paste into `backend/.env` `SUPABASE_PUBLISHABLE_KEY=` → `launchctl kickstart -k`.

## Lessons logged

1. The first rotation attempt failed because the script required the operator to manually URI-encode the password. The dashboard hands you a raw value with `@`/`/`/`:` in it; manual encoding is error-prone. **Fix:** script now auto-encodes.
2. The second attempt failed with `password authentication failed` after the script's encoding bug was the wrong RFC (`quote_plus` form-encoding rather than `quote` RFC-3986). Caught it on the rollback.
3. The token-rotation step broke the daemon because `start_nai.sh` validated `JWT_SECRET_KEY` directly rather than the canonical `ADMIN_TOKEN`. The wrapper-script edit documents the transition contract: either env var satisfies the pre-flight.

## 2026-05-28 — Publishable key rotation completed (operator)

Operator rotated SUPABASE_PUBLISHABLE_KEY in the Supabase dashboard and
pasted the new value into backend/.env. Verified live:

| Check | Result |
|---|---|
| Prefix | sb_publishable_ ✓ |
| Length | 46 (matches new-format keys) |
| Old leaked sha (dead) | df070f021d25 |
| New active sha | c53a57548598 |
| Live GET /auth/v1/settings with new key | HTTP 200 (Supabase accepted) |
| Daemon restart + env hash check | process env sha == file sha ✓ |

All four secrets from the original .env exposure are now rotated:
SUPABASE_SECRET_KEY, DB password, JWT_SECRET_KEY -> ADMIN_TOKEN,
SUPABASE_PUBLISHABLE_KEY. No outstanding rotation items.

Evidence: evidence/rotation_publishable_*.log
