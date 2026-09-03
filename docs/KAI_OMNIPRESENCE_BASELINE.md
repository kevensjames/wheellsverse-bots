# KAI OMNIPRESENT HOLDING COMMAND OS — Program Baseline

> Program architect baseline for evolving the EXISTING KAI Holding OS into the Omnipresent
> Holding Command OS. Grounded in the §0–§90 spec index (TRUNCATED at ~§90 tail), the six
> domain inventories (A–F), and MEMORY.md. This is a **reconcile + expand + unify** program,
> not a build-from-scratch. Every "EXISTS/PARTIAL" claim below cites a concrete module.
>
> **Spec-tail warning:** the operator's source message was cut at "exceeded 50,000 char limit".
> §90's tail and any §91+ are MISSING. Phase 5 (Holding Command API) is the section most likely
> to be under-specified as a result — do not treat §90 as complete.

---

## 1. §2 CURRENT RELEASE STATE — SATISFIED

**§2 is DONE this session. Recorded here per the spec's instruction.**

- **PR #67 merged** and deployed to **BOTH** production services at **SHA `4fbfb8e`**:
  - **App A** = `wheellsverse-v2` / `app.wheellsverse.com` (core.api:app; railway-up, not git-integrated — SHA labels can read stale).
  - **App B** = `kai-prod` / `kai.wheellsverse.com` (`backend/app/main.py`).
- **Certified this session** across 4 viewports (Playwright), authority posture confirmed:
  - Autonomy **OFF** (`HOLDING_AUTONOMY_ENABLED`, `KAI_CAPABILITY_EXECUTION_ENABLED`, `KAI_A2_EXECUTION_ENABLED` all dark, fail-closed).
  - **MONEY_MODE = MOCK** (no real fund movement; `digital_twin.report_value` → UNAVAILABLE for un-sourced money).
  - **Dashboard reconciled** — `/admin/holding` reflects real exists/deployed/enabled/dark state (dashboard-truth policy honored).
- What is LIVE in prod is **read-only**: Holding OS dashboard, KAI presence layer (`kai-presence.js` orb + governed streaming drawer), Nexus immersive view, App A↔App B bridge (`kai_bridge.py`), deployment-truth registry, signals/DETECT_ONLY (dark), A2/self-improvement/autonomy (dark).

