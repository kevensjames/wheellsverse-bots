# WHEELLSVERSE — Production Deployment Plan (DRAFT for approval)
## Bring the staging-certified A↔B governed stack to production
**Status: PLAN ONLY. Nothing in here has been executed. Production is UNTOUCHED. Execution requires a second explicit confirmation, phase by phase.**

---

## 1. Current production reality (read-only, verified 2026-08-29)
| | |
|---|---|
| App A (Command Center) | **live** at app.wheellsverse.com · Railway `grateful-flexibility/production/wheellsverse-v2` · deploy `e73ef751` |
| KAI bridge in prod | **`enabled:false`, `upstream_configured:false`** — fail-closed; no App B wired |
| App B (governance runtime) | **NOT in production** — exists only on staging (and locally) |
| apex wheellsverse.com | Cloudflare Pages (no `/api` proxy) — not the app origin |

**So today prod = Command Center UI only.** The certified value (governed KAI, worker, bridge) is **not** in production yet. This plan stands it up.

## 2. What "deploy the certified stack" means (scope decision — YOURS)
Two options; the plan below covers **Option A** (the full certified value) and flags where **Option B** stops short.

- **Option A — full unified OS (what was certified):** stand up **App B in production** (new service + prod Postgres + prod Redis + funded OpenAI key), then flip App A prod's bridge on. Delivers governed KAI/worker/automation to the live Command Center.
- **Option B — App A improvements only:** redeploy prod App A from the certified branch for the env-label fix etc., **bridge stays OFF**. Low risk, but delivers none of the A↔B governance. (Not recommended as the endpoint — it's a subset.)

## 3. Prerequisites before ANY production phase (human/owner-only)
1. **Funded production OpenAI key** (separate from staging) — governed KAI needs it; a 429/no-credits repeats the staging story.
2. **Production data stores for App B** — a dedicated **prod Postgres** (with the Supabase-owned `profiles/conversations/messages` present, or the base-compat migration to create them) + **prod Redis**. **Never** point App B prod at a staging store.
3. **`SESSION_SIGNING_SECRET`** — one strong secret **shared** by prod App A + prod App B (rotate from any staging value; never reuse the staging secret).
4. **Money/safety invariants confirmed for prod App B:** SOL money mode **MOCK**, Empire **DISABLED_RESTRICTED_LAB_ONLY**, destructive scopes OFF (`KAI_SCOPE_*` unset), self-heal apply OFF — exactly as on staging.
5. **Operator go/no-go recorded** for each phase below.

## 4. Deploy sequence — staged, dark-first, reversible
Each phase has a verify gate and a rollback. **Stop and get confirmation between phases.**

**Phase 0 — Freeze & record rollback points**
- Record current prod App A deploy id `e73ef751` (rollback target) + branch/SHA to deploy (`feat/kai-capability-fabric` @ the certified HEAD).
- Confirm a clean tree; tag the release.

**Phase 1 — Provision prod App B infra (💲, dark)**
- New prod Postgres + Redis (isolated). Run `alembic upgrade head` on the empty prod DB (proven repeatable). No App A change yet.
- *Rollback:* delete the new resources (nothing is wired to them).

**Phase 2 — Deploy App B to prod (dark, bridge still OFF)**
- Deploy App B (same Docker image pattern as staging) with prod DB/Redis/secrets + funded OpenAI key + `APP_ENV=production`.
- *Verify:* `/health` 200 env=production; governance gates return 403 unauth; a governed owner call (via a one-shot shell cookie) returns 200 + logs `llm_call_log`.
- *Rollback:* remove the App B service. App A prod is still untouched, bridge still off.

**Phase 3 — Wire App A prod → App B prod (flag-gated, canary)**
- On prod App A set `KAI_BRIDGE_ENABLED=true`, `KAI_UPSTREAM_URL=<App B prod internal>`, shared `SESSION_SIGNING_SECRET`, and deploy the certified App A branch (env-label fix + capability flag).
- *Verify (canary):* `/admin/kai-bridge/health` → enabled/upstream_configured; owner→200 / operator→403 / anon→401 through the prod bridge; env chip=PRODUCTION; console clean.
- *Rollback (instant):* set `KAI_BRIDGE_ENABLED=false` (fail-closed 404) — the bridge disables without touching App B; or redeploy App A prod to `e73ef751`.

**Phase 4 — Full enable + watch**
- Announce, monitor `llm_call_log` spend + audit + health for a soak window.
- *Rollback:* same instant flag-off as Phase 3.

## 5. Rollback summary (fastest → fullest)
1. **Bridge off:** `KAI_BRIDGE_ENABLED=false` on prod App A → governed path 404s, prod reverts to today's UI-only behavior. Seconds.
2. **App A rollback:** redeploy prod App A deploy `e73ef751`. Minutes.
3. **App B teardown:** remove the App B prod service + (optionally) its stores. Prod App A unaffected once the bridge flag is off.

## 6. Risks & honest caveats
- **New prod surface:** App B in prod is a new internet-reachable governance runtime — it must enforce `require_kai_ultra` at every entry point (certified) and keep money mode MOCK.
- **Cost:** prod App B + Postgres + Redis + OpenAI usage are ongoing prod costs.
- **App A slow boot:** core.api takes ~5 min to import; prod healthcheck window must accommodate it (it does today).
- **Not re-certified in prod:** staging certification ≠ production certification. Phase 2–3 verifies re-prove the governed path on prod infra before full enable.
- **Secrets:** never reuse staging secrets/keys in prod; mint fresh.

## 7. Explicit execution gate
**None of the above runs without your phase-by-phase confirmation.** On approval I execute **one phase at a time**, verify its gate, and stop for your go before the next. Production is not auto-deployed.
