# NEXORA Production-Readiness Audit

_Generated 2026-06-29 by a 4-lens multi-agent audit (architecture, security, performance/scale, devops) with adversarial verification of every critical/high finding. 18 agents, 13 confirmed critical/high, 0 wholly fabricated (3 impact-narratives downgraded during verification)._

## 1. Executive summary

**Verdict: MVP-solid on correctness, not yet production-ready on operations, and not yet scale-ready architecturally.**

The money path is genuinely well-built. The hardest correctness problems on a creator-payout platform — single-writer balance discipline, layered idempotency, careful refund/dispute reversal math, a real double-payout gate, signature-verified webhooks, and the IDOR-closed paywall — are implemented correctly and hold up under adversarial review.

But the platform is gated by **three independent blockers** before it can take real money or scale:

- **Security exposes the wall it built.** Two confirmed HIGH defects let a user defeat the very controls the money path depends on: anyone can forge a free "active" subscription via the unauthenticated `/api/nx/subscribe` route, and a user can flip their own `is_suspended` flag off (and rename `full_name` to impersonate) via the `User` entity ACL.
- **Operations is effectively blind and unrecoverable.** Sentry is wired in code but `sentry-sdk` is in no requirements file — a guaranteed silent no-op. No backup/restore for a single-file financial SQLite DB. No CI runs the 132 tests on a PR.
- **The architecture has a hard scale ceiling and a latent data-integrity hazard.** Dual write paths into shared tables permanently diverge (worst: DMs split across `nx_messages` vs `nx_dms`), and `init_db()` runs full DDL on every entity request, taking the SQLite write lock on the read path.

**Single biggest risk:** unauthenticated subscription forgery (`/api/nx/subscribe`) + self-service un-suspension via the `User` entity. Together they let any caller get paid content free and let a banned user re-enable themselves. Deploy-blockers, not roadmap items.

## 2. What's already strong

- **Single-writer balance invariant** — `recalc_creator_stats` (`nexora_ops.py:8-36`) is the only writer of `available_balance`/`total_earnings`; checkout deliberately doesn't increment (`nexora_payments.py:349-353`).
- **Layered idempotency that holds** — SELECT-1 fast path + partial UNIQUE `ux_tx_stripe_id` (`nexora_db.py:319`) + atomic `nx_payment_events` ledger.
- **Careful money-reversal math** — partial refunds recompute net from immutable gross + cumulative `amount_refunded`; reversed rows never re-opened; correlation by `payment_intent`/`charge_id`.
- **Real paywall IDOR fix** — fan identity only from `verify_fan_token(Bearer)`, locked posts blank `body/text/media` (`api.py:10809-10830`).
- **Entity API is not SQL-injectable** — identifiers from the trusted registry, bound params, `_from_fe` allowlist prevents mass-assignment.
- **Thoughtful deploy scaffolding** — Dockerfile fingerprint + import smoke-test, WAL + `busy_timeout`, `.railwayignore` excludes the DB file, `/api/health`.
- **Strong money-path tests** — 132 tests weighted to refunds (17), webhook idempotency (9), payout safety (3).

## 3. Prioritized issues (all lenses)

