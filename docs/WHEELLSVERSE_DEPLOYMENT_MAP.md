# WHEELLSVERSE — Deployment Map (verified Phase-0)

Where each system actually runs, how it ships, and the env-var **NAMES** it needs.
No secret VALUES appear here (directive §30) — names only.

## Runtime targets

| System | Repo | Host / target | Pipeline | State |
|---|---|---|---|---|
| **App A — core.api** | wheellsverse-bots (this) | Railway `grateful-flexibility` / `wheellsverse-v2` → **app.wheellsverse.com** | GH Action `docker-push.yml` builds image → ghcr.io on push to `main`; Railway deploys image | **LIVE** (prod SHA was `4bbf5b95`; capability deploy `f067da31`) |
| **App B — KAI brain** | wheellsverse-bots `backend/app` | none (local/Docker) | — | **LOCAL-ONLY**, Docker down; never deployed |
| **Apex proxy** | wheellsverse-bots `frontend/` | Cloudflare Pages → wheellsverse.com | Pages build; `functions/_middleware.js` proxies `/admin`+`/api/*` → Railway App A | **LIVE** |
| **SOL API** | **wheellsverse-sol** (separate) | Railway `wheellsverse-sol` / `sol-api` → sol-api-production.up.railway.app | `railway up` (auto-deploy webhook BROKEN — deploy manually) | **LIVE**, money mode **MOCK** (`APP_ENV=staging`) |
| **SOL worker/scheduler** | wheellsverse-sol | Railway `sol-worker`, `sol-scheduler` | `railway up` | **LIVE** (RQ/Redis) |
| **Nurtelle** | **chenara** (separate) | none yet | Next.js build | **PRE-DEPLOY**, local |

## The deploy-gate reality (why "production unchanged" happened)
App A's image ships **only from `main`** via `docker-push.yml`. `feat/kai-capability-fabric` is a stacked
branch **ahead 79 / behind 39** of `main`; deploying it wholesale would regress 39 commits. The current
`/admin` route was repointed by commit **d52a975** (index.html → dashboard/ceo.html) — a one-line change
that shipped to `main`, not a deletion. **Recovery path = a small, forward `main` change** (re-point +
registry-driven Universe), never a wholesale branch deploy.

## Env-var NAMES by system (names only — values live in Railway/Cloudflare, never here)
- **App A:** `API_KEY` (rotated), `DATABASE_URL`, `REDIS_URL`, `KAI_CAPABILITY_FABRIC_ENABLED` (set),
  `KAI_PRESENCE_ENABLED`, Shopify/Toodle/SiteBoost/LeadGen service keys.
- **App B (KAI):** `DATABASE_URL`, `REDIS_URL`, `OLLAMA_*`, LLM provider keys, bridge/session secrets.
- **SOL:** `APP_ENV` (=staging), `PROVIDER_MODE` (=mock), `DATABASE_URL`, `REDIS_URL`, provider
  (Dwolla) credentials — **MOCK**, no real money movement in prod today.
- **Cloudflare Pages:** origin URL for the `_middleware.js` proxy.

## What is NOT deployed (honest gaps — never show these green)
- App B / KAI server runtime (all capabilities are **CATALOG_ONLY** on the server lane).
- Every external capability (MCP servers, coding CLIs, security/knowledge packs) — none installed on any
  deployed host; Claude-local only.
- Nurtelle — no environment yet.
- No isolated Railway **staging** for App A — a known human-only blocker for the certification gate.

## Deploy safety rules (unchanged by this reconstruction)
Rollback target for App A = prior deployment `b41ce1cb`. Never `reset --hard` / force-push / rewrite
history. Production changes stay operator-gated. Sol money invariants (append-only balanced ledger,
settlement-on-webhook, reconciliation holds) are never bypassed by any Command Center control.
