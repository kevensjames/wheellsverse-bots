# KAI ⇄ Admin Merge — Identity-First Bridge Plan (P1 → P3, P6)

> 2026-08-11. Chosen path: **bridge-first (identity)**. This is the wiring plan
> for the pieces that touch production auth/infra. Everything here is **additive
> and flag-gated** — the existing X-API-Key / X-Admin-Token paths keep working
> until a replacement is verified in staging (§33: never delete before verified).
> **Nothing in this plan is deployed.** The reusable identity core it wires in
> (`core/operator_session.py`) already exists and is covered by 20 passing unit
> tests (`tests/test_operator_session.py`).

## What already exists on this branch (build on it, don't re-do it)

| Piece | Where | Status |
|---|---|---|
| C1 HTML key-injection removed | `core/api.py` (0× `%%API_KEY%%`) | ✅ done (d52a975) |
| KAI CEO Command Center (3D shell) | `dashboard/ceo.html`, served at `/admin` (`core/api.py:1641`) | ✅ the merge shell — three.js KAI Core + "KAI COMMAND" bar |
| Apex→backend same-origin proxy | `frontend/functions/_middleware.js` | ✅ apex `/admin`+`/api/*` → Railway App A |
| `?key=` bootstrap hardened | `ceo.html:256` (no-referrer + immediate strip) | ✅ done |
| Unified operator identity core | `core/operator_session.py` | ✅ built + tested (this change) |

## The two gaps this plan closes

1. **Identity is still binary shared-secret.** App A = owner `X-API-Key`
   (`core/api.py:186` `verify_api_key`, `:855` `api_key_middleware`); App B =
   operator `X-Admin-Token` (`backend/app/dependencies/admin.py:10`
   `require_admin_token`, plain `!=`, not constant-time). No roles, no scopes.
2. **Two brains, still unbridged.** `ceo.html`'s command bar posts to
   `/api/narai/command` (App A NarAI); the *governed* brain (KG/twin/persona/
   memory/`@audited`) is App B `/admin/kai-chat` + `/kai/chat` on a **separate
   deploy** (`backend/app/main.py`, kai.wheellsverse.com). `core/api.py` imports
   zero KAI routers. Apex→App A is proxied; **App A→App B is not**.

---

## P1 — finish C1 (the one residual)

`?api_key=` query-param acceptance is still live in `core/api.py:203` and `:873`.
Only **one** consumer remains: `dashboard/index.html:18053` (legacy dashboard,
now at `/admin/legacy`) —
`new EventSource('/api/agent/stream/${runId}?api_key=${_apiKey()}')`. `ceo.html`
already avoids it (`:436`).

- **Step 1:** migrate that `EventSource` to a header-authenticated stream (or a
  short-lived signed stream token minted by `operator_session.mint_session`-style
  signing) so the key never enters a URL / access log.
- **Step 2:** only then delete the two `or request.query_params.get("api_key")`
  clauses. Verify `tests/test_wmos_containment.py` stays green.
- **Do NOT** delete before Step 1 — it would break legacy agent streaming.

## P2 — unify identity (wire `core/operator_session.py` in, flag-gated)

New env flag `OPERATOR_SESSION_ENABLED` (default **off**). When off, behavior is
byte-identical to today.

**App A (`core/api.py`)**
- Add a resolver shim: from `x-api-key`/`x-admin-token` headers + the
  `wv_session` cookie, call `operator_session.resolve_principal(...)` with
  `owner_key=_API_KEY`, `admin_token=settings.admin_token`,
  `session_secret=<SESSION_SIGNING_SECRET>`. Stash `request.state.principal`.
- In `verify_api_key` / `api_key_middleware`: when the flag is on, accept **a
  valid session cookie OR the legacy key**; when off, unchanged. Keep the
  constant-time key compare that's already there.