| Severity | Lens | Issue | File / Area | Fix |
|---|---|---|---|---|
| **HIGH** | Security | Unauthenticated subscription forgery — grants paid access free; can forge in another fan's name | `api.py:10853-10869` (`nx_subscribe`), public via `/api/nx/` prefix `api.py:198` | Delete/internalize the route; subscriptions only via the signature-verified webhook (`_handle_checkout`). |
| **HIGH** | Security | Self-service un-suspension / impersonation via `User` entity — `is_suspended` + `full_name` self-writable | `nexora_entities.py:93-105` + `api.py:10577-10587` | Move `is_suspended` to `writable_admin`; lock `full_name`; audit all enforcement-gating columns. |
| **HIGH** | Architecture | Dual write paths into shared tables permanently diverge; DMs split `nx_messages` vs `nx_dms`, no reconciliation | `nexora_db.py:456-489` vs `nexora_entities.py:33-49`; `nx_messages` vs `nx_dms` | One writer per table; legacy routes → thin adapters over `entity_create`; collapse `nx_messages`→`nx_dms`. |
| **HIGH** | Performance | `init_db()` runs full DDL (28 CREATE TABLE + ~22 INDEX + PRAGMA) on **every** entity request — DDL on the hot read path, takes the WAL write lock | `nexora_entities.py:333,363,393,428,487,511`→`nexora_db.py:340` | Call once at startup + module-level `_initialized` guard. ~6-line change, largest latency win. |
| **HIGH** | DevOps | No CI runs tests/lint/build on PR (either repo) | `.github/workflows/` | Add `pull_request` workflows (pytest+flake8 / npm lint+test+build); required checks; gate docker-push on tests. |
| **HIGH** | DevOps | Sentry wired but `sentry-sdk` in no requirements file — silent no-op; zero error reporting | `sentry_init.py:40-47` + `requirements-server.txt` | Add `sentry-sdk[fastapi]`; set DSN/ENV/RELEASE; wire FE `@sentry/react`; verify a test exception lands. |
| **HIGH** | DevOps | `stripe_id` UNIQUE-index migration runs lazily, 500s on a prod DB with duplicate `stripe_id`; boot failure swallowed so healthcheck stays green | `nexora_db.py:319,403` + `api.py` init | De-dup (keep earliest) before `_INDEXES`; move `init_db()` into lifespan; seed-dupe test + preflight count. |
| MEDIUM | Security | KYC PII (legal name, DOB, ID/selfie URLs) at-rest plaintext, no column encryption (flow currently unwired) | `nexora_db.py:268-284` | Encrypt PII columns / opaque keys; authenticated content-sniffed EXIF-stripped upload + signed short-TTL delivery — before KYC goes live. |
| MEDIUM | Security | Notification spoofing → in-app phishing; `owner_from_body=True` lets any fan inject notifications w/ links into any feed | `nexora_entities.py:119-132` | Restrict `create_roles` to admin / server-side `_notify()` only; validate recipient; server-stamped sender. |
| MEDIUM | Security | Login brute-force: rate limiter keys on spoofable `X-Forwarded-For`, no per-account lockout/CAPTCHA; 6-char min pw | `api.py:737-760` + `nexora_auth.py:123,216` | IP from trusted proxy (CF-Connecting-IP); per-email+IP backoff/lockout + CAPTCHA; raise pw length + breach check. |
| MEDIUM | Security | No session revocation on suspend/pw-change; money routes use `_nx_require_creator` (ignores `is_suspended`); 30-day TTL | `nexora_auth.py:91-95,22` + `api.py:10728,10887` | Revoke-all on suspend/pw-change; route money endpoints through suspension check; shorten TTL + rotation. |
| MEDIUM | Security | Bearer token in `localStorage` (XSS-exfiltratable); CSP Report-Only, excludes SPA, keeps `unsafe-inline/eval` | `nxHttpClient.js` + `netlify.toml` | httpOnly+SameSite cookie + CSRF (or short TTL + rotation); enforce CSP without `unsafe-*` on SPA origin. |
| MEDIUM | Arch | HTTP/business/DB concerns interleaved; two identity layers (creator token vs unified `nx_users`) mixed by routes | `api.py:10410-10452`; `nexora_users.py` vs `nexora_auth.py` | Thin service layer both route families call; unify on `nx_users` w/ `creator` as a role; one shared `Depends`. |
| MEDIUM | Arch | `read_public` entities allow generic reads w/ no field redaction — `GET /api/nx/e/Post` can return subscriber-only text; `CreatorProfile` exposes `available_balance` | `api.py:10533-10559`; `nexora_entities.py:281-309` | `read_public` = "listable" not "all columns"; add `public_fields` allowlist; route generic Post reads through the paywall; add tests. |
| MEDIUM | Arch | Connection-per-call defeats multi-statement atomicity; legacy `/subscribe` = two independent commits | `nexora_db.py:31-42`; `nexora_ops.py:10-34` | `with get_conn() as conn` context manager; pass `conn` into DB fns so routes compose one transaction. |
| MEDIUM | Arch/Perf | SQLite single-file on one volume + single host = no horizontal scale; media on local disk via tunnel, no CDN | `nexora_db.py:18-26` | Known launch tradeoff; plan Postgres + R2/S3 + CDN (see §4). |
| MEDIUM | Perf | `recalc`/Messages queries defeat BINARY indexes with `COLLATE NOCASE` → full SCANs (EXPLAIN-confirmed) | `nexora_ops.py:12-31`; `nexora_entities.py:367-368` | Emails already lowercased on write — drop `COLLATE NOCASE` so indexes seek; UNION the DM OR-scan; verify EXPLAIN. |
| MEDIUM | Perf | `home_feed`/`dashboard_data` ship unbounded result sets; feed filtered client-side; dashboard unbounded `SELECT *` of ledger | `nexora_aggregations.py:9-44`; `Home.jsx:48-50` | Push follow/sub filter into SQL w/ keyset pagination; cap dashboard lists; separate `/transactions`. |
| MEDIUM | Perf | No route code-splitting — 38 pages eagerly bundled; admin/PDF tooling shipped to every fan; CJS `lodash` | `App.jsx:14-60`; `vite.config.js` | `React.lazy()`+Suspense per route; `manualChunks`; `lodash-es`/per-method imports. |
| MEDIUM | Perf | Full-res images, no `loading="lazy"`/`srcset`/CDN — media egress via one tunnel is the true media-scale wall | `Home.jsx:111-190`; `api.py:726` | `loading="lazy"`+`decoding="async"` now; responsive variants at upload; object storage + CDN. |
| MEDIUM | Perf | Messages polls full 200-row table every 5s/client; conversation list derived client-side | `Messages.jsx:24-50` | `since=<cursor>` or SSE/WebSocket; scope by `conversation_id` (`ix_dm_convo`); memoize w/ React Query `select`. |
| MEDIUM | Perf | Connection-per-helper: `/api/nx/me` opens 6 connect/PRAGMA/close cycles; `mkdir` syscall every `get_conn` | `nexora_db.py:31` | Drop `mkdir` from `get_conn`; per-request connection reuse; aggregate stats into one connection; `COUNT(*)` not `list_posts(9999)`. |
| MEDIUM | DevOps | FE→BE hostnames unreconciled (`api.`/`nai.`/`app.`); CORS default whitelists `app.`, FE calls `api.` | `api.py:693-706` + `.env.example:8` | One `DEPLOY.md`; set `CORS_ORIGINS` to the real Netlify origin; verify a real cross-origin XHR. |
| MEDIUM | DevOps | Contradictory deploy descriptors: root `railway.json` (NIXPACKS+`core.api:app`) vs `deploy/railway.json` (DOCKERFILE+`main.py --dashboard`); fly/render too | root vs `deploy/railway.json`, `nixpacks.toml`, `Dockerfile`, `deploy/fly.toml`, `deploy/render.yaml` | Pick ONE (Railway+Dockerfile matching `core.api:app`); archive the rest; reconcile the Mac-mini `:8001` story. |
| MEDIUM | DevOps/Arch | `core.api` monolith couples nexora deploy to ~15k lines shared w/ bots/KAI; any import error 500s the money API | `core/api.py` | Extract `/api/nx` into its own APIRouter/ASGI app; short-term ensure CI import-smoke covers nexora routes. |
| MEDIUM | DevOps | In-memory rate limiter is per-process, resets on redeploy, trusts client XFF | `api.py:733-761` | Shared store (Redis) keyed on trusted proxy IP; validate the proxy chain. |
| MEDIUM | DevOps | `/api/health` reports ok from memory % only — never checks DB or `/var/data` writability | `api.py:3154-3200` | Add `/api/health/ready` (`SELECT 1` + writability); point `healthcheckPath` at it. |
| MEDIUM | DevOps | Stripe/prod secrets not validated at boot; dual env-var name for webhook secret | `.env.example` + `nexora_payments.py` | Fail-fast when `ENV=production` and keys absent; one canonical webhook-secret name; `.env.nexora.example`. |
| MEDIUM | DevOps | No backup/restore for the single-file financial SQLite DB | `nexora_db.py:20-26` | Litestream → S3/B2 (or cron `sqlite3 .backup`); test a restore; document RPO/RTO. **Mandatory before real money.** |
| MEDIUM | Arch | Nexora = 39 inline `@app` routes in a 15.4k-line monolith, not an APIRouter/package | `api.py:10473+` | Extract `core/nexora/router.py` with `APIRouter(prefix='/api/nx')`; `_nx_require_*` → `Depends()`. |
| LOW | Security | `CreatorVerification` docs stay owner-mutable after admin review (TOCTOU) | `nexora_entities.py:251-271` | Lock owner-writes once `status` leaves `'submitted'`; validate consent + required fields at submit. |
| LOW | Arch/Sec | Stripe/secret config read ad hoc via `os.getenv` w/ silent `''` defaults | `nexora_payments.py:8-9`; `nexora_connect.py` | `core/nexora/config.py` reads+validates all vars once at import, fail-fast. |
| LOW | Perf | `recalc_all()` recalcs every creator serially (4 scans each) → O(N·M); one admin click can stall the writer | `nexora_ops.py:39-43` | After collation fix, set-based `GROUP BY` aggregate `UPDATE`s instead of a Python loop. |
| LOW | Arch | Tests money-path-heavy; dual-writer divergence + generic entity-read paywall under-tested | `tests/test_nexora_*.py` | Add tests: legacy-vs-entity gate parity; non-subscriber can't read `Post.text`/`available_balance` via generic endpoint; DM history complete regardless of path. |
| LOW | DevOps | Creator media via single Cloudflare tunnel — no CDN, no redundancy (SPOF) | `cloudflared/config.yml.example` | Object storage + CDN w/ signed URLs; until then back up the media disk + document the SPOF. |

