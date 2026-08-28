# App B (KAI governance runtime) — Isolated Staging Provisioning Runbook
### Modeled on the wheellsverse-sol staging pattern · DRAFT for operator approval · 2026-08-28

> **Nothing here has been executed.** Every `railway` command that creates or
> deploys resources is **billable** and is flagged **💲**. Run them only after you
> approve this plan. Production (`grateful-flexibility/production`) is never touched.

---

## 0. Why App B needs its own build config

The repo's root `railway.json` deploys **App A** (`uvicorn core.api:app`, health `/api/health`).
App B (`uvicorn app.main:app` from `backend/`) had no deploy config. Added in this pass:
**`backend/railway.json`** (App B API: `alembic upgrade head && uvicorn app.main:app`, health `/health`).
Per SOL gotcha #1, config-as-code overrides dashboard settings and applies to every
service built from `backend/` — so the **Celery worker** cannot simply override the start
command in the UI; it is deployed from a **temp copy** whose `railway.json` runs celery and
strips the healthcheck (SOL's proven method, §4 below). App A is unaffected (still builds from root).

## 1. Target topology (SOL-style, all names `*-staging`, never prod names)

| Resource | Name | Purpose |
|---|---|---|
| Project | `kai-staging` | isolated, separate from `grateful-flexibility` |
| Environment | `staging` | the only env in the project |
| Postgres plugin | `kai-staging-db` 💲 | dedicated — **not** prod Supabase/PG |
| Redis plugin | `kai-staging-redis` 💲 | dedicated — Celery broker + result backend |
| Service: App B API | `kai-staging` 💲 | `backend/railway.json`, rootDirectory=`backend`, public hostname |
| Service: worker | `kai-worker-staging` 💲 | celery worker, temp-copy config (no healthcheck) |
| Service: App A bridge | `kai-appA-staging` 💲 | **recommended** — so the App A↔B bridge is real & isolated (see §6) |

Self-heal scheduler is an **in-process thread** (`self_heal_scheduler.start()` → `_thread.start()`),
so **no separate scheduler service** is required — it runs inside the API service.

## 2. Environment variables (NAMES ONLY — never paste values in chat/docs/logs)

Set on the **App B API** + **worker** services (values via `railway variables --set` or dashboard):

| Var | Source / value class | Notes |
|---|---|---|
| `DATABASE_URL` | Railway reference `${{kai-staging-db.DATABASE_URL}}` | only strictly-required field |
| `REDIS_URL` | `${{kai-staging-redis.REDIS_URL}}` | |
| `CELERY_BROKER_URL` | `${{kai-staging-redis.REDIS_URL}}` | worker |
| `CELERY_RESULT_BACKEND` | `${{kai-staging-redis.REDIS_URL}}` | worker |
| `SESSION_SIGNING_SECRET` | **new staging secret** (shared App A↔B) | `openssl rand -hex 32`; same value on both App A-staging + App B-staging |
| `OPERATOR_SESSION_ENABLED` | `1` | unified `wv_session` gate |
| `JWT_SECRET_KEY` | new staging secret | App B auth |
| **`OPENAI_API_KEY`** | **operator-supplied, staging-scoped** | Journey B tool-capable brain; **you set this**, I never see it |
| `KAI_LLM_ALLOW_LOCAL_ONLY` | *unset* (staging uses OpenAI) | leave unset so the tool-capable path is live |
| `STRIPE_*`, `SUPABASE_SECRET_KEY` | omit / test-safe | optional; App B boots without them |

App A-staging (bridge origin) also gets: `KAI_BRIDGE_ENABLED=1`, `KAI_UPSTREAM_URL=<App B staging internal URL>`,
`SESSION_SIGNING_SECRET` (same as App B), `OPERATOR_SESSION_ENABLED=1`.

**Token/secret policy (operator standing):** never paste any secret or minted JWT into chat, logs, docs, or fixtures. Mint→use→discard inside one shell.

## 3. Provisioning commands (in order) — 💲 = billable

```bash
# --- create isolated project + env (does NOT touch grateful-flexibility) ---
railway init --name kai-staging                      # 💲 creates project
# (Railway makes a 'production' env by default; rename/keep one env named 'staging')

# --- data plugins (dedicated, isolated) ---
railway add --database postgres                       # 💲 kai-staging-db
railway add --database redis                          # 💲 kai-staging-redis

# --- App B API service ---
railway add --service kai-staging                     # 💲
railway service kai-staging
#   set rootDirectory=backend so backend/railway.json is used (dashboard: Service → Settings → Root Directory = backend)
railway variables --set DATABASE_URL='${{kai-staging-db.DATABASE_URL}}' \
                  --set REDIS_URL='${{kai-staging-redis.REDIS_URL}}' \
                  --set SESSION_SIGNING_SECRET='<staging-secret>' \
                  --set OPERATOR_SESSION_ENABLED=1 \
                  --set JWT_SECRET_KEY='<staging-secret>'
#   >>> YOU set OPENAI_API_KEY here (staging key), I do not handle its value <<<
railway up --service kai-staging                      # 💲 deploy (snapshot; clean tree = provenance)
railway domain --port 8080 </dev/null                 # public hostname (--port + </dev/null avoids the hang, SOL gotcha #2)
```

> **⚠ Classifier note:** this session blocks `railway variables --set` and `railway logs`.
> So either **you** run the `variables --set` lines / set them in the dashboard, or you enable
> those commands for me. I *can* run `railway init/add/up/status/domain`.

## 4. Worker service (temp-copy, healthcheck stripped — SOL gotcha #1)

```bash
# build a temp copy of backend/ whose railway.json runs celery and has NO healthcheck
# (worker serves no HTTP; a healthcheck would fail it forever)
tmp=$(mktemp -d); cp -R backend/* "$tmp"/
cat > "$tmp/railway.json" <<'JSON'
{ "$schema":"https://railway.app/railway.schema.json",
  "build":{"builder":"NIXPACKS"},
  "deploy":{"startCommand":"celery -A app.workers.celery_app worker --loglevel=INFO",
            "restartPolicyType":"ON_FAILURE","restartPolicyMaxRetries":3} }
JSON
railway add --service kai-worker-staging              # 💲
railway service kai-worker-staging
# same DATABASE_URL/REDIS_URL/CELERY_* vars as API
( cd "$tmp" && railway up --service kai-worker-staging )   # 💲
rm -rf "$tmp"
```
(We run the worker only; Celery **beat** is not started — its beat_schedule is prediction/market
tasks unrelated to the KAI governance journeys. Journey C needs the worker, not beat.)

## 5. Migration certification on the real staging DB (Section 3)

Already proven **canonical & repeatable from empty** locally (0→18 tables, head `0006`, no create_all/stamp).
On staging it runs automatically via the API startCommand (`alembic upgrade head && uvicorn …`), or run once explicitly:
```bash
railway run --service kai-staging alembic upgrade head   # against kai-staging-db
```

## 6. App A ↔ App B bridge (Section 6) — recommended: isolated App A staging

To prove the governed path **without touching prod App A**, deploy a small App A staging service
in the same project and point its bridge at App B staging:
```bash
railway add --service kai-appA-staging                # 💲 builds from repo root (App A's railway.json)
railway service kai-appA-staging
# vars: SESSION_SIGNING_SECRET (same as App B), OPERATOR_SESSION_ENABLED=1,
#       KAI_BRIDGE_ENABLED=1, KAI_UPSTREAM_URL=http://kai-staging.railway.internal:8000
railway up --service kai-appA-staging                 # 💲
```
App A staging must **never** fall back to prod/local App B or mock success — the allowlist + fail-closed
404 + 504-on-timeout in `core/kai_bridge.py` enforce this; verified in the journeys.

*(Alternative, cheaper: run App A locally pointed at App B staging's public hostname. Less isolated;
only the App B side is then truly "staging." I recommend the isolated App A service above.)*

## 7. Post-provision verification → resumes the Pass-5 loop

Once the three services are up + `OPENAI_API_KEY` set:
HEALTH (`/health`, DB, Redis, migration head, registry) → BRIDGE (auth/role/correlation/allowlist/CORS/streaming/error-map)
→ Journey B (real OpenAI tool exec + audit+usage rows) → C (worker retry) → D (incident ack) → E (automation run)
→ AUTH matrix (OWNER/ADMIN/OPERATOR/READ_ONLY, server-side enforcement) → AUDIT durability (incl. Pass-4 failure-rollback invariant)
→ hosted STREAMING → RESTART → ROLLBACK/redeploy → SECURITY (SSRF/traversal/RBAC/IDOR/secret-leak/x-env)
→ Playwright A–H → supersede `WHEELLSVERSE_STAGING_CERTIFICATION_2026-08-28.md` with a full PASS/FAIL matrix.

## 8. Estimated cost & teardown

New billable resources: 1 project, 2 DB plugins (Postgres+Redis), 2–3 services. On Railway's usage
model this is roughly a few $/day while running; **teardown** = `railway down` per service + delete the
project when the pass completes. Staging is meant to be ephemeral — spin up, certify, tear down.

---

### Approval needed before I run anything billable
1. **Go / no-go** on creating the `kai-staging` project + Postgres + Redis + 2–3 services (💲).
2. **App A bridge choice**: isolated `kai-appA-staging` service (recommended) vs local App A → App B staging.
3. **`railway variables --set`**: you set the secrets + `OPENAI_API_KEY` yourself, or enable that command for me.
