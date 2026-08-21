# KAI ⇄ Admin Merge — Hosted-Edge Certification + Production Runbook

> The merge is **local-certified** end-to-end (identity, bridge, Gate-3 streaming,
> global presence, Nexus avatar/voice) with every flag default-OFF. This document
> is the remaining gate to **production**: what must be proven over the real
> HTTPS + Cloudflare edge (things a localhost stack cannot show), and the exact
> one-flag-at-a-time cutover. **Nothing here is executed by me** — it needs the
> operator's production infrastructure, secrets, and go-ahead.

## The topology this must respect

Two separate production deployments (not one app):

- **App A** = `core.api:app` → **app.wheellsverse.com** (Railway `grateful-flexibility`).
  Serves the admin shell, the presence assets, the `/admin/kai/*` bridge, and
  `/admin/session/*`.
- **App B** = `backend/app/main.py` → **kai.wheellsverse.com** (separate deploy).
  The governed KAI brain (`/admin/kai-chat`, `/admin/kai-chat/stream`, KG, …).
- **Cloudflare apex** proxy (`frontend/functions/_middleware.js`) forwards
  `wheellsverse.com/admin` + `/api/*` to App A so the apex is same-origin.

The browser only ever talks to **one origin** (App A / the apex). App A's bridge
reaches App B **server-side**, forwarding the `wv_session` cookie. So the edge
path for a governed chat is:

```
browser ──HTTPS──▶ Cloudflare apex ──▶ App A (bridge) ──HTTP──▶ App B ──▶ provider
        ◀────────────────── SSE stream ──────────────────────────────────┘
```

Every edge risk below lives on that path.

## Prerequisites (operator, before any flag)

1. **Deploy the merge code** to both App A and App B production (merge
   `feat/kai-admin-merge` → the production branch; see "Branch consolidation").
2. **Shared `SESSION_SIGNING_SECRET`** — one high-entropy value set on BOTH App A
   and App B (env). Different values = cross-app auth silently fails.
3. **App B provider** — real cloud LLM keys (prod does NOT use ollama;
   `KAI_LLM_ALLOW_LOCAL_ONLY` stays UNSET in prod, so `REQUIRED_ADAPTERS={openai}`
   holds). Set `OPENAI_API_KEY` (+ any others).
4. **Operator profile** — `KAI_OPERATOR_USER_ID` on App B = a real Supabase
   `profiles.id` with `tier='ultra'` (prod already has the Supabase-managed
   `profiles`/`auth.users`, so no schema bootstrap is needed — that was a
   local-only step).
