# Security Scan Report

Automated review of the `wheellsverse-bots` codebase covering: hardcoded
secrets, SQL injection, unvalidated input / command injection, insecure
dependencies, permissive CORS, exposed debug endpoints, and missing auth.

Fixes for the **critical** items are included in this PR. Items marked
"reported only" need a decision or manual follow-up (noted inline).

---

## Critical — fixed in this PR

### 1. Committed secrets (credentials in git)
Two files contained live secrets tracked in the repo:

- `data/canva_backup_codes.txt` — Canva account email + one-time backup codes.
- `data/tiktok_pkce.txt` — TikTok OAuth PKCE code verifier.

`.gitignore` ignored `data/*.json` but not these `.txt` files, so they were
committed. Neither is referenced by any code.

**Fix:** removed both from tracking (`git rm --cached`) and added
`.gitignore` rules for `*_backup_codes.txt` / `*pkce*.txt` under `data/`.

**ACTION STILL REQUIRED (cannot be done from code):** these values remain in
git history and must be treated as compromised — **rotate the Canva backup
codes and re-run the TikTok OAuth flow** (the PKCE verifier is single-use but
should not have been persisted). Optionally purge them from history with
`git filter-repo` / BFG.

### 2. Overly permissive CORS (wildcard + credentials)
Two FastAPI apps set `allow_origins=["*"]` together with
`allow_credentials=True`:

- `second_brain_inbox/api/main.py` — hardcoded `["*"]`.
- `narai/api/main.py` — `NARAI_CORS_ORIGINS` defaulted to `"*"`.

With Starlette's `CORSMiddleware`, a wildcard origin combined with
`allow_credentials=True` causes the middleware to **reflect the caller's
`Origin`** and return `Access-Control-Allow-Credentials: true`, effectively
letting any website make credentialed cross-origin requests to the API.

**Fix:** both apps now read a comma-separated origin list from env
(`SECOND_BRAIN_CORS_ORIGINS` / `NARAI_CORS_ORIGINS`) defaulting to localhost
dev origins, and credentials are only enabled when the resolved list does not
contain `*`.

---

## Reviewed — no action needed

### SQL injection — none found
All dynamic SQL uses parameterized queries (`?` placeholders). The
`f"UPDATE ... SET {cols} ..."` patterns
(`core/api.py`, `core/chat_db.py`, `core/nexora_*.py`,
`backend/app/services/sol/storage.py`) build the SET/column clause from
**hardcoded allowlists of column names**, never from user input, and always
bind values as parameters. No string interpolation of user data into SQL.

### Command injection — low risk
- `narai/api/routes/siteboost_admin.py` builds subprocesses as arg **lists**
  (no `shell=True`), validates category input against a strict regex, and is
  gated by `Depends(verify_admin_api_key)`.
- `money_center/dashboard.py` / `money_center/cli.py` use `shell=True`, but the
  command strings come from a local asset-registry config file, not from HTTP
  request data. These are local operator tools; still worth migrating off
  `shell=True` if the registry ever becomes user-editable.

### Secrets in code — none found
No API keys / tokens hardcoded in Python. `.env.example` files contain only
placeholders. Matches in test files (`whsec_test_...`, `test-secret-not-prod`)
are dummy fixtures.

### Authentication
The primary backend (`backend/app/*`) uses layered auth: Supabase JWT
(`dependencies/supabase_jwt.py`), API-key bearer auth for `/v1/*`
(tier-gated), and an admin-token header for `/admin/*`. Rate limiting
(slowapi) and a security-headers middleware are wired globally.
`core/api.py` also uses auth dependencies throughout.

Minor hardening opportunity (reported only): `dependencies/admin.py` compares
the admin token with `!=` rather than a constant-time comparison
(`hmac.compare_digest`) — a theoretical timing side channel.

---

## Reported only — needs a decision

### 3. Insecure dependency: `litellm==1.80.0`
`requirements.txt` pins `litellm==1.80.0`, which is affected by
**GHSA-jjhc-v7c2-5hh6** (Critical + several High advisories). The pin is
intentional and documented: bumping to a fixed release (`>=1.83.0`) requires
migrating from `openai` 1.x to 2.x. The maintainers note litellm is only used
by operator-run scripts (`infra/brain/router.py` and a few CLIs), not the
public request path. **Recommendation:** schedule the openai 2.x + litellm
upgrade to close the advisory.

### 4. `DEBUG` defaults to `True`
`backend/app/config.py` defaults `DEBUG = True`. Ensure production deployments
set `DEBUG=false` / `APP_ENV=production` (the latter also enables HSTS via the
security-headers middleware). Consider defaulting `DEBUG=False`.

### Debug / exposed endpoints — none problematic
No endpoints dump `os.environ` or stack traces. `/health` and `/version`
expose only app name/version/env, and `narai` gates `/docs` behind
`NARAI_ENV=dev`.
