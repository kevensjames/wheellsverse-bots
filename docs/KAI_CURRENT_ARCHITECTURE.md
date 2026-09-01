# KAI — Current Architecture (§1)

Map of the system **as it exists and runs today** (2026-09-01), so the Holding-OS mission extends it
and never rebuilds it. Verified against the live deploy + the source on `feat/kai-exec-appb-integration`.

## 0. Two deployed apps + one bridge (three surfaces, one git tree)

| Surface | Entry point | Deploy | Live SHA | Serves |
|---|---|---|---|---|
| **App B** (KAI daemon) | `backend/app/main:app` | Railway **kai-prod** (project `kai-production`, Dockerfile.staging, `railway up` snapshot) | `feat/kai-exec-appb-integration` **3b9caff** | auth, provider router, memory/RAG/KG, tools, governance, self-heal, **Holding OS**, **Capability Fabric**, **execution gateway** |
| **App A** (core.api) | `core.api:app` | Railway **grateful-flexibility** (git-connected, branch `production`, NIXPACKS) | `production` **a886ec6** | apex/admin, **Nexus capability catalog + page + module**, the **App A→App B bridge** |
| Nexus static | `frontend/admin/*` | served by App A (allowlisted `/admin/*.js|.css|.json`, `Cache-Control: no-store`) | — | `kai-capabilities.html`, `kai-nexus-*.js`, `kai-presence`, `holding.html`, `kai-capability-catalog.json` |

**Owner auth reality:** App B has **no `API_KEY` field** in `Settings` — owner auth is a **session cookie** (`wv_session`) minted with `SESSION_SIGNING_SECRET` (shared App A/App B so one login authenticates both), resolving to `ROLE_OWNER` which holds `SCOPE_KAI_ULTRA` (all scopes). `require_kai_ultra` (owner-only) gates `/admin/kai-chat` and the capability execution routes; the App A→App B **bridge** (`core/kai_bridge.py`) re-enforces `kai.ultra` on the `kai-chat` + `capabilities` prefixes (operator-ok on kg/twin/persona/briefing/research/memory/holding). `MONEY_MODE=MOCK`.

## 1. Capability Fabric — `backend/app/services/capability/` (BUILT + LIVE)
The governed capability system, **certified in production** (Execution V1, 2026-09-01).
- `manifest.py` — `CapabilityManifest` + enums. **`ActionClass` = READ_ONLY · REVERSIBLE_WRITE · HIGH_IMPACT · FINANCIAL · DESTRUCTIVE · PROHIBITED** → this is the mission's **§45 A0–A5** already, in code.
- `registry.py` (single registry, 126 seeded), `brain.py` (intent→selection, honest availability), `graph.py` (relations), `risk.py` (`evaluate_policy` — the choke point), `security.py`, `lifecycle.py`, `results.py` (normalize + injection scanner + trust boundary §58), `coding.py` (CodingWorkerRouter), `seed.py` (**126 capabilities**).
- `invocation.py` — **`governed_invoke`**: lifecycle-gate → policy → timeout → crash-redaction → trust re-ownership → size clamp → audit.
- `execution.py` — **`CapabilityExecutionService`** (the one execution boundary; server-owned operation allowlist, V1 read-only/compute envelope, SSRF guard, fixture file boundary, idempotency, owner-scoped rate limit, evidence).
- `command.py` — **Brain→execution bridge** (Brain selects, same service executes).
- `live_adapters.py` — `MarkItDownAdapter`, `YtDlpAdapter` (LIVE, yt-dlp in the image), `CodebaseMemoryMcpAdapter` (SUBPROCESS).
- Router `backend/app/routers/admin_capabilities.py` (owner-only, flag `KAI_CAPABILITY_EXECUTION_ENABLED`, LIVE ON): `GET /admin/capabilities`, `/{id}/status`, `POST /{id}/invoke`, `/{id}/test`, `/command`, `GET /invocations`.
- **Live-certified:** yt-dlp metadata OK+evidence · download NOT_ENABLED · SSRF INPUT_REJECTED · unknown-op OPERATION_UNKNOWN · anon 403 · markitdown UNAVAILABLE (honest).

## 2. Holding OS — `backend/app/services/holding/` (BUILT; flag `KAI_HOLDING_ENABLED`)
Maps directly onto much of the mission's §39–55:
- `registry.py` — entity registry (companies), no-fabrication `report_value`.
- `reports.py`, `priorities.py` — source-cited deterministic priority feed (not LLM-invented) → **§43/§44 planner precursor**.
- `proposals.py` + `proposals_store.py` — proposed→approved/rejected/executed state machine (dedup + cooldown) → **§47 OwnerActionQueue precursor**.
- `executor.py` — `execute_approved` (bound to approval; refuses non-approved) → **§46 autonomous-work-engine precursor** (read-only runners).
- `worker_jobs.py` — dispatch plane: state machine, lease/heartbeat, idempotency, crash-reclaim → **§79 tool-sandbox / §46 worker plane**.
- `watch.py` + `watch_store.py` — change/anomaly detection (diff vs last state, spam-free) → **§41 HoldingObserver** (exists under a different name).
- `briefing.py` — morning briefing → **§48 DailyOwnerBrief**. `delivery.py` — Telegram (opt-in). `status.py` — worker liveness + autonomy roll-up (`AUTONOMOUS_READ_ONLY`/`DEGRADED`).
- `signals.py`, `kpi_history.py`, `entity_status.py`, `staging_cert.py`.
- Router `admin_holding.py` (owner-only): overview, entities/{id}, briefing, proposals(+approve/reject/execute), worker-jobs(+claim/heartbeat/complete/reclaim), workers/heartbeat, status.