- New routes (both flag-gated, no-store):
  - `POST /admin/session/login` — body carries the owner key or admin token;
    on match, `Set-Cookie: wv_session=<mint_session(role)>; HttpOnly; Secure;
    SameSite=Lax; Path=/`. Mints `owner` for the API key, `operator` for the
    admin token.
  - `POST /admin/session/logout` — clears the cookie.
  - `GET  /admin/session/whoami` — returns `{role, scopes, source}` so the
    orb/drawer/Nexus render the *same* identity everywhere.
- Enforce scope on sensitive App-A writes as they're migrated (SiteBoost send,
  W-MOS ARM/KILL): `require_scope(request.state.principal, SCOPE_HIGH_IMPACT)`
  etc. — do this incrementally, logged in the ledger, never silently.

**App B (`backend/app/dependencies/admin.py`)**
- Add `require_scope(scope)` dependencies backed by the same
  `operator_session.resolve_principal`, reading the same `wv_session` cookie +
  `SESSION_SIGNING_SECRET`. `require_admin_token` stays as the fallback while the
  flag is off. (Also upgrade its `!=` to `hmac.compare_digest` — free hardening.)

**Shared secret:** both apps must read the **same** `SESSION_SIGNING_SECRET`
(env). This is what lets one cookie authenticate across the bridge.

## P3 — bridge App A → App B (the KAI brain), same-origin

The apex proxy only reaches App A. To make `/kai/*` and `/admin/kai-chat`
same-origin from the admin shell (so the `wv_session` cookie flows to the
governed brain), pick one:

| Option | How | Trade-off | Rec |
|---|---|---|---|
| **A. Reverse-proxy path** | In `core/api.py`, add an `httpx` passthrough for `/kai/*` + `/admin/kai-chat*` → `backend/app` origin, forwarding the `wv_session` cookie. Mirror the apex `_middleware.js` pattern one layer down. | Keeps the two deploys independent; smallest blast radius; streaming (SSE) needs `httpx.stream`. | ✅ **start here** — least coupling, reversible, no import-graph merge of two 15k-line apps. |
| **B. Sub-app mount** | `core.api:app.mount("/kai-app", app.main:app)` — run App B in-process under App A. | One process, one cookie jar, no network hop; but merges dependencies, lifespans, schedulers of two big apps — high risk, hard to unwind. | later, only if A's latency proves unacceptable. |

Gate the whole bridge behind `KAI_BRIDGE_ENABLED` (default off). Until on, the
shell keeps using App A's NarAI.

## P6 — repoint the assistant to the governed brain (closes §12/§26)

- Change `ceo.html`'s command bar (and the future shared orb/drawer) from
  `POST /api/narai/command` to the governed `POST /admin/kai-chat` (via the P3
  bridge), carrying the `wv_session` cookie.
- **Escalation gate:** `/admin/kai-chat` mints a synthetic "ultra" operator that
  bypasses tier gates (`backend/app/routers/admin_chat.py:60-116`). Require
  `SCOPE_KAI_ULTRA` for that path — which, per `operator_session.ROLE_SCOPES`,
  **only `owner` holds**. An `operator`-role session reaching the bridge gets a
  normal, governed session, never the ultra bypass. This is the difference
  between the merge *closing* the escalation and *creating* one.
- Two-brains caveat: this is a behavior/cost/tool-access change, not a URL swap
  — cut over in staging with the NarAI path kept as fallback.

## Rollout order & verification

1. Land `operator_session.py` + tests (this change). ✔ 20/20 green.
2. P2 shim behind `OPERATOR_SESSION_ENABLED=off` → deploy inert → flip on in
   **staging** only → run `test_wmos_containment.py` + new session tests.
3. P1 EventSource migration → remove `?api_key=`.
4. P3 reverse-proxy behind `KAI_BRIDGE_ENABLED=off` → staging.
5. P6 repoint in staging with fallback.
6. Only after staging green: production, one flag at a time, each with a ledger
   row moved DISCOVERED→…→VERIFIED.

**No production deploy happens without explicit operator approval.**