**Conclusion:** §2 needs no further work. The current release is the certified floor this program builds up from. All new autonomy/execution stays dark (§0 #12: deployment ≠ authority) until a genuine hosted-edge certification gate is passed — and **no isolated Railway staging environment exists yet** (recurring blocker per MEMORY), which gates every "enable authority" step in this program.

---

## 2. GAP MATRIX — ALL 90 SECTIONS

Verdict legend: **EXISTS** (built, tested, cited) · **PARTIAL** (substrate exists, real gap) · **NET-NEW** (nothing to reuse) · **SATISFIED** (done).
Paths are relative to the `cyberops` tree (`feat/kai-cyber-operations`) unless noted; holding services are byte-identical in `feat/kai-exec-appb-integration`, and the capability fabric is byte-identical in all three trees.

### Cross-cutting / release

| § | Verdict | Reuse module (path) or gap |
|---|---------|----------------------------|
| §0 permanent principles | PARTIAL | Enforced-in-code across modules: `holding/a2_framework.py` (FORBIDDEN_A2_ACTIONS, `_AUTHORITY_IMMUTABLE`), `capability/coding.certify_worker_result` (#11 no self-approve), `holding_cycle.py` (3 fail-closed brakes, #12), `kai_bridge._STRIP_REQUEST`+`invocation.py` redaction (#9), `capability/results.Provenance` (#16). **Gap:** #1/#2/#3/#8 are process norms with no code enforcer; no single ConstraintRegistry module (see §1). Treat §0 as a continuous review gate, not a phase. |
| §2 current release | **SATISFIED** | See Section 1. |

### DOMAIN A — Presence / Voice / Gesture / Avatar / Digital Human

| § | Verdict | Reuse module (path) or gap |
|---|---------|----------------------------|
| §4 KaiPresenceState | PARTIAL | `frontend/admin/kai-presence.js` (kaiState 6-state) + `kai-nexus-embodiment.js` (14-state). **Gap:** no persistent *backend* KaiPresenceState with full §4 field set (attention/mission-focus/pending-approvals/runtime/sha/model/latency); frontend-only, ephemeral. |
| §5 always present | EXISTS | `core/api.py::_inject_kai_presence()` injects orb+drawer on all `/admin/*`; Cmd/Ctrl+K. **Gap:** mobile-compact/push-to-talk absent. |
| §6 always-listen privacy | PARTIAL | `kai-speech-input.js` honest (BROWSER_LIMITED, no covert loop). **Gap:** 4 privacy modes + mic/recording indicators + mute are NET-NEW; ⚠ `core/wake_word_listener.py` is a covert always-on mic (NarAI) that would violate §6 if enabled here. |
| §7 voice command center | PARTIAL | All adapters exist + certified (`kai-speech-input.js`, `kai-tts-provider.js`, `kai-barge-in.js`, `core/voice_router.py`). **Gap:** never assembled into a live VoiceSessionManager loop — parts bin, not a center. |
| §9 gesture | NET-NEW | No gesture module anywhere. Only the session/scope model exists to enforce "gestures never authorize." |
| §10 avatar | PARTIAL (dormant) | `kai-avatar-driver.js` + viseme engine/mapper/morph-registry + `kai-glb-renderer.js`/`-validator.js` + `kai-avatar-lab.html` built+served+tested. Live = VIDEO swap (`nexus-assets/`). **Gap:** GLB honestly ASSET_UNAVAILABLE (no rigged `.glb`); driver suite not `<script>`-included on any live page. |
| §49 digital human | PARTIAL | `kai-nexus-embodiment.js` maps state→video/halo/subtitle/voice; `kai-subtitles.js` + TTS + barge-in exist. **Gap:** facial/viseme EXTERNAL_BLOCKED on rigged asset; modules not wired to a live surface. |
| §50 voice personality | PARTIAL | Masculine voice-pick in `kai-presence.js::_pickVoice` + `kai-tts-provider.js::scoreVoice`. **Gap:** no defined calm/concise/executive personality layer; TTS rate/pitch hardcoded. |
| §51 speech length | PARTIAL | `speak()` truncates 700 chars; subtitle 240. **Gap:** no summary-first-voice / depth-on-dashboard split; no "show details/explain more/technical" affordance. |
| §52 interruptions | EXISTS | `kai-barge-in.js` = one certified cancellation path; live in `kai-presence.js` (`stopStream`/`stopSpeak`, Stop button, new-turn barge-in). **Gap:** spoken "stop" needs mic (dormant). |
| §54 global context | PARTIAL | ⚠ **Not covered by any inventory.** Grounded in Domain A §4 + MEMORY (P13 Nexus continues same conversation drawer→nexus): `kai-presence.js` carries conversationId + context. **Gap:** "this" resolving to selected item with evidence across navigation is unproven. |
| §64 never fake presence | EXISTS | State transitions driven by real SSE events; `kai-nexus.js` DEMO is `?scenario=`-only with banner; provenance REAL/DEMO/UNAVAILABLE tagged. Strong reuse anchor. |
| §66 owner arrival | PARTIAL | Presence reads `/admin/session/whoami` (session activation, not facial-id — correct); `briefing.py::kai_completed_since_last_visit`. **Gap:** no arrival trigger loading brief + comparing last visit on dashboard-open. |
| §67 presence settings | NET-NEW | No settings model/UI for greeting/voice/PTT/wake-word/gesture/camera/quiet-hours/severity. |
| §68 quiet mode | NET-NEW | No quiet-mode state/logic (closest = voice being Nexus-only, which is mode-based not governed). |
| §69 fullscreen command mode | EXISTS | **Two** immersive views: `/admin/nexus` (`nexus.html`) + `/admin/mission-nexus` (`kai-nexus.js`, 1660 ln). ⚠ Duplication — §69 must consolidate onto one. |

### DOMAIN B — Self-Model / Twin / Knowledge / Memory / Goals / Attention

| § | Verdict | Reuse module (path) or gap |
|---|---------|----------------------------|
| §1 OperationalSelfModel + 10 submodels | PARTIAL | `holding/self_model.py`, `holding/digital_twin.py`, `capability/graph.py` exist. **Gap:** RuntimeIdentity/ConstraintRegistry/SystemHealthModel/EvidenceStore only partial; MissionMemory/CurrentAttentionModel/GoalRegistry NET-NEW. |
| §14 HoldingDigitalTwin | EXISTS | `holding/digital_twin.py` (dynamic company discovery, `SOURCE_MAP`, `fact()`, `portfolio_view()`, money only via `registry.report_value`→UNAVAILABLE) + `holding/registry.py` (11-entity hierarchy). **Gap:** parent→child is implicit `products[]` not edges; plan fields are UNAVAILABLE placeholders. |
| §15 SystemKnowledgeIndex | PARTIAL | Sources exist (`repo_inspect.py`, `tech_doc_lookup.py`, `log_inspect.py`, `deployment_status.py`, `registry.py`, capability registry, twin, `../kg/`). **Gap:** no unifying query layer answering arch/dependency/change questions with evidence. |
| §16 knowledge freshness | PARTIAL | `digital_twin.fact()`/`_freshness()` emits value/source/observed_at/freshness/status; `registry.Confidence`. **Gap:** Fact dict has no per-fact `confidence` and no `evidence_ref` (~4 of 6 spec fields missing). |
| §17 CurrentAttentionModel | NET-NEW | Nothing. Substrate to assemble from: `self_model.what_am_i_doing()`, `portfolio_view().needs_attention`, `plan.py` tasks, `owner_queue`. |
| §32 memory | PARTIAL (wrong scope) | `../memory/store.py` (pgvector, **user-scoped**), `../kg/` triples, `../learning/` lessons, `proposals_store.py`/`cycle_store.py`. **Gap:** no holding-scoped typed memory (7 spec categories) with mandatory-provenance write-path. Reuse infra, add scope. |
| §55 multi-company reasoning | NET-NEW | ⚠ **Not covered by any inventory.** Grounded in Domain B substrate: `registry.all_entities()` + `digital_twin.portfolio_view()` give per-company state. **Gap:** no shared-issue detector (infra/vendor-cost/dup-caps/funnel/defect/cred) — extends §18 problem detection across companies. |
| §62 KAI own-status panel | EXISTS (field gaps) | `self_model.snapshot()/describe()/what_am_i_doing()` + `holding_view.py` + `holding.html:195`; `claims_consciousness=False` asserted. **Gap:** rendered panel omits prod/staging SHA split, model, latency, attention, autonomy-class, limitations, last-verified. |
| §63 limitations | PARTIAL | `self_model._KNOWN_LIMITATIONS` (4 concrete) via `snapshot().known_limitations`. **Gap:** dropped from `holding_view` (not rendered); static hardcoded, not live-derived. |
| §81 HoldingGoalRegistry | NET-NEW | Nothing. `registry.kpis[]` are free-text; `StartupState.current_goal` is UNAVAILABLE string. Reuse `../planning/` storage/approval pattern (distinct concept — do not overload work-goals). |
| §82 goal-gap analysis | NET-NEW | Depends on §81. Reuse the `priorities.py`/`reconcile_plan` deterministic-evidence style. |

### DOMAIN C — Proactive / Briefing / Problem / Opportunity / Idea / Prioritization / Review

| § | Verdict | Reuse module (path) or gap |
|---|---------|----------------------------|
| §11 ProactiveBriefingEngine | PARTIAL | `holding/watch.py` (`run_watch`/`diff`, change-only) + `self_improvement_detect.run_detection`. **Gap:** no unified engine with the full §11 trigger taxonomy (missing dashboard-open, mission-complete, approval-needed, deadline, opportunity). |
| §12 arrival brief | NET-NEW (stub) | `briefing.today_for_you()` returns `kai_completed_since_last_visit` key but nothing computes "since last visit". Depends on §66 owner-arrival event + last-visit store. |
| §13 DailyHoldingBrief | EXISTS (holes) | `reports.build_morning_briefing()` + `briefing.run_morning_briefing()` — exec/what-changed/health/systems/deploys/risks/priorities. Powers dashboard + spoken. **Gap:** missions/opportunities/recommendations sub-sections absent (engines don't exist); revenue/customers by-design REQUIRES_OPERATOR_CONFIRMATION. |
| §18 problem detection | PARTIAL | Two deterministic streams: `priorities.derive_priorities()` (operational) + `self_improvement_detect.Candidate` (code-defect). **Gap:** no unified `HoldingProblem` type; deploy-drift/mission-fails/security/doc-inaccuracy/stale-plans not wired in. |
| §19 solution engine | PARTIAL | `proposals._template()` (priority→action/plan/risk/reversible) + `SelfImprovementEngine.owner_review_package()` (full problem→verify→diff→rollback). **Gap:** one templated action not multiple **options**; no **cost** estimate. |
| §20 OpportunityEngine | NET-NEW | Zero (empty `digital_twin.opportunities` field only). Reuse the Candidate/evidence+confidence shape from `self_improvement_detect`. |
| §21 idea mode | NET-NEW | Zero. **Strong reuse base:** `proposals_store.py` (durable state machine + 24h dedup + `resolve_absent` superseding) — extend that table, do not fork. |
| §22 prioritization | PARTIAL | `priorities.derive_priorities()` deterministic + source-cited but flat 4-level severity, not the §22 ordered ladder. ⚠ **3 rankers exist** (`priorities`, `briefing._oa_key`, `proposals.build_daily_plan`) — §22 must consolidate them. |
| §31 notification policy | PARTIAL | Gating scattered across `watch.py`, `self_improvement_detect`, `delivery.send_alert` (opt-in, default OFF), `admin_supreme.telegram_notify_severity`. **Gap:** no single NotificationPolicy the emitters consult (dedup/cooldown/opt-in primitives already exist). |
| §83 strategic/weekly review | NET-NEW | Only the cadence constant `holding_cycle.CYCLE_INTERVALS["planning_90d"]`. Reuse `reports` builders + `kpi_history` (week-over-week). |
| §84 morning/arrival report | EXISTS (auto-on-open missing) | Celery beat `holding-morning-briefing` → `workers/holding_tasks.morning_briefing` + on-demand `GET /admin/holding/briefing`. **Gap:** auto-on-open trigger not wired (same owner-open event as §12). |
| §85 company deep dive | PARTIAL | `reports.company_portfolio(entity_id)` + `GET /admin/holding/entities/{id}`. **Gap:** registry dict only — no per-company live signals/proposals/deploy/health/goal-gap/timeline folded in. |

### DOMAIN D — Missions / Autonomy / Approval / Execution / Working-Now / Command Router

| § | Verdict | Reuse module (path) or gap |
|---|---------|----------------------------|
| §8 natural command router | PARTIAL | `capability/brain.py::CapabilityBrain.plan()` + `command.py::plan_and_execute()` + `POST /admin/capabilities/command` (fabric half); `holding/task_resolver.py` (deterministic holding half). **Gap:** no NL front-end feeds holding path; intent is coarse keyword; no DigitalTwin/Context injection; orb posts to *chat* endpoint not Brain. |
| §23 autonomy A0–A5 | EXISTS | `holding/plan.py::AutonomyClass` → certified `capability.manifest.ActionClass` (no parallel policy); `auto_eligible()` A0/A1; enforced in `autonomous_work.py` fail-closed (`BLOCKED_POLICY`/`BLOCKED_WORKER`). |
| §24 approval conversation | PARTIAL | `POST /proposals/{id}/approve\|reject` (records, executes nothing) + `capability/risk.evaluate_policy`→REQUIRE_APPROVAL (HTTP 202) + `owner_queue.OwnerAction` structured fields. **Gap:** no NL approval *dialog*; no casual-word guard; inline ACTION/TARGET/ENV/RISK/EVIDENCE/ROLLBACK/AUTHORITY turn not built. |
| §25 owner decision center | EXISTS | `owner_queue.prepare_owner_actions` (irreducible human step, dedup by source_key, rejects generic titles) + `briefing.today_for_you` (cap TODAY_MAX=7, NO_ACTION message) → `holding.html`. |
| §26 safe execution loop | EXISTS | `autonomous_work.run_cycle` (observe→normalize→reconcile→detect→plan→classify→execute→verify; `_verify` requires real evidence) + `holding_cycle.run_persistent_cycle` (CycleRecord, 3 brakes) + `executor.execute_approved`. Driven by `POST /admin/holding/run-cycle` (staging-only). |
| §27 mission system | NET-NEW | **No `Mission` class/status-enum anywhere.** `mission_id` is a passthrough string. Closest = `plan.py::PlanTask` (per-task, not aggregate). Must **wrap** PlanTask + proposals + worker_jobs + CycleRecord, not replace them. |
| §28 proactive missions | PARTIAL | Anti-flood behavior exists without the noun: `watch.diff` (one alert/change), `reconcile_plan`+`owner_queue` dedup by source_key. **Gap:** not expressed as "one active Mission per root problem" (needs §27). |
| §29 KAI working now | PARTIAL | `holding_view.py::kai_working` buckets from real WorkResults + `holding.html:150`. **Gap:** coarse bucket — missing started_at/progress/next-step/writes; populates only when persistent cycle runs live. |
| §30 background presence/scheduler | PARTIAL | Bounded observers: `watch.run_watch`, `briefing.run_morning_briefing`, `self_improvement_detect`, `status.cron_status`. **Gap:** no in-app scheduler driving the holding cycle — docstrings expect an external Railway cron not confirmed wired. `holding_cycle.py` deliberately builds no scheduler. |
| §90 Holding Command API | PARTIAL | Pattern exists in fabric: `admin_capabilities.InvokeBody` (server-derived `Principal` via `require_kai_ultra`, body role ignored) → typed `{utterance,input,mission_id}` → Brain (not NL-to-shell). **Gap:** on capabilities router not holding; envelope missing context/company/mode/client_caps; no `/admin/holding/command`. ⚠ **§90 spec tail is TRUNCATED.** |

### DOMAIN E — Capability Fabric / Workforce / Model-Routing / Eval / Dashboards / Evidence / Health / Finance / Customer / Security

| § | Verdict | Reuse module (path) or gap |
|---|---------|----------------------------|
| §3 target dashboard surfaces | PARTIAL | `frontend/admin/holding.html` renders ~16 of 26 surfaces. **Missing surfaces:** VISION/GESTURE, dedicated CAPABILITIES panel, CUSTOMER-SIGNALS, dedicated SYSTEM-HEALTH, SYSTEMS/OS-LAB, TIMELINE, EVIDENCE-drawer, command palette. |
| §33 self-improvement | EXISTS | `holding/self_improvement.py` (value-gate, prepare-only, reproducing-test, independent-review, never merges/deploys) + `_guardrails.py` (ceiling/one-per-root) + `_detect.py`/`_signals.py`. Flag `KAI_SELF_IMPROVEMENT_ENABLED`. |
| §34 eval harness | NET-NEW | Zero (task-success/FP-rate/TTR/regression/tool-selection). `internal_test.py` is a suite runner, not eval. Clone `security/risk_score.py` versioned-formula pattern. |
| §35 model routing | EXISTS (coding) / PARTIAL (general) | `capability/coding.py::CodingWorkerRouter` (fit-not-prestige, required_model no-silent-switch, no model gets approval authority). ⚠ Adjacent FreeLLMAPI gateway on `feat/kai-freellmapi` (istanbul, `3a9da00`) — **reconcile, don't rebuild.** Gap: no general chat-LLM provider router unified with the fabric. |
| §36 coding workforce | EXISTS | `capability/coding.py` (`CodingTask`, `certify_worker_result` no self-cert, `coding_action_class` fail-closed, `assign_worktrees` isolated). |
| §37 capability fabric pipeline | EXISTS | `capability/brain.py` (full REQUEST→…→PLAN, observable rationale) + `registry.py` (single registry) + `execution.py` (the ONE execution plane) + `risk.py`/`security.py`/`results.py`. |
| §38 capability dashboard | EXISTS | `routers/admin_capabilities.py` + `frontend/admin/kai-capabilities.html` + `kai-nexus-capabilities.js` + 126-cap catalog JSON. **Minor gap:** cost/last-used/env columns not all surfaced (data model supports them). |
| §45 finance | PARTIAL | `digital_twin.py` models revenue/customers as `fact()`→UNAVAILABLE unless source-backed; holding.html placeholder. **Gap:** no cash/runway/P&L display, no authoritative source wired, no finance surface. |
| §46 customer intelligence | PARTIAL | Same twin `customers_summary` Fact (UNAVAILABLE until CRM/billing). **Gap:** no leads/subs/support/churn model or surface. |
| §47 marketing/sales | NET-NEW | Only incidental strings. No analyze/recommend/draft/prepare engine, no approval-bound external-send gating. |
| §48 security center | EXISTS | `services/security/{evidence_bus,posture,risk_score,aikido_adapter}.py` + `routers/admin_security.py` (10 read-only `/admin/cyber/*`) + `cyber-operations.html` + `kai-nexus-security.js`. Defensive-only, flag `KAI_CYBER_OPS_ENABLED`, undeployed. |
| §53 command palette | PARTIAL | `kai-presence.js` Cmd/Ctrl+K→drawer + `window.KAI.ask()` + suggestion chips. **Gap:** not the §53 structured multi-action palette (Speak/Search/Run/Create mission/Open company/Show problem). |
| §56 HoldingSystemGraph | PARTIAL/NET-NEW | `capability/graph.py` (typed graph substrate) + `../kg/` + `kai-nexus-systems.js` (hardcoded 8-node topology). **Gap:** no dynamic holding graph over companies/apps/repos/services/vendors/deploys/missions from real registries. |
| §57 holding health score | PARTIAL/NET-NEW | `holding/signals.py::health_block` = trivial http 200/0 only. **Gap:** no versioned formula, no dimensions, no INSUFFICIENT_DATA. Clone `security/risk_score.py`. |
| §58 KAI confidence | PARTIAL | `registry.Confidence` (VERIFIED/UNVERIFIED = data-provenance). **Gap:** no evidence-quality HIGH/MEDIUM/LOW on problems/recs/actions. |
| §59 evidence drawer | PARTIAL | Evidence *data* exists (`security/evidence_bus.py`, proposal/mission `evidence_refs`, priorities `source`). **Gap:** no reusable frontend SHOW-EVIDENCE drawer. |
| §60 approval evidence package | EXISTS (self-improve) / PARTIAL (generic) | `self_improvement.owner_review_package` returns the §60 shape. **Gap:** not generalized to every approval type (finance/deploy/merge). |
| §61 holding timeline | PARTIAL/NET-NEW | Nexus timeline UI exists but data mostly DEMO-seeded (provenance DEMO) + real SSE layered on. **Gap:** no certified backend HoldingTimeline event store. |
| §70 visual language | EXISTS | Dark-premium mission-control across `holding.html`/`cyber-operations.html`/`kai-nexus.css` (Space Grotesk, navy/cyan). Original KAI identity, no JARVIS assets. |
| §71 accessibility | PARTIAL | `cyber-operations.html` + `kai-presence.{js,css}` solid (ARIA/focus/reduced-motion). **Gap:** `holding.html` has ZERO aria/role/reduced-motion — the main deployed dashboard fails a11y. |
| §72 performance/lazy-load | PARTIAL | Nexus code-split into 9 modules; panels fetch async. **Gap:** no explicit lazy-load of avatar/graphs/OS-lab, no measured core-fast-load. |
| §73 offline/degraded | EXISTS | `cyber-operations.html` + holding cyber card render NOT_CONNECTED/OFFLINE/DEGRADED via AbortController; no fake AI response. Strong honesty pattern. |
| §74 network failure | PARTIAL | AbortController timeouts + `idempotency_key` on invoke + proposal states. **Gap:** no explicit reconnect/backoff or replay-dedup for missions/approvals/commands. |
| §86 system deep dive | PARTIAL | Substrate (`CapabilityRegistry`, `CodingWorkerRouter`, `seed.py`, Nexus systems canvas) — no stale hardcode. **Gap:** no per-system "deep dive from real registries" view assembled as such. |

### DOMAIN F — Governance / OS-Lab / Resource / Continuous-Thinking / Session-Sec / Prompt-Injection / Multi-Agent-Review

| § | Verdict | Reuse module (path) or gap |
|---|---------|----------------------------|
| §39 Systems/OS Lab | NET-NEW | Zero code. Only capability-catalog *notes*. No governed-OS registry or categories. |
| §40 Ultron OS sandbox | NET-NEW | No `ultron` reference in any tree. |
| §41 OS supply-chain cert | PARTIAL | Pattern exists for *capabilities*: `capability/manifest.py` supply-chain record + `security/{aikido_adapter,posture,risk_score,evidence_bus}.py`. **Gap:** no OS-specific pipeline (pin-SHA→isolated build→QEMU→monitor) or NO_MALICIOUS_BEHAVIOR_DETECTED verdict vocab. |
| §42 virtme-ng | NET-NEW | No reference, all trees. |
| §43 syzkaller | NET-NEW | No reference, all trees. RESTRICTED_SECURITY_LAB — heavy operator authorization. |
| §44 Qubes/Genode principles | PARTIAL (applied, undocumented) | Principles live in code: `operator_session.ROLE_SCOPES` (least-authority), `capability/execution._ip_forbidden` (default-deny egress), worktree isolation, `kai_bridge` allowlist. **Gap:** no doc/module mapping them; names absent. |
| §75 session security | EXISTS | `core/operator_session.py` (immutable Principal, constant-time HMAC, fail-closed, `SCOPE_KAI_ULTRA` owner-only) + `operator_session_web.py` + `kai_bridge.py` (re-resolves at every entry). Voice/gesture carry no authority. |
| §76 prompt-injection defense | PARTIAL | Strong on external-data path: `capability/results.py` (`scan_for_injection`, NFKC fold, `sanitize_external_result`) + `invocation.py` + `aikido_adapter.py`; output side `reasoning_sanitizer.py`. **Gap:** chat/reasoning-context ingestion (README/logs/PR text via `nai_brain`/`twin` context builders) is NOT routed through `scan_for_injection`. |
| §77 proactive idea safety | PARTIAL | `proposals.py`/`proposals_store.py` + `governance.actions.audited(destructive=…)`. **Gap:** no per-idea classifier tagging money/prod/legal/security/cred/customer-comms/personnel with approval boundary. |
| §78 resource governance | PARTIAL | `router/spend_tracker.py` (daily/monthly USD caps) + `admin_chat._RATE_LIMIT_PER_MIN` + `capability/execution.rate_limit_per_min` + `coding.cost_budget` + `_guardrails` ceiling. **Gap:** no per-mission/provider/company dimension, no anomaly surface, no dashboard. ⚠ `core/budget_manager.py` is a NarAI ad controller — **false friend, do not extend.** |
| §79 automation priority | EXISTS | `holding_cycle.py` — wraps `run_cycle`, builds no new scheduler, bounded per-source, 0 work on no-change, 3 fail-closed brakes, no continuous LLM loop. **CRITICAL constraint honored.** |
| §80 continuous thinking | PARTIAL | Bounded observe→reconcile→plan→work→evidence cycle exists. **Gap:** the goals-vs-reality eval loop not assembled (needs §81/§82 + §34). |
| §87 self-explanation | PARTIAL | `self_model.py` + `priorities.py` (source-cited) + `grounding.py` (cited-or-refuse) + evidence refs. **Gap:** no unified "explain fact/priority/alternatives/uncertainty" endpoint. |
| §88 review/challenge mode | NET-NEW | No re-evaluate-with-separate-reviewer over reasoning/recs. `certify_worker_result` is code-change-only. |
| §89 multi-agent review | PARTIAL | One certified seam: `capability/coding.certify_worker_result` (reviewer≠worker, enforced in `a2_framework.prepare`/`a2_dispatch`). **Gap:** not the §89 panel (planner/domain-expert/security-reviewer/verifier) — extend the seam, don't fork. |

**Honest headline:** of 91 items, roughly **~15 EXISTS**, **~50 PARTIAL** (substrate present, real gap), **~24 NET-NEW**, **1 SATISFIED**. The mission's center of mass is **PARTIAL** — extend-in-place with strict reuse, not greenfield.

---

## 3. BASE BRANCH + INTEGRATION STRATEGY

### The key structural finding (from the inventories)
The `cyberops` tree (`feat/kai-cyber-operations`) is **already the superset integration branch**. Domains B, D, E, F all independently confirmed:
- The **autonomous-operator core** (`holding/digital_twin.py`, `self_model.py`, `plan.py`, `autonomous_work.py`, `holding_cycle.py`) is **byte-identical** in cyberops and `feat/kai-exec-appb-integration`.
- The **capability fabric** (`services/capability/*`, 126-cap catalog) is **byte-identical in all three trees, including cyberops** — it is NOT stranded on `feat/kai-capability-fabric`.
- cyberops also carries presence (`kai-presence.js`), Nexus, the App A↔App B bridge (`kai_bridge.py`), and Cyber Ops Phase A (`services/security/*`, `admin_security.py`).

So the exec-integration and fabric branches are effectively **already merged into cyberops**. Only two lines are NOT reconciled into it:
1. **`feat/kai-freellmapi`** (the CURRENT istanbul worktree, `3a9da00`) — the FreeLLMAPI optional model-provider gateway. This is the §35 general-model-routing piece. Domain E flags it must be **reconciled with `capability/coding.py`, not rebuilt**.
2. **`feat/kai-nexus`** — the cinematic avatar/voice. Domain A found the embodiment suite (driver/viseme/GLB) is already in cyberops and served but dormant; the *rigged `.glb` asset* is the missing external input, not the code.

### Recommendation: **extend `feat/kai-cyber-operations` as the single base branch.**

Rationale:
- It is the widest superset already — starting anywhere else means re-doing merges the inventories prove are done.
- A fresh unified branch would **re-introduce the exact duplication traps** the inventories warn about (3 priority rankers, 4 TTS paths, 2 Nexus views, twin-of-operator vs holding-twin name collision, `budget_manager` false friend). Building on cyberops keeps those reuse anchors in one place.
- Prod (`4fbfb8e`) is a **read-only subset** of cyberops (autonomy/fabric/cyber all dark or absent in prod). cyberops is ahead, not divergent.

Two mandatory reconciliation steps before Phase 1 (these become Phase 0):
1. **Rebase/verify cyberops against prod `4fbfb8e`** to confirm no prod drift and that the certified read-only floor is preserved.
2. **Merge `feat/kai-freellmapi` into cyberops** and reconcile it with `capability/coding.py` (one model-routing authority, not two). Defer `feat/kai-nexus` avatar assets to Phase 7 (blocked on the missing rigged `.glb` anyway).

**LIVE-in-prod vs dormant-on-branch:** LIVE = read-only Holding OS dashboard, presence orb+drawer, Nexus view, bridge, deployment-truth registry (all at `4fbfb8e`, MONEY_MODE=MOCK). Dormant-on-cyberops-behind-flags = autonomous operator, capability fabric execution, self-improvement, A2, cyber-ops center. Nothing that grants authority is enabled anywhere.

---

## 4. PHASED BUILD PLAN

Each phase is a coherent shippable unit with its own **verify + independent-review gate** (§0 #11 no self-approve → use `code-reviewer`/`verifier` in a separate lane; §89 reviewer≠author). All new autonomy/execution ships **dark** (§0 #12). All computation stays **event-driven/bounded** (§79 — no infinite LLM loops). Every material claim gets provenance (§0 #16). Dashboard reflects real state at every phase (§0 #15).

Highest-leverage reconcile-and-unify first; gesture/avatar-embodiment/OS-lab last.

### Phase 0 — Branch reconciliation & baseline re-certification `[foundational]`
Rebase/verify cyberops vs prod `4fbfb8e`; merge + reconcile `feat/kai-freellmapi` model gateway into `capability/coding.py` (§35); confirm all authority flags dark and prod behavior unchanged.
**Verify:** full suite green; dashboard-truth reconciled; zero prod behavior change; no second model router introduced.

### Phase 1 — Self-model + twin + knowledge unification (Domain B core) `[high leverage, read-only]`
§1/§62/§63 (extend `self_model.py`/`holding_view.py`/`holding.html`; render limitations, live-derive some); §16 (add `confidence`+`evidence_ref` to `digital_twin.fact()`); §14 hierarchy edges; §15 SystemKnowledgeIndex as a compose-layer over existing sources + `../kg/`. Grounds everything downstream; low risk (read-only).
**Verify:** self-cert test asserts full §62 field set renders + `claims_consciousness=False`; knowledge index answers a dependency question with cited evidence.

### Phase 2 — Attention + Goals + Gap + Holding memory `[NET-NEW, assembled from live sources]`
§17 CurrentAttentionModel (from `what_am_i_doing`+`portfolio_view`+`plan`+`owner_queue`); §81 HoldingGoalRegistry (hang off `registry` entities, reuse `../planning/` storage/approval pattern — distinct from work-goals); §82 gap analysis (reuse `priorities`/`reconcile_plan` style); §32 holding-scoped typed memory (reuse pgvector + `proposals_store`, add provenance-required write-path).
**Verify:** goal registry rejects invented targets (no source → UNAVAILABLE); attention model is bounded (not hidden CoT); memory write refuses silent LLM→fact.

### Phase 3 — Proactive / Problem / Opportunity / Idea / Prioritization unification (Domain C) `[consolidation, high leverage]`
§18 unify the two problem streams into `HoldingProblem` + wire the 5 missing sources; §22 make `derive_priorities` the single ladder, route the other 2 rankers through it (kill duplicates); §20 OpportunityEngine (reuse Candidate shape); §21 Idea mode on `proposals_store` (extend, don't fork); §19 add multi-option + cost; §31 single NotificationPolicy over `delivery.py`; §11 unified ProactiveBriefingEngine; §83 weekly review; §85 richer company deep-dive; §12/§84 last-visit store + arrival trigger; §55 cross-company shared-issue detector (extends §18).
**Verify:** no 4th ranker/detector/queue/sender introduced; rejected ideas don't reappear without new evidence; notifications fire only on the 7 allowed reasons.

### Phase 4 — Mission system + working-now + scheduler (Domain D) `[the one genuine NET-NEW aggregate]`
§27 Mission entity that **wraps** PlanTask+proposals+worker_jobs+CycleRecord (never replaces); §28 one-active-mission-per-root-problem flood control; §29 enrich `kai_working` (started_at/progress/next/writes); §30 wire the bounded holding cycle to the EXISTING celery-beat/Railway cron (no new daemons — §79).
**Verify:** mission lifecycle PROPOSED..COMPLETE/FAILED; §26 loop never marks success on generated-code-alone; scheduler yields 0 work on no-change cycle.

### Phase 5 — Holding Command API + NL router + approval conversation + palette `[integration, needs §90 tail]`
§90 typed `/admin/holding/command` (context/company/mission/mode/client_caps; server-derived principal via `require_kai_ultra`) over existing Brain + `task_resolver` + `CapabilityExecutionService`; §8 wire presence NL input (currently → chat) to the router + add DigitalTwin/Context injection; §24 NL approval dialog + casual-word guard + inline consequential-action turn; §53 structured command palette; §54 global conversation context; §76 gap-fill — route chat-context ingestion through existing `scan_for_injection`.
**⚠ Blocked/underspecified by the TRUNCATED §90 tail — request the missing spec before finalizing the envelope.**
**Verify:** command API is typed not NL-to-shell; body role is ignored (server derives authority); no ambiguous word authorizes high-impact; injection scan covers the chat path.

### Phase 6 — Dashboard surfaces + evidence/health/graph/timeline + UX `[breadth]`
§3 missing surfaces; §56 dynamic HoldingSystemGraph (typed layer over registries, reuse `capability/graph.py` primitives); §57 versioned health score (clone `security/risk_score.py`); §58 evidence-quality confidence; §59 reusable evidence drawer; §60 generalize `owner_review_package` to all approval types; §61 certified HoldingTimeline event store feeding the existing Nexus UI; §70/§71 (fix `holding.html` a11y)/§72/§73/§74.
**Finance/customer (§45/§46) and marketing (§47) are gated on operator data provisioning** — build the surfaces to render UNAVAILABLE honestly until authoritative sources (Stripe/CRM/billing) are wired; money stays MOCK.
**Verify:** health score shows formula+version+INSUFFICIENT_DATA; no DEMO-as-REAL; a11y audit passes on holding.html; degraded/offline render without fake AI.

### Phase 7 — Voice command center + digital human wiring (Domain A integration) `[needs operator privacy choice]`
§7 assemble VoiceSessionManager from the certified-but-dormant adapters; §6 privacy modes (**operator chooses default — spec recommends PUSH_TO_TALK**) + visible mic/recording indicators + mute; §10/§49 wire the avatar driver/viseme/GLB suite into a live surface (video-swap works now; rigged `.glb` still an external blocker); §50/§51/§52 personality/summary-first/spoken-stop; §66 arrival trigger; §67 settings; §68 quiet mode; §69 consolidate the two Nexus views; §64 never-fake enforced.
**Reuse only** — do not add a 3rd voice-pick or a 4th TTS path; `kai-barge-in.js` is the one cancellation authority.
**Verify:** no covert mic (wake_word_listener stays disabled here); presence carries no authority (§75); barge-in single-path.

### Phase 8 — Gesture (§9) `[NET-NEW, needs camera authorization]`
Small vocabulary + visible camera indicator + local inference + hard enforcement that gestures NEVER authorize financial/prod/merge/cred/destructive. **Requires operator camera-privacy authorization.** Optional/deferrable.
**Verify:** a gesture cannot reach any authority path; camera indicator always visible; no face-rec/biometric.

### Phase 9 — Governance maturation: eval / challenge / review-panel / resource governor / self-explanation / continuous-thinking `[deepening]`
§34 eval harness (clone `risk_score.py` formula, consume `audit_log`/`worker_jobs`/`cycle_store`); §88 challenge mode; §89 multi-agent review panel (extend `certify_worker_result` seam — planner/domain-expert/security-reviewer/verifier); §78 unified resource governor (compose `spend_tracker`+rate-limiter+ceiling+cost_budget; **ignore `budget_manager.py`**); §87 self-explanation endpoint; §80 assemble the bounded goals-vs-reality loop; §44 document the applied compartmentalization principles.
**Verify:** eval is deterministic + versioned; no self-approval in the panel; governor is bounded (no unlimited tokens/CPU/browser); §79 honored (no continuous loop).

### Phase 10 — Systems/OS Lab (§39–44) `[heaviest, NET-NEW, RESTRICTED — needs operator sign-off]`
Governed OS-collection registry + categories; §40 Ultron as EDUCATIONAL_OS_SANDBOX (isolated QEMU, production=NO); §41 OS supply-chain cert pipeline (reuse the capability supply-chain/verdict pattern); §42 virtme-ng / §43 syzkaller as RESTRICTED_SECURITY_LAB (default OFF, prod DISABLED). **Requires explicit operator authorization + isolated infra; recommend descoping or deferring until the rest of the OS is certified.**
**Verify:** never claim MALWARE_FREE (use NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE/UNVERIFIED); nothing auto-selected into prod.

**Continuous (not a phase):** §0 principles, §75 session security, §76 injection defense are enforced at every phase's review gate.

**Phases needing the truncated §90+ tail or operator input:** Phase 5 (§90 tail), Phase 6 (finance/customer data provisioning), Phase 7 (voice privacy default), Phase 8 (camera authorization), Phase 10 (OS-lab authorization).

---

## 5. RISKS + OPEN QUESTIONS FOR THE OPERATOR

1. **Truncated spec tail (BLOCKER for Phase 5).** The source message cut at ~§90; the §90 Holding Command API tail and any §91+ are missing. Please supply the remainder before the command-API envelope is finalized.
2. **Voice/gesture privacy default (§6/§9).** Spec recommends **PUSH_TO_TALK** as the privacy-preserving default and forbids a covert continuous mic. Confirm PTT as default, and confirm whether gesture/camera (§9, Phase 8) is authorized at all — it needs explicit camera-privacy sign-off. Note `core/wake_word_listener.py` is a covert always-on NarAI mic that must stay disabled in this context.
3. **OS-Lab authorization (§39–44, Phase 10).** This cluster is entirely NET-NEW, heavy, and partly RESTRICTED_SECURITY_LAB (syzkaller, Ultron, virtme-ng). It needs explicit authorization + isolated infra + a supply-chain cert pipeline. Recommendation: **descope or defer** until the core OS is certified; confirm whether it's in scope for this program at all.
4. **Base branch decision.** Recommendation is to **extend `feat/kai-cyber-operations`** (already the superset of exec-integration + fabric + holding + presence + cyber) rather than open a fresh unified branch — a fresh branch re-introduces the duplication traps the inventories flag. Requires reconciling `feat/kai-freellmapi` (model gateway) and `feat/kai-nexus` (avatar assets) into it. Confirm.
5. **Finance/customer data provisioning (§45/§46, Phase 6).** The twin honestly returns UNAVAILABLE until authoritative sources are wired. To display cash/revenue/runway/customers/churn, the operator must provision + authorize the sources (Stripe/CRM/billing). Money stays **MOCK** until an explicit decision. Which sources, and when?
6. **No isolated staging environment.** Per MEMORY this is a recurring blocker. Every "enable authority" step (autonomy A2+, execution, real money) is gated on hosted-edge certification that has no staging to run in. Enabling anything beyond read-only requires the operator to stand up isolated staging first.
7. **Missing rigged `.glb` avatar asset (§10/§49).** The embodiment code is built + served + tested but the facial/viseme renderer is EXTERNAL_BLOCKED on a rigged `.glb` that doesn't exist. Video-swap works meanwhile. Provide/commission the asset, or accept video-only for Phase 7.
8. **Duplication traps.** The inventories flag concrete collisions that WILL recur if phases don't respect the reuse maps: 3 priority rankers, 4 TTS paths, 2 Nexus immersive views, the twin-of-operator (`admin_twin.py`) vs holding-twin name collision, the `../planning/` work-goal vs §81 business-goal overload, and `core/budget_manager.py` (NarAI ads) as a false friend for §78. Consolidation is the work, not addition.
9. **§54/§55 coverage gap.** Neither §54 (global conversation context) nor §55 (multi-company shared-issue reasoning) was covered by any of the six domain inventories. They are classified provisionally here (PARTIAL / NET-NEW respectively) from adjacent evidence and should get a dedicated inspection before their phases (5 and 3).
10. **Deployment ≠ authority (§0 #12) holds the whole program.** Everything ships dark. Confirm the operator understands that "built + deployed" will repeatedly NOT mean "live/enabled" — enabling authority is a separate, explicit, staged, operator-gated act.
