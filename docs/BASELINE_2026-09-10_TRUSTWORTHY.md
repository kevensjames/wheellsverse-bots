# TRUSTWORTHY BASELINE — 2026-09-10

The first baseline in this sequence taken against a **production-equivalent dependency set**. Every
earlier audit ran against a smaller application than production serves; this record exists to say so
precisely and to fix the point from which later claims are measured.

Earlier evidence is **superseded, not deleted**. §5 names exactly which claims are affected and how.

---

## 1. The baseline

| | |
|---|---|
| production SHA | `5ba51b01c5e9` |
| App A deployment | `16696e80` |
| App B deployment | `bb794e15` (unchanged; no `backend/` files in the diffs) |
| migration head | `0008_add_kai_devices` |
| test suite | **1234 passed / 0 failed / 0 collection errors** (was 44 + 5) |
| node suites | 23 / 23 |
| Phase 0 CI gate | **runs on `production`** since PR #80 (`e1e13d25`) |
| eight authority flags | 0 ON |
| `KAI_COMPUTER_OPS_ENABLED` | false |

### Holding tuple, read directly from the production database

`holding_proposals` **11** (executed 2 / proposed 9) · `holding_action_nonces` **0** ·
`holding_timeline` **15** · `holding_worker_jobs` **0** · `kai_devices` / `kai_device_pairings` /
`kai_device_nonces` **0 / 0 / 0** · `audit_log` 263 with **0** device, desktop or mission events.

## 2. What the dependency correction exposed

`core/api.py` mounts every NarAI v2 router inside `try/except`. A missing optional dependency does
not raise — it logs a warning and those routes **silently never exist**. The venv used for every
audit in this sequence lacked `chromadb`, `litellm`, `cachetools` and `aiosqlite`, all of which are
pinned in `requirements.txt`.

Consequence: roughly **120 production routes were invisible** to every guard, including:

- **33 mutating `/api/v2/narai` routes**, all of which carry `require_auth`. The `PublicRule` purpose
  *"NarAI v2 uses its own JWT auth on every route"* is therefore now **VERIFIED**, where it had been
  carried as an UNVERIFIED claim since PR #74.
- **A second WebSocket route, `/api/v2/narai/voice/ws`** — which authenticated with a long-lived JWT
  taken from a query parameter.

The five mutating v2 routes without `require_auth` are accounted for: `auth/login`, `insider/lead`
and `telegram/subscription/checkout` are entry points a caller cannot yet hold a credential for, and
`insider/reissue` and `insider/revoke` are guarded in-body by `_require_admin(x_admin_token)`.

## 3. WebSocket surface

Two routes, both gated, both now resolved through one module (`narai/api/ws_auth.py`):

| Route | Identity | Notes |
|---|---|---|
| `/api/code/stream/{run_id}` | owner session cookie + trusted Origin, or `X-API-Key` | gated by PR #77 |
| `/api/v2/narai/voice/ws` | owner/operator session cookie + trusted Origin, or a single-use ticket | JWT-in-URL removed |

Every WebSocket route bypasses `api_key_middleware` by construction — it is registered as
`@app.middleware("http")` and Starlette passes non-HTTP scopes straight through. Each route therefore
authenticates itself or not at all, which is why they now share one resolver rather than two.

## 4. Certified on isolated staging

`kai-appA-staging` in project `kai-staging`. **19 / 19**, including the positive handshakes that
production can never demonstrate:

```
anonymous                              REFUSED(403)
legacy ?token= long-lived JWT          REFUSED(403)
legacy ?token= WITH a valid ticket     REFUSED(403)
owner cookie + trusted Origin          ACCEPTED(101)
owner cookie + hostile / null / absent Origin   REFUSED(403)
viewer cookie + trusted Origin         REFUSED(403)
valid single-use ticket                ACCEPTED(101)
expired / wrong-route / wrong-env / foreign-secret / viewer-role / tampered / oversized ticket
                                       REFUSED(403)
ticket second use (replay)             REFUSED(403)
concurrent replay (8 parallel)         exactly 1 winner
```