5. **`DEBUG=false`** on App B (the safe default now, but set it explicitly).
6. Keep all four cutover flags **OFF** initially:
   `OPERATOR_SESSION_ENABLED`, `KAI_BRIDGE_ENABLED`, `KAI_COMMAND_BAR_GOVERNED`
   (and don't set `KAI_UPSTREAM_URL` yet). Presence assets are served but inert
   (the orb shows OFFLINE / "not enabled"), so shipping the code dark is safe.

---

## HOSTED_EDGE_CERTIFICATION (blocks production only)

Run these against **staging over the same HTTPS + Cloudflare edge as prod** (a
staging CF hostname in front of staging App A + App B), with the flags ON there.
Each is something localhost could not prove.

| # | Edge check | How to prove | PASS criteria |
|---|---|---|---|
| E1 | **Secure cookie over HTTPS** | Log in via `POST /admin/session/login`; inspect `Set-Cookie` | `wv_session` is `HttpOnly; Secure; SameSite=Lax; Path=/`; the browser sends it on same-origin `/admin/*` requests; `wv_session_active` (non-secret hint) present |
| E2 | **Cookie flows through the apex proxy** | With sessions ON, load `wheellsverse.com/admin` and call `/admin/session/whoami` | returns `owner` — the CF Pages Function preserves cookies both ways |
| E3 | **SSE survives the edge (no buffering)** | Owner sends a long governed prompt; watch the network stream | tokens arrive **incrementally over time** (not one buffered blob). If Cloudflare buffers: set the response to bypass CF buffering (Cache Rule / `cache: bypass`, honor `X-Accel-Buffering: no`, ensure `text/event-stream` isn't cached). **This is the single highest edge risk.** |
| E4 | **SSE through the Pages Function** | Same, but via the apex proxy (`wheellsverse.com/admin/kai/kai-chat/stream`) | the Pages Function streams the body (it returns `new Response(resp.body, resp)` — verify it doesn't await/buffer); tokens still incremental |
| E5 | **Disconnect propagation** | Start a long stream, close the tab/abort | App A logs the bridge stream closing; App B logs `kai.stream.cancelled`; provider stops. Confirm the edge forwards the client close (CF should drop the upstream on client disconnect) |
| E6 | **Header filtering / no secret leak** | Inspect responses through the edge | `X-Correlation-Id` present; no `Set-Cookie` for `wv_session` leaks off App A's origin; no upstream/provider headers, no `X-Admin-Token`, no `X-API-Key` echoed; hop-by-hop stripped |
| E7 | **C1 through the edge** | `GET wheellsverse.com/api/<gated>?api_key=<key>` with sessions ON | **401** (query secret rejected); header/cookie auth still 200 — closed end-to-end, no `?api_key=` in any CF/access log |
| E8 | **No CORS surprise** | All calls are same-origin (apex/App A) | no CORS preflights on `/admin/kai/*`; if any cross-origin slips in, it is denied |
| E9 | **Cookie domain/path** | Verify scope | `wv_session` scoped to App A's host/`Path=/`; App B never receives it from the browser directly (only via the bridge server-side) — so kai.wheellsverse.com needs no cookie of its own |
| E10 | **RBAC + redaction hold at the edge** | operator session → `/admin/kai/kai-chat*` | **403** (owner-only); a forced provider error returns a redacted message, no traceback (DEBUG=false) |

**Gate:** all E1–E10 PASS → `HOSTED_EDGE_CERTIFIED`. E3/E4 (SSE non-buffering
through Cloudflare) is the likeliest to need a CF config change — budget for it.

### Driven now (code-level, without prod) — 2026-08-21
What can be certified/hardened without a live edge has been:

- **E4 (Pages-Function streaming) — code-audited + hardened.**
  `frontend/functions/_middleware.js` passes the upstream `ReadableStream` through
  with `return new Response(resp.body, resp)` (streams; does NOT `await
  .text()/.json()`), and now sets `duplex: "half"` when forwarding a streamed
  request body (Streams-spec requirement; CF supports it). It propagates the
  bridge/App-B response headers (`Cache-Control: no-cache`, `X-Accel-Buffering:
  no`). So the **Worker layer streams SSE**; what remains is **E3** — Cloudflare's
  CDN must not buffer/compress `text/event-stream` (a CF Cache-Rule / no-compress
  setting), which only the real edge can confirm.
- **E7 (C1) + E10 (RBAC + redaction) — already certified against the REAL apps**
  in-process (surrogate + live-gate): `?api_key=` rejected when sessions on;
  operator→403 on the ultra path; `DEBUG=false` redacts. The edge run just
  re-confirms them over HTTPS.
- **E1 (cookie attributes) — verified in code + local HTTP:** `wv_session` is
  `HttpOnly; Secure; SameSite=Lax; Path=/`. The only edge-specific unknown is the
  real-HTTPS round-trip (Secure cookies aren't sent over the local http surrogate).
- **Security scan (Aikido):** the reverse-proxy bridge and the admin auth
  dependency scan **clean** (SAST + secrets) via the Aikido MCP. To pull the
  Aikido *platform* issue feed for the repo, enable it at
  `app.aikido.dev/settings/integrations/ide/mcp/permissions` (workspace setting).

**Still strictly operator-blocked (need staging behind the real Cloudflare edge):**
E2, E3, E5, E6, E8, E9 and the HTTPS confirmations of E1/E7/E10.

---

## Production cutover — one flag at a time

Each flag is a Railway env change + redeploy of the named app. **Never combine.**
Watch `kai.bridge` / `kai.stream` audit + error rates between steps. Every rollback
is a single env flip + redeploy (seconds).

### Flag 1 — `OPERATOR_SESSION_ENABLED=true` (App A + App B)
- **Pre-check:** legacy `X-API-Key` / `X-Admin-Token` work; `/admin/session/whoami` → 404 (routes absent).
- **Enable:** set on **both** apps (shared secret already present); redeploy both.
- **Smoke (over HTTPS):** owner + operator login (E1), whoami roles + scopes, cross-app whoami (E2), attack cookies fail closed, **C1** `?api_key=` now 401 (E7), legacy header still works.
- **Rollback:** unset on both; redeploy. `?api_key=` accepted again; no data to undo.
- **Success:** sessions work on both apps; C1 closed; no 5xx.

### Flag 2 — (folds into Flag 1) C1 query-secret closure
No separate flag — enabling Flag 1 rejects `?api_key=`. Verify E7. (Optional later:
delete the two `query_params.get("api_key")` reads once Flag 1 is permanent.)

### Flag 3 — `KAI_BRIDGE_ENABLED=true` + `KAI_UPSTREAM_URL` (App A only)
- **Pre-check:** `GET /admin/kai-bridge/health` → `{enabled:false}`; `/admin/kai/*` → 404 (fail-closed).
- **Enable:** set `KAI_UPSTREAM_URL=https://kai.wheellsverse.com`, `KAI_BRIDGE_ENABLED=true` on App A; redeploy A.
- **Smoke:** health `enabled:true`; owner `/admin/kai/kg` reaches App B; operator `/admin/kai/kai-chat` → **403**; anonymous → 401; traversal/allowlist → 404; **SSE streams incrementally through the edge (E3/E4)**; **disconnect cancels (E5)**; audit clean, no secrets (E6).
- **Rollback:** `KAI_BRIDGE_ENABLED=false` on A; redeploy → all `/admin/kai/*` → 404. The presence orb degrades to "not enabled"; no user-facing break.
- **Success:** governed routes reachable same-origin under RBAC; streaming + cancellation certified at the edge.

### Flag 4 — `KAI_COMMAND_BAR_GOVERNED=true` (App A only)
- **Pre-check:** `/admin/ui-config.kai_command_bar_governed=false`; ceo.html command bar uses NarAI.
- **Enable:** set on App A; redeploy A.
- **Smoke:** ceo.html command bar streams from the governed brain (tokens in the log, KAI Core state moves); the admin **presence orb goes ONLINE for owner**, the drawer + suggestions stream, the **Nexus** at `/admin/nexus` shows the living avatar + speaks; operator is denied the governed path (403); audit per action.
- **Rollback:** unset on A; redeploy → command bar back to NarAI; presence still works (it only needs Flags 1+3), so consider leaving the orb enabled and only reverting the ceo bar.
- **Success:** one governed KAI across the CEO bar, every admin page, the drawer, and the Nexus.

> Presence (orb/drawer/Nexus) needs **Flags 1 + 3** (session + bridge). It has no
> flag of its own — the assets are always served and degrade gracefully, so the
> orb "comes alive" the moment Flags 1+3 are on for an owner.

## Instant kill switch
Setting **any** flag back to OFF disables that layer immediately on the next
redeploy; setting all three OFF returns production to exactly today's behavior
(legacy NarAI, X-API-Key, no bridge). No migration, no data change is involved in
any rollback.

## Branch consolidation (do before prod deploy, human-sequenced)
`feat/kai-admin-merge` is based on `fix/wmos-critical-containment` (the only branch
with the C1 fix). Neither is on `main`. Before production: land the C1 containment
(with its stranded `tests/test_wmos_containment.py`, currently uncommitted on the
`istanbul` branch) and `feat/wmos-safety-kernel` (H1) to `main`, then rebase this
merge branch onto the updated `main`. Do not fold unrelated WIP into the merge.

## Post-cutover backlog (not blocking)
- Delete the now-unreachable `?api_key=` query reads once Flag 1 is permanent.
- Real viseme lip-sync + provider-side TTS (the Nexus avatar currently uses
  browser SpeechSynthesis + generic-motion speaking video — honest, not
  phoneme-accurate).
- Multi-worker session/rate-limit store (the operator-stream limiter is per-process
  — move to Redis if App A runs multiple workers with a shared limit).