## 4. Scale-to-millions roadmap

**What breaks first:**
- **~1k** — fine (SQLite + WAL + busy_timeout).
- **~10k** — strained: single SQLite **writer** is the first wall (webhook bursts + recalc + per-request `init_db()` contend for the write lock → 5s timeout → 500); `COLLATE` full SCANs compound; `dashboard_data`'s unbounded ledger fetch risks latency/OOM for a successful creator.
- **~100k** — wall: single writer + single host saturate; can't add app replicas (each opens the same SQLite file); media egress through the one tunnel saturates host bandwidth — the true media wall.
- **~1M** — impossible without the migration below.

**Migration path (lowest-risk first):**
1. **Free headroom now:** remove `init_db()` from the hot path; drop `COLLATE NOCASE` (emails already lowercased) so indexes seek. ~tens of lines, big SQLite headroom.
2. **Bound payloads:** SQL-side feed filter + keyset pagination; cap `dashboard_data`; paginated `/transactions`.
3. **Extract `/api/nx` into its own deployable service** (APIRouter) so it scales/deploys independently and an unrelated import can't 500 the money path.
4. **Reconcile dual writers, then migrate to Postgres** (entity layer is a thin column-mapped abstraction; the single-writer recalc invariant ports cleanly). Unify writers FIRST — two diverging writers are far more dangerous under Postgres concurrency.
5. **Media → object storage (R2/S3) + CDN** with signed short-TTL URLs + thumbnails at upload.
6. **Add Redis** for read-hot aggregates + a shared, IP-trustworthy rate limiter.

