# Deployment topology — direct evidence

**Supersedes the earlier inference.** The previous disposition of the failing Workers job argued from
production uptime: *"it fails at the commit production was released from, and production is serving,
therefore it is irrelevant."* That reasoning is not sound — uptime alone cannot prove a failed job is
irrelevant, because a job can fail while a previously published artifact keeps serving. This document
replaces it with configuration, routes, deployment records and served artifacts.

Measured 2026-09-07 against the live production estate.

---

## 1. DNS and routing

All three hostnames resolve to the same Cloudflare anycast addresses (`172.67.194.236`,
`104.21.90.39`), so every one is Cloudflare-proxied. What differs is where Cloudflare sends them.

| Hostname | Terminates at | Evidence |
|---|---|---|
| `wheellsverse.com` (apex) | **Cloudflare Pages** | `server: cloudflare`, **no** `x-railway-*` header; `/api/health` returns the SPA **HTML**, not API JSON |
| `app.wheellsverse.com` | **Railway — App A** (`wheellsverse-v2`) | `x-railway-request-id`, `x-railway-edge: jfk1`; `/api/health` returns real API JSON with `git_sha 5e767a4` |
| `kai.wheellsverse.com` | **Railway — App B** (`kai-prod`) | `/health` returns `{"status":"ok","env":"production"}` |

## 2. Service responsibilities

**Railway App A — `wheellsverse-v2`** (project `grateful-flexibility`, `5407586d…`)
Serves `app.wheellsverse.com`: the admin surface, `/admin/holding`, the operator session, the
`/admin/kai/*` bridge to App B, and the `/api/*` platform API. Deployed by CLI upload
(`railway up`, NIXPACKS). Current deployment `c81a3b11-d096-4fa5-8c1c-53215ae2e568`,
image `sha256:41e671ec58e75212…`.

**Railway App B — `kai-prod`** (project `kai-production`, `896e8fbe…`)
Serves `kai.wheellsverse.com` and is reached privately by App A. Owns the holding API, the timeline
store, the deployment registry and the migrations. Built from `backend/Dockerfile.staging`
(`RAILWAY_DOCKERFILE_PATH`), whose `CMD` chains `alembic upgrade head && uvicorn`. Current deployment
`e6436cc1-1118-4ded-a11e-7678e2625cf1`, image `sha256:48c39277ca6eb7fc…`.

**Cloudflare Pages — project `wheellsverse-bots`**
Publishes the static apex site from `frontend/`. Its check **passes** on the production merge. This is
the check that actually deploys frontend content.

## 3. What `frontend/wrangler.jsonc` publishes

```jsonc
{ "name": "wheellsverse-bots", "compatibility_date": "2025-09-27",
  "assets": { "directory": "." } }
```

A **static-assets Worker with no `main` entry** — it declares no code, only that the `frontend/` tree
is an asset bundle. Note that `assets.directory: "."` means this PR *does* change what such a Worker
would publish, because the release changes 18 files under `frontend/`. That is why "the PR does not
touch its build inputs" is true but insufficient on its own.

## 4. Does the failing Workers job control any live hostname or artifact?

**No.** Four independent lines of evidence, none of which is uptime:

1. **No Worker route serves any production hostname.** The apex terminates at Pages (no Railway
   headers, serves static HTML). `app.` and `kai.` carry Railway edge headers, so Cloudflare proxies
   them straight to Railway. No response from any hostname carries a `cf-worker` header.
2. **The Worker has no reachable hostname of its own.** `wheellsverse-bots.workers.dev` and
   `wheellsverse-bots.kevensjames.workers.dev` both fail to resolve. A Worker that has never built
   successfully has never published a script to route to.
3. **The frontend is deployed by Pages, not Workers.** The Pages check passes on the same commit where
   the Workers check fails, and the apex serves Pages content.
4. **The build never executes.** `started_at == completed_at` to the second on the candidate,
   on `b0674ce` and on `4fbfb8e`. It fails at job creation, so it produces no artifact to publish.

**Residual honesty:** what I cannot inspect without Cloudflare dashboard or API credentials is the
Worker's *route bindings* and its build log. The evidence above is external and behavioural. If a route
binding existed but the Worker had never published, requests matching it would fail rather than reach
Railway — and they demonstrably reach Railway. That is the strongest statement available from outside.

## 5. Which CI checks are release-blocking, and why

**None are enforced.** `GET /repos/kevensjames/wheellsverse-bots/branches/production` returns
`protected: false`, and the protection endpoint returns `404 Branch not protected`. There are **no
required status checks** on `production`.

This is itself a finding. The merge of PR #69 succeeded while `Workers Builds` was failing, not because
that check was judged irrelevant by any configured policy, but because **no policy exists**. The
practical gate today is human approval, not CI.

| Check | Result at the merge | Actually blocking? | Should it be? |
|---|---|---|---|
| `Cloudflare Pages` | pass | no | **yes** — it deploys the apex |
| `ingest` | pass | no | yes |
| `Cursor Security Agent` | pass | no | worth considering |
| `Cursor Approval Agent` | pass | no | policy decision |
| `Workers Builds: wheellsverse-bots` | **failure** | no | **no** — it publishes nothing |
| `Aikido Security` | skipping | no | yes, once it runs |
| `Cursor Bugbot` | skipping/neutral | no | optional |

**Recommendation, not applied here:** either delete the unused `frontend/wrangler.jsonc` Worker
project so the failing check disappears honestly, or fix it and bind it to nothing. Then enable branch
protection on `production` with `Cloudflare Pages` and `ingest` required. Both are operator decisions
about repository configuration and are outside this hotfix's scope.

## 6. One correction to an earlier claim

`frontend/functions/_middleware.js` exists in the repository and proxies apex `/api/*` and `/admin` to
`grateful-flexibility-production.up.railway.app`. **It is not active on the live apex**: apex
`/api/health` returns SPA HTML rather than the API's JSON. Either the Pages project does not have
Functions enabled, or the deployment predates the file. Earlier notes describing the apex proxy as
working should be read as describing the repository, not the running site.