No production data, no voice, no external provider, no consequential action.

## 5. Superseded evidence — precisely

Nothing below is deleted. These claims were correct about what their environment could see and
silent about what it could not, which is the most dangerous shape a security result can take.

| Claim | Where | Status |
|---|---|---|
| "the WebSocket surface is one route" | PR #77, and the pin in `test_websocket_auth_boundary.py` | **SUPERSEDED.** Two routes. The second only loads with `chromadb` + `litellm`. |
| "genuine `wss://` handshake to production → 403 from the gate" | PR #77 evidence, and my report of it | **SUPERSEDED AS EVIDENCE.** The edge returns **403 to every WebSocket upgrade, including paths that do not exist**, so a production WebSocket probe cannot distinguish gated from absent. PR #77's gate remains proven — **on staging**, where 403 vs 101 discriminates. |
| "387 mutating routes enumerated" | `test_public_action_routes.py` | **SUPERSEDED.** Enumerated against a reduced surface. |
| "`/api/v2/narai` in-handler guards sampled, not exhaustively verified" | PR #74 record, §11 | **RESOLVED.** Now exhaustively verified: 33 `require_auth`, 5 accounted. |
| "27 anonymous action paths contained" | PR #74, marker `PR74_27_…` | **STANDS.** Re-verified against the full surface; no additional anonymous action path found. |
| "four webhook trust boundaries contained" | PR #76, marker `PR76_…` | **STANDS**, with §6 correcting the restoration plan. |

## 6. Webhook plan — corrected

**Payhip stays `FAIL_CLOSED_UNAVAILABLE`.** It is not a provisioning gap and should not be treated as
one. Payhip's documented `signature` is `sha256(api_key)` — a **constant**, identical on every
request. It authenticates no individual payload, and it becomes replayable by anyone who observes a
single delivery. Its public API exposes coupons and license keys only, so there is no transaction
endpoint to confirm a sale against.

It stays closed until a trusted transaction-confirmation source, an intermediary, or a manual-review
workflow exists. Supplying `PAYHIP_API_KEY` would turn the receiver green without making a single
payload trustworthy.

Only **WhatsApp** (`WHATSAPP_APP_SECRET`) and **Beehiiv** (`BEEHIIV_WEBHOOK_SECRET`, the Svix
`whsec_`) need production secrets. **Telegram** is already configured and refuses forged and missing
headers; verifying its `setWebhook` `secret_token` registration is a separate operator evidence task
and cannot be done without the bot token.

## 7. Guards added so this cannot recur

- `ROUTER_MANIFEST` records every router mount attempt with its outcome and reason.
  `REQUIRED_V2_ROUTERS` names those whose absence is a failure. `router_manifest_status()` is the one
  verdict the gate and `/api/health` both read — and a required router that was never **attempted**
  counts as missing, because that is what an early import abort looks like.
- `/api/health` reports `routers`, `routers_missing` and `ws_ticket_store`, so a readiness probe can
  refuse a reduced deployment instead of reporting a healthy one.
- `tests/test_router_manifest_gate.py` pins route **identity** and security invariants, not a count.
- Both surface pins now **fail loudly** when the audit environment is missing a dependency, rather
  than passing against a smaller application.

## 8. Known, recorded, not fixed here

- **`ws_ticket_store` is `EPHEMERAL` on staging.** Production mounts a volume at `/var/data`, staging
  mounts none, so a staging redeploy reopens a 30-second replay window for a ticket still inside its
  TTL. Route- and environment-binding still hold. Measured, not assumed — and it is why the
  after-restart replay property is certified locally (two separate interpreters, one store) rather
  than on staging.
- **A ticket still travels in the URL.** It is single-use, 30-second, route- and environment-bound,
  and worthless once spent — but it is in a URL, and this record does not call that equivalent to a
  cookie. The browser path does not use it.
- Staging has **no Git trigger** (the Railway GitHub App grant is missing), so its provenance is a
  recorded SHA rather than platform attestation.