## 5. Pre-go-live DevOps checklist

Items 1-6 are **hard blockers** for taking real money.
1. **Close the two HIGH security holes** — delete/internalize `/api/nx/subscribe`; move `User.is_suspended` to `writable_admin` + lock `full_name`; add tests.
2. **De-dup `stripe_id` BEFORE the UNIQUE-index migration** (keep earliest), inside `init_db()` before `_INDEXES`; move `init_db()` into the FastAPI lifespan so failure fails the healthcheck; seed-dupe test + preflight count.
3. **Wire real error reporting** — add `sentry-sdk[fastapi]`; set DSN/ENV/RELEASE; FE `@sentry/react`; verify a test exception lands.
4. **Stand up CI** — PR pytest+flake8 / npm lint+test+build; required checks; gate docker-push on tests.
5. **Backups** — Litestream → B2/S3 (or cron `.backup`); **test a restore**; document RPO/RTO.
6. **Pick ONE deploy target + reconcile hostnames** — Railway + Dockerfile (matches `core.api:app`); archive the rest; one `DEPLOY.md` reconciling `api.`/`nai.`/`app.` + the Mac-mini `:8001` story.

Then before live traffic:
7. Set `CORS_ORIGINS` explicitly to the real Netlify origin; verify a real cross-origin XHR.
8. Fail-fast on missing secrets when `ENV=production`; one canonical webhook-secret name; source from `wvkey`, not plaintext `.env`.
9. Add `/api/health/ready` (`SELECT 1` + writability); point `healthcheckPath` at it.
10. Harden auth — CF-Connecting-IP not raw XFF; per-email lockout + CAPTCHA; revoke-all on suspend/pw-change; route `/me`/`/earnings`/`/payouts` through the suspension check; shorten TTL.
11. Confirm the Stripe webhook secret matches the dashboard; a real signed test event recorded exactly once.
12. Free perf wins (ship with the above): remove `init_db()` from hot path; drop `COLLATE NOCASE`; add `loading="lazy"` to feed/avatar images.
