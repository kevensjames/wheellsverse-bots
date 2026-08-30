# Holding OS — isolated staging deploy + hosted cert (operator runbook)

Stands up an **isolated** App B staging service (own Postgres+Redis), flags ON, then certifies the
live Holding OS. Production is never touched. You run the deploy; I verify the cert output.

**Certified commit:** `bc3cc50` on `feature/kai-holding-operations-os`. Run from the repo root
(`/Users/jhonwheeler/wheellsverse-kai-merge`), branch checked out.

Prereqs: `railway login` done. The container auto-runs `alembic upgrade head` on boot (no manual migration).

## 1) Create an isolated staging project + service
```
railway init --name kai-staging                 # new, isolated project
railway add --database postgres                  # isolated Postgres
railway add --database redis                     # isolated Redis
railway add --service kai-staging-appb           # the App B service (from this repo)
```

## 2) Set env (flags ON, staging, fresh secret — the secret is never displayed)
```
railway variables --service kai-staging-appb \
  --set "APP_ENV=staging" \
  --set "RAILWAY_DOCKERFILE_PATH=backend/Dockerfile.staging" \
  --set "KAI_HOLDING_ENABLED=true" \
  --set "KAI_HOLDING_BRIEFING_ENABLED=true" \
  --set "OPERATOR_SESSION_ENABLED=true" \
  --set "OPENAI_API_KEY=sk-staging-unused" \
  --set "DATABASE_URL=\${{Postgres.DATABASE_URL}}" \
  --set "REDIS_URL=\${{Redis.REDIS_URL}}"

# fresh signing secret, generated + stored in Railway WITHOUT printing it:
railway variables --service kai-staging-appb --set "SESSION_SIGNING_SECRET=$(openssl rand -hex 32)"
```
Notes: Holding is read-only and never calls OpenAI, so `OPENAI_API_KEY` is a harmless placeholder here.
`KAI_HOLDING_BRIEFING_ENABLED=true` lets the daily Celery briefing persist KPI history; set `false` if
you only want the on-demand endpoint for now.

## 3) Deploy (snapshot) + get the URL
```
railway up --service kai-staging-appb --detach
railway domain --service kai-staging-appb --port 8000     # --port avoids the CLI hang; copy the https URL
```
Wait for the deploy to go healthy (Railway dashboard → Deployments). Confirm boot:
```
curl -s "https://<staging-url>/health"                     # expect {"status":"ok","env":"staging"}
```

## 4) Run the hosted cert (secret injected by Railway, never printed)
```
STAGING_URL="https://<staging-url>" \
  railway run --service kai-staging-appb python3 ops/holding-staging/hosted_cert.py
```
Expected: **HOSTED HOLDING STAGING CERT: 10/10 — PASS** (owner-only access; operator-role 403;
overview/entities/briefing 200; truth-grounding; ranked source-cited priorities; KPI snapshot;
movement; live-signal health). Paste me the output and I'll verify it.

## 5) Rollback / teardown (staging is disposable)
- Disable instantly: `railway variables --service kai-staging-appb --set "KAI_HOLDING_ENABLED=false"` (holding routes vanish).
- Full teardown: delete the `kai-staging` project in the Railway dashboard (removes service + Postgres + Redis).

## After staging PASS
That clears the go/no-go for a **dark prod** deploy (see `docs/KAI_HOLDING_DEPLOY_PLAN.md`): App B snapshot
with flags OFF → verify dark → flip `KAI_HOLDING_ENABLED=true`. I'll prepare those exact steps when you're ready.
