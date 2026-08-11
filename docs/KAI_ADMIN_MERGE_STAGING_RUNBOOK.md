# KAI ⇄ Admin Merge — Staging Runbook (flag cutover)

> All merge code is committed on `feat/kai-admin-merge` behind default-OFF flags.
> This runbook enables it **in staging only, one flag at a time**. Never combine
> cutovers. Production stays OFF until each staged step passes its success gate
> and the operator explicitly approves. Nothing here has been deployed.

## ⛔ EXTERNAL BLOCKER — no isolated staging exists (S0 finding)

Verified 2026-08-11: there is **no isolated staging deployment** for either app.
`railway.json`/`nixpacks`/`Dockerfile` start `core.api:app`; `frontend/functions/_middleware.js`
proxies to `grateful-flexibility-production.up.railway.app` — **production**. App B
runs at kai.wheellsverse.com — **production**. Running these gates against those
would touch production, which is forbidden.

**As the credential-free substitute**, the spine is certified LOCALLY against the
**real** app objects (`tests/test_staging_surrogate.py`: boots `core.api:app` +
`app.main:app` in-process with stub env, all flags ON). That covers Gate 1 fully
and Gate 2's security logic; it does NOT cover real DB routes, real LLM streaming,
HTTPS `Secure`-cookie behavior, or Cloudflare topology.

**Operator must provision to run the real gates:**
1. An **isolated staging deployment of App A** (`core.api:app`) — separate Railway
   service (or equivalent), non-prod DB, its own domain, `APP_ENV≠production`
   only if you want non-Secure cookies (prefer HTTPS + Secure).
2. An **isolated staging deployment of App B** (`app.main:app`) — separate service,
   non-prod Postgres + Redis, staging LLM/provider keys.
3. A shared **`SESSION_SIGNING_SECRET`** (staging-only, high-entropy) on both.
4. Staging `API_KEY` (A) and `ADMIN_TOKEN` (A+B); staging Cloudflare/proxy route
   (or direct staging URLs) so the browser reaches both same-origin.
5. Confirmation that neither URL is production.

Provide the two staging URLs + confirm the secrets are present (do not send their
values) and the staging gates below can run.

## Prerequisites (both apps, staging)

Set on **both** App A (`core.api:app`) and App B (`backend/app/main.py`) so a
cookie minted by one validates in the other:

| Env var | App | Notes |
|---|---|---|
| `SESSION_SIGNING_SECRET` | A + B | **Identical** high-entropy value. Rotating it invalidates all sessions. |
| `API_KEY` | A | existing owner key (owner-role login) |
| `ADMIN_TOKEN` | A + B | existing operator token (operator-role login) |
| `APP_ENV` | A + B | must NOT be dev/local/test in staging → cookies get `Secure` |

Baseline before any flag: `curl -s $A/admin/ui-config` →
`{operator_session_enabled:false, kai_bridge_enabled:false, kai_command_bar_governed:false}`.

---

## Flag 1 — `OPERATOR_SESSION_ENABLED`

Unifies identity and (as a side effect) closes the C1 `?api_key=` vector.

- **Pre-check:** legacy auth works — `curl -H "X-API-Key: $API_KEY" $A/api/overview` → 200; `curl $A/admin/session/whoami` → 404 (routes absent while off).
- **Enable:** set `OPERATOR_SESSION_ENABLED=true` on **A and B**; redeploy both.
- **Smoke:**
  1. `POST $A/admin/session/login {"secret":"$API_KEY"}` → 200, `Set-Cookie: wv_session` (HttpOnly, Secure, SameSite=Lax) + `wv_session_active=1`.
  2. `GET $A/admin/session/whoami` with the cookie → `{role:"owner", scopes:[…"kai.ultra"…]}`.
  3. Operator login (`ADMIN_TOKEN`) → `role:"operator"`, **no** `kai.ultra`.
  4. Cookie authorizes App A `/api/*` and App B admin routes (X-Admin-Token no longer required).
  5. **C1 check:** `GET $A/api/overview?api_key=$API_KEY` with **no** header/cookie → **401** (query param now rejected). Same call with `X-API-Key` header → 200.
  6. Legacy dashboard agent stream still works (uses the cookie via `wv_session_active`).
- **Rollback:** set `OPERATOR_SESSION_ENABLED=false` on both; redeploy. Query-param `?api_key=` is accepted again; session routes disappear. No data migration to undo.
- **Success:** owner+operator sessions work in both apps; `?api_key=` rejected; legacy header path intact; no 5xx in logs.

## Flag 2 — (folded into Flag 1) `?api_key=` closure

No separate flag. The adaptive EventSource + `resolve_api_key` gating mean enabling
Flag 1 **is** the query-secret removal. Verify smoke step 5 above. The hard deletion
of the two `query_params.get("api_key")` sites can follow later once Flag 1 is
permanent in prod (it is already unreachable while sessions are on).

## Flag 3 — `KAI_BRIDGE_ENABLED` (+ `KAI_UPSTREAM_URL`)

Same-origin App A → App B (governed brain). Requires Flag 1 on.

- **Pre-check:** `GET $A/admin/kai-bridge/health` → `{enabled:false,…}`; `GET $A/admin/kai/kai-chat` (with cookie) → 404 (fails closed).
- **Enable:** set `KAI_UPSTREAM_URL=https://<staging App B origin>` and `KAI_BRIDGE_ENABLED=true` on **App A**; redeploy A.
- **Smoke:**
  1. `health` → `enabled:true`.
  2. Owner cookie → `GET $A/admin/kai/kg` → 200 proxied from App B; response carries `X-Correlation-Id`.
  3. Operator cookie → `/admin/kai/kai-chat` 200; `/admin/kai/kai-chat/ultra` → **403** (owner-only).
  4. Anonymous → 401. Non-allowlisted path (`/admin/kai/secret`) → 404. `..` traversal → 404.
  5. SSE endpoint streams incrementally (not buffered).
  6. Audit log shows one `kai.bridge` event per call, **no secrets**.
- **Rollback:** `KAI_BRIDGE_ENABLED=false` on A; redeploy. All `/admin/kai/*` → 404.
- **Success:** governed routes reachable same-origin under RBAC; ultra owner-only; SSRF guards hold; audit clean.

## Flag 4 — `KAI_COMMAND_BAR_GOVERNED`

Points the CEO command bar at the governed brain. Requires Flags 1 & 3 on.

- **Pre-check:** `ui-config.kai_command_bar_governed=false`; command bar posts to `/api/narai/command` (App A NarAI).
- **Enable:** set `KAI_COMMAND_BAR_GOVERNED=true` on **App A**; redeploy A.
- **Smoke:**
  1. `ui-config` → `true`.
  2. Owner in ceo.html: type a command → response comes from the governed brain via `/admin/kai/kai-chat`; DevTools shows **no** `?api_key=` and **no** secret in the request; the request carries the `context` envelope (route/module only).
  3. Operator: an ultra-only instruction is refused with 403 (scope), not silently escalated.
  4. Audit event emitted per command.
- **Rollback:** `KAI_COMMAND_BAR_GOVERNED=false` on A; redeploy → back to NarAI. The old route was never removed.
- **Success:** governed responses, context attached server-side, RBAC enforced, audit present, no secret in any URL.

## Production

Only after all four pass in staging AND operator sign-off. Enable the same flags in
the same order in production, one at a time, watching `kai.bridge` audit + error
rates between each. Each flag's rollback is a single env flip + redeploy.