## 3. What the mission needs that does NOT yet exist (the real new build, §37–40)
- **`SelfModel` / OperationalSelfModel (§37–38)** — ✅ BUILT `self_model.py` (7/7). Live-state wiring to the twin pending (Wave 2/§63).
- **`HoldingDigitalTwin` (§3/§39)** — ✅ BUILT `digital_twin.py` (9/9): normalized live index over registry/status/priorities/proposals/capability; dynamic company discovery; `Fact` provenance; `SOURCE_MAP`; portfolio view. Not a second DB. See `KAI_HOLDING_DIGITAL_TWIN.md`.
- **`StartupStateModel` (§4/§40)** — ✅ BUILT (`StartupState` in `digital_twin.py`): typed per-company state, money/customers only via `report_value` → `UNAVAILABLE` when un-sourced.
- **`HoldingStateReconciler` (§8-10,§17)** — ✅ BUILT `state_reconciler.py` (9/9): deterministic versioned material-change engine; baseline + no-change → `NO_MATERIAL_CHANGE`.
- Remaining NEW/EXTEND: `CurrentPlan` model + plan reconciliation (§11-13, head of Wave 2), continuous cycle (§16), AutonomousWorkEngine (§19), owner-queue filter + Today brief (§24-27), A2 framework (§34-36), SelfImprovementEngine (§37-40), schedulers (§41-42), Nexus UI (§49-52).
- **Named A0–A5 action classes (§45)** — the concept exists (`ActionClass`); a holding-facing A0–A5 mapping + the **AutonomousWorkEngine (§46)** that *executes* A0/A1 and certified-A2 (vs. today's propose-only) is NEW/EXTEND.
- **`SelfImprovementEngine` (§52–54)** — self-heal exists (detection + reversible actions); the safe self-code loop (issue→spec→worktree→worker→independent-review→PR) as a first-class engine is NEW/EXTEND.
- **Continuous analysis loop (§42)**, **CompanyPlanner/PortfolioPlanner (§43–44)** as first-class, **DecisionJournal (§62)**, **PlanRetrospectives (§63)** — NEW.
- **Resource/Cost schedulers (§75–76)**, **CredentialBroker (§77)**, **network-policy/quarantine (§78)** as first-class — PARTIAL (manifest declares network/resource profiles; enforcement engine NEW).

## 4. Existing controls to REUSE (never rebuild)
- **Governance/policy:** `capability/risk.evaluate_policy` + `governed_invoke` (auth, action-tier floor, approval, audit). Holding `_audit_proposal` → `AuditLog`.
- **Money safety:** `MONEY_MODE=MOCK` throughout; no financial writes anywhere; financial capabilities RESTRICTED/DISABLED.
- **Kill switches:** `KAI_CAPABILITY_EXECUTION_ENABLED`, `KAI_HOLDING_ENABLED` (+ per-capability `activation`/`quarantine` in the registry). Mission's **§94 `HOLDING_AUTONOMY_ENABLED` / §95 per-capability** map to these.
- **Trust boundary (§58):** `results.sanitize_external_result` + `scan_for_injection` — every external/capability output is UNTRUSTED, re-scanned, cannot self-authorize.
- **Self-heal:** `services/supreme/*`, `self_heal.py` (detection-only + reversible, quad-gated), `self_correction/*`.
- **Model routing:** intent router over openai/anthropic/perplexity/cloudflare/ollama (Ollama-first, per-user budget). **Do NOT replace with LiteLLM wholesale (§17)** — evaluate LiteLLM as an adapter *beneath* the existing router.
- **Memory:** pgvector `memories` (typed, decay); RAG (chunk→embed→citations); SQLite KG. **Canonical writer = kai-memory** (§64) — external memory providers stay subordinate.
- **Infra:** kai-prod (Postgres+Redis volumes, `kai-watch-cron`, `kai-briefing-cron`, external `kai-prod-monitor` */5 cron); App A grateful-flexibility; Mac mini (Ollama, colima, `wv-github-worker`/`wv-browser-worker`/`wv-egress-proxy` images).

## 5. Deploy + rollback (current)
- App B: `railway up --service kai-prod` from a kai-production-linked worktree at the target SHA (classifier-gated to the operator). Rollback: previous SHA (`914855d` pre-execution).
- App A: `git push origin <branch>:production` → git-connected auto-deploy (classifier-gated). Rollback: `production` prior head.
- **Both deploy triggers are operator-run.** Owner auth for direct App B calls = a minted `wv_session` cookie (SESSION_SIGNING_SECRET), not an API key.

**Consequence for this mission:** the "B" objective (autonomous operator) is mostly **extending the Holding OS + wiring the AutonomousWorkEngine to the certified Capability ExecutionService**, plus three genuinely-new models (SelfModel, DigitalTwin, StartupState). The "A" objective (capability library) is a **~55-candidate delta** on the 126 already cataloged — verified in `KAI_CAPABILITY_MASTER_INVENTORY.md`.
