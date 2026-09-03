# KAI OMNIPRESENT HOLDING COMMAND OS — Requirements Ledger (§161)

> Mandated by spec §161: one row for **every** section §0–§166, no silent omission.
> Status is derived from the baseline gap matrix (`docs/KAI_OMNIPRESENCE_BASELINE.md`, §0–§90)
> and the spec index (`omnipresence_spec_index.md`, §0–§166). This is a **living** ledger —
> statuses advance as phases land and evidence is collected (see `KAI_OMNIPRESENCE_EVIDENCE_MATRIX.md`).
>
> **Derivation rule:** baseline EXISTS→IN_PROGRESS (module cited; PASS only if tested+certified this
> session) · PARTIAL→IN_PROGRESS (gap in notes) · NET-NEW→NOT_STARTED · SATISFIED→PASS.
> §91–166 (absent from the gap matrix) classified from the spec index + baseline reuse anchors.

## Status vocab
`NOT_STARTED` · `IN_PROGRESS` · `PASS` (tested + adversarially-reviewed + certified this session) ·
`BLOCKED` (genuine external gate) · `REJECTED` · `N/A`

## Summary (167 sections, §0–§166)
| status | count | |
|--------|-------|--|
| PASS | 2 | §2 release, §48 security center |
| IN_PROGRESS | 119 | substrate exists, extend-in-place |
| NOT_STARTED | 30 | NET-NEW, nothing to reuse yet |
| BLOCKED | 15 | §90 tail · gesture/camera (§9,93,94,130,136) · OS-lab (§39–43,115–117) · final cert (§159) |
| N/A | 1 | §160 execution directive |
| REJECTED | 0 | — |

**BLOCKED gate legend:** `[G:SPEC90]` §90 tail truncated · `[G:CAM]` operator camera/gesture authorization (Phase 8) ·
`[G:OSLAB]` operator OS-lab authorization + isolated infra (Phase 10) · `[G:STAGING]` no isolated staging env exists (hosted-edge cert).

---

## Ledger — §0 through §166

| § | title (short) | status | impl_ref | test_ref | runtime_evidence | notes |
|---|---------------|--------|----------|----------|------------------|-------|
| 0 | Permanent principles | IN_PROGRESS | `a2_framework.py`(FORBIDDEN_A2/_AUTHORITY_IMMUTABLE), `coding.certify_worker_result`, `holding_cycle.py`(3 brakes), `kai_bridge._STRIP_REQUEST`, `results.Provenance` | — | — | #11/#12/#16/#9 enforced-in-code; #1/#2/#3/#8 are process norms w/ no code enforcer. Continuous review gate, not a phase. |
| 1 | OperationalSelfModel + 10 submodels | IN_PROGRESS | `holding/self_model.py`, `digital_twin.py`, `capability/graph.py` | — | — | RuntimeIdentity/ConstraintRegistry/SystemHealthModel/EvidenceStore partial; MissionMemory/CurrentAttention/GoalRegistry NET-NEW. |
| 2 | Current release state | **PASS** | Holding OS dashboard + `kai-presence.js` + Nexus + `kai_bridge.py` + deployment-truth registry | full suite green | PR #67 @ `4fbfb8e`, BOTH prod services, Playwright 4-viewport cert this session; authority OFF/MOCK/IN_SYNC | Certified read-only floor. See baseline §1. |
| 3 | Target dashboard surfaces | IN_PROGRESS | `frontend/admin/holding.html` (~16/26 surfaces) | — | — | Missing: VISION/GESTURE, CAPABILITIES panel, CUSTOMER-SIGNALS, SYSTEM-HEALTH, OS-LAB, TIMELINE, EVIDENCE drawer, command palette. |
| 4 | KaiPresenceState | IN_PROGRESS | `kai-presence.js`(6-state), `kai-nexus-embodiment.js`(14-state) | — | — | No persistent **backend** state w/ full §4 field set; frontend-only, ephemeral. |
| 5 | Always present | IN_PROGRESS | `core/api.py::_inject_kai_presence()`, Cmd/Ctrl+K | — | live on all `/admin/*` (prod) | Mobile-compact / push-to-talk absent. |
| 6 | Always-listen privacy | IN_PROGRESS | `kai-speech-input.js`(honest, no covert loop) | — | — | 4 privacy modes + mic/recording indicators + mute NET-NEW. ⚠ `core/wake_word_listener.py` covert mic must stay disabled. |
| 7 | Voice command center | IN_PROGRESS | `kai-speech-input.js`, `kai-tts-provider.js`, `kai-barge-in.js`, `core/voice_router.py` | — | — | Adapters certified but never assembled into a live VoiceSessionManager loop — parts bin. |
| 8 | Natural command router | IN_PROGRESS | `capability/brain.py::plan()`, `command.py`, `holding/task_resolver.py` | — | — | No NL front-end feeds holding path; intent coarse keyword; orb posts to *chat* not Brain; no twin/context injection. |
| 9 | Gesture | BLOCKED `[G:CAM]` | — (only session/scope model enforces "never authorizes") | — | — | NET-NEW; needs operator camera-privacy authorization (Phase 8, optional/deferrable). |
| 10 | Avatar | IN_PROGRESS | `kai-avatar-driver.js`, viseme engine/mapper/morph-registry, `kai-glb-renderer.js`, `kai-avatar-lab.html` | built+served+tested | video-swap live (`nexus-assets/`) | GLB honestly ASSET_UNAVAILABLE (no rigged `.glb`); driver suite not `<script>`-included on any live page. |
| 11 | ProactiveBriefingEngine | IN_PROGRESS | `holding/watch.py`, `self_improvement_detect.run_detection` | — | — | No unified engine w/ full trigger taxonomy (dashboard-open/mission-complete/approval/deadline/opportunity missing). |
| 12 | Arrival brief | NOT_STARTED | (stub) `briefing.today_for_you()` key only | — | — | Nothing computes "since last visit"; depends on §66 arrival event + last-visit store. |
| 13 | DailyHoldingBrief | IN_PROGRESS | `reports.build_morning_briefing()`, `briefing.run_morning_briefing()` | — | powers dashboard + spoken | Missions/opportunities/recommendations sub-sections absent; revenue/customers REQUIRES_OPERATOR_CONFIRMATION. |
| 14 | HoldingDigitalTwin | IN_PROGRESS | `holding/digital_twin.py`(dynamic discovery, SOURCE_MAP, portfolio_view), `holding/registry.py`(11 entities) | — | — | parent→child implicit `products[]` not edges; plan fields UNAVAILABLE placeholders. |
| 15 | SystemKnowledgeIndex | IN_PROGRESS | `repo_inspect.py`, `tech_doc_lookup.py`, `log_inspect.py`, `deployment_status.py`, `registry.py`, `../kg/` | — | — | No unifying query layer answering arch/dependency/change questions w/ evidence. |
| 16 | Knowledge freshness | IN_PROGRESS | `digital_twin.fact()`/`_freshness()`, `registry.Confidence` | — | — | Fact dict has no per-fact `confidence` or `evidence_ref` (~4/6 spec fields missing). |
| 17 | CurrentAttentionModel | NOT_STARTED | (assemble from) `what_am_i_doing()`, `portfolio_view().needs_attention`, `plan.py`, `owner_queue` | — | — | Nothing built. Must be bounded (not hidden CoT). |
| 18 | Problem detection | IN_PROGRESS | `priorities.derive_priorities()`, `self_improvement_detect.Candidate` | — | — | No unified `HoldingProblem` type; deploy-drift/mission-fails/security/doc-inaccuracy/stale-plans not wired. |
| 19 | Solution engine | IN_PROGRESS | `proposals._template()`, `SelfImprovementEngine.owner_review_package()` | — | — | One templated action not multiple **options**; no **cost** estimate. |
| 20 | OpportunityEngine | NOT_STARTED | (reuse) Candidate/evidence+confidence shape from `self_improvement_detect` | — | — | Only empty `digital_twin.opportunities` field exists. |
| 21 | Idea mode | NOT_STARTED | (extend) `proposals_store.py` state machine + 24h dedup + `resolve_absent` | — | — | Strong reuse base; extend the table, do not fork. |
| 22 | Prioritization | IN_PROGRESS | `priorities.derive_priorities()` (deterministic, source-cited) | — | — | Flat 4-level severity, not the §22 ordered ladder. ⚠ 3 rankers exist — must consolidate. |
| 23 | Autonomy A0–A5 | IN_PROGRESS | `holding/plan.py::AutonomyClass`→`capability.manifest.ActionClass`, `autonomous_work.py`(fail-closed) | — | flags dark in prod | Code exists; live A2+ enablement is `[G:STAGING]`-gated (separate authority act). |
| 24 | Approval conversation | IN_PROGRESS | `/proposals/{id}/approve|reject`, `capability/risk.evaluate_policy`→REQUIRE_APPROVAL, `owner_queue.OwnerAction` | — | — | No NL approval dialog; no casual-word guard; inline ACTION/TARGET/ENV/RISK/EVIDENCE/ROLLBACK/AUTHORITY turn absent. |
| 25 | Owner decision center | IN_PROGRESS | `owner_queue.prepare_owner_actions`, `briefing.today_for_you`(TODAY_MAX=7) | — | renders `holding.html` | Solid EXISTS; extend as decision surfaces grow. |
| 26 | Safe execution loop | IN_PROGRESS | `autonomous_work.run_cycle`, `holding_cycle.run_persistent_cycle`(3 brakes), `executor.execute_approved` | — | — | `_verify` requires real evidence (never success-on-code-alone). Live run `[G:STAGING]`-gated. |
| 27 | Mission system | NOT_STARTED | (wrap) `plan.py::PlanTask` + proposals + worker_jobs + CycleRecord | — | — | No `Mission` class/status-enum; `mission_id` is a passthrough string. The one genuine NET-NEW aggregate. |
| 28 | Proactive missions | IN_PROGRESS | `watch.diff`(one alert/change), `reconcile_plan`+`owner_queue` dedup | — | — | Anti-flood behavior w/o the noun; needs §27 for "one active mission per root problem". |
| 29 | KAI working now | IN_PROGRESS | `holding_view.py::kai_working`, `holding.html:150` | — | — | Coarse bucket — missing started_at/progress/next-step/writes; populates only when persistent cycle runs. |
| 30 | Background presence/scheduler | IN_PROGRESS | `watch.run_watch`, `briefing.run_morning_briefing`, `self_improvement_detect`, `status.cron_status` | — | — | No in-app scheduler; wire the bounded cycle to EXISTING celery-beat/Railway cron (§79 — no new daemons). |
| 31 | Notification policy | IN_PROGRESS | `watch.py`, `self_improvement_detect`, `delivery.send_alert`(opt-in default OFF), `admin_supreme.telegram_notify_severity` | — | — | No single NotificationPolicy the emitters consult (dedup/cooldown/opt-in primitives exist). |
| 32 | Memory | IN_PROGRESS | `../memory/store.py`(pgvector, user-scoped), `../kg/`, `../learning/`, `proposals_store.py` | — | — | Wrong scope — no holding-scoped typed memory (7 categories) w/ mandatory-provenance write-path. Reuse infra, add scope. |
| 33 | Self-improvement | IN_PROGRESS | `holding/self_improvement.py`(prepare-only, reproducing-test, independent-review, never merges/deploys), `_guardrails.py` | — | flag `KAI_SELF_IMPROVEMENT_ENABLED` dark | Strong EXISTS. |
| 34 | Eval harness | NOT_STARTED | (clone) `security/risk_score.py` versioned-formula pattern | — | — | `internal_test.py` is a suite runner, not eval. task-success/FP-rate/TTR/regression/tool-selection. |
| 35 | Model routing | IN_PROGRESS | `capability/coding.py::CodingWorkerRouter`(fit-not-prestige, no-silent-switch) | — | — | ⚠ reconcile `feat/kai-freellmapi` gateway into `coding.py` (one authority). No general chat-LLM router yet. |
| 36 | Coding workforce | IN_PROGRESS | `capability/coding.py`(CodingTask, certify_worker_result, assign_worktrees) | — | — | Strong EXISTS; no self-cert, fail-closed action class, isolated worktrees. |
| 37 | Capability fabric pipeline | IN_PROGRESS | `capability/brain.py`, `registry.py`, `execution.py`(the ONE plane), `risk.py`/`security.py`/`results.py` | — | — | Full REQUEST→PLAN w/ observable rationale. Byte-identical across all 3 trees. |
| 38 | Capability dashboard | IN_PROGRESS | `routers/admin_capabilities.py`, `kai-capabilities.html`, 126-cap catalog JSON | — | — | Minor gap: cost/last-used/env columns not all surfaced (data model supports them). |
| 39 | Systems/OS Lab | BLOCKED `[G:OSLAB]` | — (capability-catalog notes only) | — | — | NET-NEW; needs operator authorization + isolated infra. Recommend descope/defer. |
| 40 | Ultron OS sandbox | BLOCKED `[G:OSLAB]` | — | — | — | NET-NEW, RESTRICTED; EDUCATIONAL_OS_SANDBOX only, production=NO. |
| 41 | OS supply-chain cert | BLOCKED `[G:OSLAB]` | (pattern) `capability/manifest.py`, `security/{aikido_adapter,posture,risk_score,evidence_bus}.py` | — | — | Capability-supply-chain pattern exists; OS-specific pipeline (pin-SHA→QEMU→monitor) + verdict vocab NET-NEW + authorization-gated. |
| 42 | virtme-ng | BLOCKED `[G:OSLAB]` | — | — | — | NET-NEW, RESTRICTED_KERNEL_TEST; default OFF, prod DISABLED. |
| 43 | syzkaller | BLOCKED `[G:OSLAB]` | — | — | — | NET-NEW, RESTRICTED_SECURITY_LAB; heavy operator authorization, isolated disposable VM only. |
| 44 | Qubes/Genode principles | IN_PROGRESS | `operator_session.ROLE_SCOPES`, `execution._ip_forbidden`(default-deny egress), worktree isolation, `kai_bridge` allowlist | — | — | Principles applied in code but undocumented; gap is a doc/module mapping them (not gated). |
| 45 | Finance | IN_PROGRESS | `digital_twin.py` revenue/customers `fact()`→UNAVAILABLE, `holding.html` placeholder | — | — | No cash/runway/P&L surface. Real data gated on operator provisioning (Stripe/billing); money stays MOCK. Build surface to render UNAVAILABLE honestly. |
| 46 | Customer intelligence | IN_PROGRESS | twin `customers_summary` Fact→UNAVAILABLE | — | — | No leads/subs/support/churn model. Gated on CRM/billing provisioning. |
| 47 | Marketing/sales | NOT_STARTED | — (incidental strings only) | — | — | No analyze/recommend/draft/prepare engine; external-send approval-gating NET-NEW. |
| 48 | Security center | **PASS** | `services/security/{evidence_bus,posture,risk_score,aikido_adapter}.py`, `routers/admin_security.py`(10 read-only), `cyber-operations.html` | 44/44 unit | 6-lens adversarial review-triad this session | Defensive-only, flag `KAI_CYBER_OPS_ENABLED`. Certified-but-**undeployed** (see evidence matrix). |
| 49 | Digital human | IN_PROGRESS | `kai-nexus-embodiment.js`(state→video/halo/subtitle/voice), `kai-subtitles.js`, TTS, barge-in | — | — | Facial/viseme EXTERNAL_BLOCKED on rigged asset; modules not wired to a live surface. |
| 50 | Voice personality | IN_PROGRESS | `kai-presence.js::_pickVoice`, `kai-tts-provider.js::scoreVoice` | — | — | No calm/concise/executive personality layer; TTS rate/pitch hardcoded. |
| 51 | Speech length | IN_PROGRESS | `speak()`(truncate 700), subtitle 240 | — | — | No summary-first-voice/depth-on-dashboard split; no show-details/explain-more affordance. |
| 52 | Interruptions | IN_PROGRESS | `kai-barge-in.js`(one cancellation path), `kai-presence.js`(stopStream/stopSpeak, Stop btn) | — | — | Spoken "stop" needs mic (dormant). Single-path — do not fork. |
| 53 | Command palette | IN_PROGRESS | `kai-presence.js` Cmd/Ctrl+K + `window.KAI.ask()` + chips | — | — | Not the §53 structured multi-action palette (Speak/Search/Run/Create-mission/Open-company/Show-problem). |
| 54 | Global context | IN_PROGRESS | `kai-presence.js`(conversationId + context) | — | P13 Nexus continues conversation drawer→nexus | "this" resolving to selected item w/ evidence across navigation unproven. ⚠ not covered by any inventory — inspect before Phase 5. |
| 55 | Multi-company reasoning | NOT_STARTED | (grounded in) `registry.all_entities()` + `portfolio_view()` | — | — | No shared-issue detector (infra/vendor/dup-caps/funnel/defect/cred). Extends §18 across companies. ⚠ not covered by any inventory. |
| 56 | HoldingSystemGraph | IN_PROGRESS | `capability/graph.py`(typed substrate), `../kg/`, `kai-nexus-systems.js`(hardcoded 8-node) | — | — | No dynamic holding graph over companies/apps/repos/services/vendors/deploys/missions from real registries. |
| 57 | Holding health score | IN_PROGRESS | `holding/signals.py::health_block`(http 200/0 only) | — | — | No versioned formula, no dimensions, no INSUFFICIENT_DATA. Clone `security/risk_score.py`. |
| 58 | KAI confidence | IN_PROGRESS | `registry.Confidence`(VERIFIED/UNVERIFIED, data-provenance) | — | — | No evidence-quality HIGH/MEDIUM/LOW on problems/recs/actions. |
| 59 | Evidence drawer | IN_PROGRESS | `security/evidence_bus.py`, proposal/mission `evidence_refs`, priorities `source` | — | — | Evidence *data* exists; no reusable frontend SHOW-EVIDENCE drawer. |
| 60 | Approval evidence package | IN_PROGRESS | `self_improvement.owner_review_package`(returns §60 shape) | — | — | Not generalized to every approval type (finance/deploy/merge). |
| 61 | Holding timeline | IN_PROGRESS | Nexus timeline UI (DEMO-seeded + real SSE) | — | — | No certified backend HoldingTimeline event store; DEMO tagged as DEMO (honest). |
| 62 | KAI own-status panel | IN_PROGRESS | `self_model.snapshot()/describe()/what_am_i_doing()`, `holding_view.py`, `holding.html:195` | — | `claims_consciousness=False` asserted | Panel omits prod/staging SHA split, model, latency, attention, autonomy-class, limitations, last-verified. |
| 63 | Limitations | IN_PROGRESS | `self_model._KNOWN_LIMITATIONS`(4 concrete) | — | — | Dropped from `holding_view` (not rendered); static hardcoded, not live-derived. |
| 64 | Never fake presence | IN_PROGRESS | state transitions driven by real SSE; `kai-nexus.js` DEMO is `?scenario=`-only w/ banner; provenance tagged | — | — | Strong honesty anchor; enforce at every presence phase gate. |
| 65 | Failure communication | IN_PROGRESS | `grounding.py`(cited-or-refuse), `cyber-operations.html` NOT_CONNECTED/OFFLINE/DEGRADED, `self_model` limitations | — | — | Not in gap matrix. Honesty patterns exist; no unified failure-communication contract across all surfaces. |
| 66 | Owner arrival | IN_PROGRESS | `/admin/session/whoami`(session activation, not facial-id), `briefing.kai_completed_since_last_visit` | — | — | No arrival trigger loading brief + comparing last visit on dashboard-open. |
| 67 | Presence settings | NOT_STARTED | — | — | — | No settings model/UI (greeting/voice/PTT/wake-word/gesture/camera/quiet-hours/severity). |
| 68 | Quiet mode | NOT_STARTED | — | — | — | No quiet-mode state/logic. |
| 69 | Fullscreen command mode | IN_PROGRESS | `/admin/nexus`(`nexus.html`), `/admin/mission-nexus`(`kai-nexus.js`, 1660 ln) | — | live | ⚠ TWO immersive views — §69 must consolidate onto one. |
| 70 | Visual language | IN_PROGRESS | `holding.html`, `cyber-operations.html`, `kai-nexus.css`(Space Grotesk, navy/cyan) | — | honesty/visual pattern (part of §2 cert) | Original KAI identity, no JARVIS assets. |
| 71 | Accessibility | IN_PROGRESS | `cyber-operations.html` + `kai-presence.{js,css}`(ARIA/focus/reduced-motion) | — | — | ⚠ `holding.html` has ZERO aria/role/reduced-motion — main deployed dashboard fails a11y. |
| 72 | Performance/lazy-load | IN_PROGRESS | Nexus code-split (9 modules), async panel fetch | — | — | No explicit lazy-load of avatar/graphs/OS-lab; no measured core-fast-load. |
| 73 | Offline/degraded | IN_PROGRESS | `cyber-operations.html` + holding cyber card (AbortController, NOT_CONNECTED/OFFLINE/DEGRADED) | — | honesty pattern (no fake AI on disconnect) | Strong honesty anchor; formal degraded cert pending. |
| 74 | Network failure | IN_PROGRESS | AbortController timeouts, `idempotency_key` on invoke, proposal states | — | — | No explicit reconnect/backoff or replay-dedup for missions/approvals/commands. |
| 75 | Session security | IN_PROGRESS | `core/operator_session.py`(immutable Principal, constant-time HMAC, `SCOPE_KAI_ULTRA`), `operator_session_web.py`, `kai_bridge.py`(re-resolve every entry) | — | — | Voice/gesture carry no authority. Continuous gate at every phase. |
| 76 | Prompt-injection defense | IN_PROGRESS | `results.py`(scan_for_injection, NFKC fold, sanitize_external_result), `invocation.py`, `aikido_adapter.py`, `reasoning_sanitizer.py` | — | — | Chat/reasoning-context ingestion (README/logs/PR via twin/brain builders) NOT routed through `scan_for_injection`. |
| 77 | Proactive idea safety | IN_PROGRESS | `proposals.py`/`proposals_store.py`, `governance.actions.audited(destructive=…)` | — | — | No per-idea classifier tagging money/prod/legal/security/cred/customer-comms/personnel w/ approval boundary. |
| 78 | Resource governance | IN_PROGRESS | `router/spend_tracker.py`(USD caps), `admin_chat._RATE_LIMIT_PER_MIN`, `execution.rate_limit_per_min`, `coding.cost_budget`, `_guardrails` ceiling | — | — | No per-mission/provider/company dimension, no anomaly surface/dashboard. ⚠ `core/budget_manager.py`(NarAI ads) is a false friend. |
| 79 | Automation priority | IN_PROGRESS | `holding_cycle.py`(bounded per-source, 0 work on no-change, 3 brakes, no continuous LLM loop) | — | — | CRITICAL constraint honored. Enforce at every phase. |
| 80 | Continuous thinking | IN_PROGRESS | bounded observe→reconcile→plan→work→evidence cycle | — | — | Goals-vs-reality eval loop not assembled (needs §81/§82 + §34). |
| 81 | HoldingGoalRegistry | NOT_STARTED | (reuse) `../planning/` storage/approval pattern | — | — | `registry.kpis[]` free-text; `current_goal` UNAVAILABLE string. Distinct from work-goals — do not overload. |
| 82 | Goal-gap analysis | NOT_STARTED | (reuse) `priorities.py`/`reconcile_plan` deterministic-evidence style | — | — | Depends on §81. |
| 83 | Strategic/weekly review | NOT_STARTED | (reuse) `reports` builders + `kpi_history`(WoW), `holding_cycle.CYCLE_INTERVALS["planning_90d"]` | — | — | Only the cadence constant exists. |
| 84 | Morning/arrival report | IN_PROGRESS | celery-beat `holding-morning-briefing`→`workers/holding_tasks.morning_briefing`, `GET /admin/holding/briefing` | — | — | Auto-on-open trigger not wired (same owner-open event as §12). |
| 85 | Company deep dive | IN_PROGRESS | `reports.company_portfolio(entity_id)`, `GET /admin/holding/entities/{id}` | — | — | Registry dict only — no per-company live signals/proposals/deploy/health/goal-gap/timeline folded in. |
| 86 | System deep dive | IN_PROGRESS | `CapabilityRegistry`, `CodingWorkerRouter`, `seed.py`, Nexus systems canvas | — | — | No stale hardcode; no per-system "deep dive from real registries" view assembled as such. |
| 87 | Self-explanation | IN_PROGRESS | `self_model.py`, `priorities.py`(source-cited), `grounding.py`(cited-or-refuse), evidence refs | — | — | No unified "explain fact/priority/alternatives/uncertainty" endpoint. |
| 88 | Review/challenge mode | NOT_STARTED | (extend) `certify_worker_result` seam (code-only today) | — | — | No re-evaluate-with-separate-reviewer over reasoning/recs. |
| 89 | Multi-agent review | IN_PROGRESS | `capability/coding.certify_worker_result`(reviewer≠worker, enforced in `a2_framework`) | — | — | One certified seam; not the §89 panel (planner/domain-expert/security-reviewer/verifier). Extend, don't fork. |
| 90 | Holding Command API | BLOCKED `[G:SPEC90]` | (pattern) `admin_capabilities.InvokeBody`(server-derived Principal via `require_kai_ultra`)→Brain | — | — | Substrate exists; §90 spec tail TRUNCATED. Envelope missing context/company/mode/client_caps; no `/admin/holding/command`. Phase 5 blocked until tail supplied. |
| 91 | Streaming command | IN_PROGRESS | `kai-presence.js` governed streaming drawer, `/admin/kai-chat/stream`(SSE) | — | Gate3 STREAMING PASS (88 frames/4.3s, cancellation, owner-only) per MEMORY | Hardened streaming exists; full §91 event taxonomy (COMMAND_ACCEPTED/CONTEXT_RESOLVED/MISSION_*/etc.) tied to §90/§27 — incomplete. |
| 92 | Voice audit | NOT_STARTED | (reuse) audit_log pattern | — | — | Depends on voice loop (§7 dormant). Raw-audio-ephemeral policy NET-NEW. |
| 93 | Gesture audit | BLOCKED `[G:CAM]` | — | — | — | Depends on gesture (§9). |
| 94 | Camera privacy | BLOCKED `[G:CAM]` | — | — | — | Default OFF; needs operator authorization + explicit enablement before any camera path. |
| 95 | Mobile | NOT_STARTED | (extend) presence layer | — | — | Mobile-compact iface (presence/health/brief/PTT/attention/working/decisions) absent; gesture may be honestly UNAVAILABLE on mobile. |
| 96 | Notifications (one model) | IN_PROGRESS | `delivery.py`, `watch.py`, `self_improvement_detect`, `admin_supreme.telegram_notify_severity` | — | — | Same substrate as §31; no single `NotificationEvent` model — no per-feature provider allowed. |
| 97 | Global kill switch | IN_PROGRESS | `holding_cycle.py`(3 fail-closed brakes), autonomy flags, `autonomous_work` kill switches | — | flags dark in prod | No unified dashboard STOP w/ full brake taxonomy (OBSERVATION/DETECTION/A1/A2/SELF-IMPROVEMENT/EXTERNAL-COMMS/FINANCIAL/RESTRICTED-SEC/OS-LAB) + ON/OFF/UNAVAILABLE/POLICY_LOCKED states. |
| 98 | Dynamic "what can you do?" | IN_PROGRESS | capability `registry.py`, 126-cap catalog | — | — | Registry exists; per-cap state vocab (AVAILABLE/ACTIVE/DISABLED/BLOCKED/AUTH_REQUIRED/RESTRICTED/UNAVAILABLE/EXPERIMENTAL) partial. No hardcoded list. |
| 99 | Dynamic limitations | IN_PROGRESS | `self_model._KNOWN_LIMITATIONS` | — | — | Static hardcoded; §99 wants policy-derived, part of OperationalSelfModel (§1/§63). |
| 100 | Deployment truth | IN_PROGRESS | `holding_deployment.py`(pattern already implements) | — | live in prod @ `4fbfb8e` (part of §2) | Source hierarchy provider-metadata→git-provenance→signed-manifest→UNKNOWN; never stale manual GIT_SHA as truth. |
| 101 | Deploy reconciliation | IN_PROGRESS | `holding_deployment.py`, dashboard reconciliation (§2) | — | dashboard reconciled this session | No-feature-COMPLETE-until-deploy+dashboard-verified policy honored. |
| 102 | Dark deployment | IN_PROGRESS | authority flags(HOLDING_AUTONOMY/CAPABILITY_EXECUTION/A2/CYBER_OPS/SELF_IMPROVEMENT), `holding_deployment` | — | live: deployed-but-dark in prod | deploy != activate distinction appears in dashboard. Pattern already live. |
| 103 | Feature registry | IN_PROGRESS | `holding_deployment.FEATURE_REGISTRY` | — | — | Extend w/ §103 field set (introduced_sha/current_source_sha/runtime_enabled_staging|prod/risk_class/cert/blockers). |
| 104 | Presence header | IN_PROGRESS | `kai-presence.js` orb, `holding.html` header | — | — | Not all §104 fields inline (companies/prod-health/missions/problems/owner-decisions/worker/autonomy A0/A1 ON A2 OFF). |
| 105 | Holding snapshot | IN_PROGRESS | `holding.html`, `self_model.what_am_i_doing`, `portfolio_view` | — | — | One-glance state-over-metrics summary (healthy?/changed?/broken?/doing?/needs-me?) partial. |
| 106 | Problem cards | IN_PROGRESS | `priorities.derive_priorities`, `owner_queue`, `holding.html` | — | — | Card UI + full action set (ASK/INVESTIGATE/EVIDENCE/CREATE-MISSION/PREPARE-FIX/APPROVE/REJECT/DEFER) + RBAC-aware "never render an action the principal can't use" partial. |
| 107 | Opportunity cards | NOT_STARTED | (depends) §20 OpportunityEngine | — | — | Rejected must stay in decision memory. |
| 108 | Idea conversation | NOT_STARTED | (depends) §21 + §54 context | — | — | "build the plan but don't execute" → SIMULATION/PLAN-ONLY, no execution authority inferred. |
| 109 | Simulation | NOT_STARTED | (reuse) capability results shape | — | — | Normalized capability, distinct from real action; never mutate real state. |
| 110 | Financial simulation | NOT_STARTED | (depends) §109 + §45 | — | — | REAL only if authoritative else ASSUMPTION/UNAVAILABLE; MONEY_MODE stays MOCK unless separate governance. |
| 111 | Audit model | IN_PROGRESS | `governance.actions.audited`, audit_log | — | — | Full §111 field set (actor/principal/role/scopes/mission/procedure/policy-result/approval-ref/corr/evidence) partial; no secrets in audit. |
| 112 | Central redaction | IN_PROGRESS | `task_resolver.redact`, `kai_bridge._STRIP_REQUEST`, `invocation.py`, `reasoning_sanitizer.py` | — | — | Redaction across paths; single unified layer + full adversarial fixture set (GitHub/OpenAI/Anthropic/Slack/AWS/Stripe/Railway/DB-URL/cookie/JWT/private-key) partial. |
| 113 | External repo quarantine | IN_PROGRESS | `capability/manifest.py`, `results.scan_for_injection`(README=DATA), capability DISCOVERED states | — | — | Full lifecycle state machine (DISCOVERED→…→CERTIFIED/RESTRICTED/REJECTED) partial. |
| 114 | Malware/supply-chain | IN_PROGRESS | `capability/manifest.py` supply-chain, `security/aikido_adapter.py` | — | — | Standardized cert report + bounded verdicts (NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE/SUSPICIOUS/REJECTED/UNVERIFIED) partial. OS-specific application `[G:OSLAB]`. |
| 115 | OS catalog ingestion | BLOCKED `[G:OSLAB]` | — | — | — | `OsCatalogEntry` metadata; don't clone all. |
| 116 | Initial OS dispositions | BLOCKED `[G:OSLAB]` | — | — | — | Ultron=EDUCATIONAL, virtme-ng=RESTRICTED_KERNEL, Bottlerocket=INFRA_CANDIDATE, Qubes/Genode=SECURITY_REFERENCE, syzkaller=RESTRICTED_SECURITY_LAB. |
| 117 | No runtime explosion | BLOCKED `[G:OSLAB]` | — | — | — | OS-lab is knowledge/eval; principle honored by deferring OS-lab. |
| 118 | Resource observability | IN_PROGRESS | `spend_tracker.py`, rate limiters | — | — | Token-cost/latency tracked; full CPU/mem/disk/queue/browser observability + no-fabricated-telemetry surface partial. |
| 119 | Worker health | IN_PROGRESS | `CodingWorkerRouter`, worker_jobs | — | — | Full vocab (ONLINE/IDLE/BUSY/DEGRADED/AUTH_BLOCKED/OFFLINE/QUARANTINED) + heartbeat surface partial; ONLINE != authority. |
| 120 | Coding worker truth | IN_PROGRESS | `capability/coding.py` | — | Codex certified; Claude worker secondary (MEMORY) | Reports real config; Claude needs fixture+cert before AVAILABLE (auth-blocked under scrubbed env). |
| 121 | Worker routing | IN_PROGRESS | `capability/coding.py::CodingWorkerRouter`(fit/health/cert, no branding priority, honor operator pin) | — | — | Strong EXISTS; audited failover partial. |
| 122 | Presence without compute waste | IN_PROGRESS | `kai-presence.js`(client-driven orb, no LLM-to-animate) | — | — | Honored; idle presence state-driven. Enforce w/ §79. |
| 123 | Event-driven intelligence | IN_PROGRESS | `watch.py`, `holding_cycle.py`(bounded, 0 work on no-change) | — | — | Full material-event trigger set (DEPLOYMENT/HEALTH/MISSION/WORKER/CAPABILITY_CHANGED/PROBLEM_CONFIRMED/OWNER_APPROVAL/CUSTOMER/FINANCIAL/SECURITY/SESSION_STARTED) partial. |
| 124 | Operator return | NOT_STARTED | (depends) §66 arrival event | — | — | No last-meaningful-session store; changes_since_last_visit from authoritative events not built. |
| 125 | Greeting dedupe | NOT_STARTED | (depends) §124/§66 | — | — | Session-aware, one greeting per meaningful return (not on refresh/nav/reconnect). |
| 126 | Presence context | IN_PROGRESS | `kai-presence.js`(conversationId + context) | — | P13 Nexus continues conversation | Preserve company/mission/problem/last-discussion for "explain this"; resolution partial (same gap as §54). |
| 127 | Company context switch | IN_PROGRESS | `registry.all_entities`, `portfolio_view`, `GET /admin/holding/entities/{id}` | — | — | Entity data/endpoints exist; conversational switch ("switch to Nurtelle"/"compare Sol and SiteBoost") NET-NEW (needs §8/§54). |
| 128 | Consequential confirmation | IN_PROGRESS | `capability/risk.evaluate_policy`→REQUIRE_APPROVAL, `owner_queue` | — | — | Approval model records; NL consequential-turn + casual-word guard partial (same gap as §24); voice resolves to durable approval record. |
| 129 | Voice spoofing defense | IN_PROGRESS | `operator_session`(immutable Principal), §75 | — | — | Enforced: authenticated session is principal, voice carries no authority; voice-specific cert needs voice loop (§135). |
| 130 | Gesture spoofing defense | BLOCKED `[G:CAM]` | (enforcement in) `operator_session` scope model | — | — | "gesture != approval" already guaranteed by §75; gesture-specific cert gated on camera authorization. |
| 131 | Untrusted content rendering | IN_PROGRESS | `cyber-operations.html` esc(), `results.scan_for_injection` | — | — | Safe rendering on cyber-ops page; not universal (holding.html etc.) vs stored/reflected XSS/unsafe-markdown/js-URLs/SVG injection. |
| 132 | Browser security | IN_PROGRESS | hardened CSP, `operator_session` cookies, CSRF/origin controls | — | — | Preserve — don't loosen CSP for avatar/gesture/analytics/CDN; self-host reviewed assets. |
| 133 | 3rd-party interaction deps | IN_PROGRESS | (pattern) capability supply-chain review; voice/avatar libs self-hosted | — | — | Speech/wake-word/gesture/WebGL libs supply-chain review not all done; gesture libs gated. |
| 134 | Testing pyramid | IN_PROGRESS | unit/security/adversarial/browser tiers exercised (§2/§48) | partial | §2 4-viewport browser; §48 44/44 unit | HOSTED + DEPLOYMENT tiers `[G:STAGING]` (no isolated staging env). |
| 135 | Voice cert | NOT_STARTED | (depends) §7 voice loop | — | — | Permission/mic/PTT/partial+final-transcript/timeout/barge-in/mute/session-expiry/ambiguous-approval/stop; no hidden recording. |
| 136 | Gesture cert | BLOCKED `[G:CAM]` | — | — | — | Default-OFF/cam-denied/explicit-enable/visible-indicator/no-video-persistence/no-high-impact-auth. |
| 137 | Presence state cert | IN_PROGRESS | `kai-presence.js` state machine (real-SSE-driven, §64) | — | — | Adversarial state-machine suite (WORKING w/o mission, READY w/ backend down, prod-state-from-staging) → truthful/fail-closed — not yet written. |
| 138 | Proactive brief cert | IN_PROGRESS | `watch.diff`(one alert/change), reconcile(0 on no-change) | — | — | Anti-flood behavior exists; formal cert (no-change→silence, dup→no-repeat, stale→qualified, reviewed→no-repeat) not written. |
| 139 | Opportunity quality cert | NOT_STARTED | (depends) §20 | — | — | Generic→reject/low-conf, dup→dedupe, rejected-no-new-evidence→suppress. |
| 140 | Approval adversarial | IN_PROGRESS | `owner_queue`, `idempotency_key`, `operator_session` | — | — | Some fail-closed guards (idempotency, principal re-resolve, cross-company scope); full suite (stale-yes/replay/changed-diff-post-approval/prod-staging-substitution/provider-fake-approval) not written. |
| 141 | Self-model truth tests | IN_PROGRESS | `self_model` `claims_consciousness=False` | — | assertion holds | Full truth-test suite ("unlimited"/"all-healthy"/"say-prod-deployed") not written. |
| 142 | Prompt-injection suite | IN_PROGRESS | `results.scan_for_injection`, `sanitize_external_result` | — | — | Scan on external-data path; chat/reasoning-context gap (§76); full malicious-content suite partial. |
| 143 | Safe malware fixtures | NOT_STARTED | (substrate) `aikido_adapter` scanner | — | — | Benign mimics (curl\|bash literal/cred-path/cron-persistence/base64-blob/outbound-host) that scanner escalates; no real malware — not yet authored. |
| 144 | Visual cert | IN_PROGRESS | Playwright | — | §2 holding dashboard 4-viewport this session | Remaining §144 surfaces (voice/privacy/attention/opportunities/self-model/OS-lab/registry etc.) pending as built. |
| 145 | Perf cert | IN_PROGRESS | Nexus code-split (§72) | — | — | Core-render/latency/no-infinite-polling/memory-growth cert not run. |
| 146 | A11y cert | IN_PROGRESS | `cyber-operations.html`, `kai-presence.{js,css}` pass | — | — | `holding.html` fails a11y — must fix (§71). Essential actions need accessible path (voice/gesture never sole way). |
| 147 | Required delivery phases | IN_PROGRESS | baseline §4 phase plan | — | — | Phase plan authored; execution ongoing. Don't delay core presence for experimental OS features. |
| 148 | Final dashboard hierarchy | IN_PROGRESS | `holding.html`(subset) | — | — | Full §148 hierarchy (PRESENCE/TODAY/BRIEF/ATTENTION/…/OS-LAB/TIMELINE/EVIDENCE, not all equally dominant) partial. |
| 149 | Deploy classification | IN_PROGRESS | `holding_deployment`, dark-deploy pattern (live) | — | — | Formal P0/P1/P2-dark/P3-authority taxonomy partial. |
| 150 | No hidden feature | IN_PROGRESS | `holding_deployment.FEATURE_REGISTRY`, dashboard-truth policy | — | — | Deployed→appears-in-registry invariant (voice/gesture/ultron/virtme/A2 w/ runtime state) partial. |
| 151 | Production safety defaults | IN_PROGRESS | authority flags all dark, MONEY_MODE=MOCK | — | certified this session via §2 | PTT-enabled-after-cert pending; camera/gesture defaults N/A until those features exist. |
| 152 | Release pipeline | IN_PROGRESS | §2 prod pipeline (App B first, App A second, drift-reconcile) | — | proven via §2 release | STAGING tier `[G:STAGING]` — no isolated staging env; staging-deploy + Playwright-staging steps can't run. |
| 153 | Rollback | IN_PROGRESS | `docs/ROLLBACK_ceo_dashboard.md`, `holding_deployment` (prev SHA record) | — | — | Record prev App A/B SHA + darkening + migration-impact; if App B fails don't advance App A. |
| 154 | Audit experience | IN_PROGRESS | audit_log, WorkResults, `cycle_store` | — | — | "what did you do today?" reconstruction endpoint (observations/missions/actions/workers/approvals/results/deploys) partial; no hidden reasoning. |
| 155 | Executive trust standard | IN_PROGRESS | `grounding.py`(cited-or-refuse), `report_value`→UNAVAILABLE, `self_model` | — | — | Truthfulness-over-appearing-smart enforced in code; continuous standard. |
| 156 | End-to-end operator acceptance | NOT_STARTED | (depends) full build | — | — | Scenarios A–J (Arrival/Voice/Investigation/Solution/Opportunity/Self/Activity/Stop/Gesture/Dashboard-truth) — most depend on unbuilt engines. |
| 157 | Final security acceptance | NOT_STARTED | (partial) §48 review-triad, MEMORY RBAC fixes | — | — | 0 crit/high across full attack surface — acceptance gate; needs full adversarial suite + hosted cert `[G:STAGING]`. |
| 158 | Final product acceptance | NOT_STARTED | (depends) full build | — | — | Dashboard answers all §158 questions — acceptance gate. |
| 159 | Final certification report | BLOCKED `[G:STAGING]` | — | — | — | Exact §159 format → CERTIFIED or blockers; needs hosted staging + all acceptance gates (§156–158). Don't mark CERTIFIED w/ unresolved failures. |
| 160 | Execution behavior | N/A | — | — | — | Agent execution-mode directive (proceed through reversible authorized work; ask only for genuine external/human gates). Honored throughout; not a buildable/testable artifact. |
| 161 | Requirements ledger | IN_PROGRESS | **this file** `docs/KAI_OMNIPRESENCE_REQUIREMENTS.md` | — | created this session | Living doc; advances w/ each phase. All §0–166 present (no silent omission). |
| 162 | Evidence matrix | IN_PROGRESS | `docs/KAI_OMNIPRESENCE_EVIDENCE_MATRIX.md` | — | created this session | Seeded w/ real-evidence rows (§2/§48/§70/§73); rest pending. Mechanically traceable. |
| 163 | Decision log | IN_PROGRESS | `docs/KAI_OMNIPRESENCE_DECISIONS.md` | — | created this session (9 ADRs) | Living doc; all 7 §163-mandated topics covered (event-driven-not-loop/mic-off-PTT/gesture-no-consequential/self-model-not-sentience/repo-quarantine/deployed!=enabled/KAI-is-brain) + strict-reuse + base-branch ADRs. |
| 164 | Threat model | IN_PROGRESS | `docs/KAI_OMNIPRESENCE_THREAT_MODEL.md` | — | created this session (19 threats, 8 boundaries) | Living doc; 19-threat table (threat/boundary/mitigation-module/test/residual) + 4 flagged HIGH gaps + residual-risk register w/ §0#12 re-score trigger. |
| 165 | KAI remains the brain | IN_PROGRESS | `a2_framework.py`(FORBIDDEN_A2), `coding.py`(no model gets approval authority), `execution.py`(the ONE plane) | — | — | No external system (Ultron/Claude/Codex/Gemini/MCP/LangGraph) becomes alt authority plane. Enforced in code; continuous gate. |
| 166 | Final product principle | IN_PROGRESS | whole program | — | — | Continuous guiding principle: CAPABLE+INFORMED+PROACTIVE+PERSISTENT+GOVERNED+AUDITABLE+TRUTHFUL, never theatrical fake autonomy. Enforced at every phase gate. |

---

## Notes on classification
- **PASS** is reserved (per §0 #13 and the derivation rule) for requirements coded + tested + adversarially-reviewed + certified **this session**: only §2 (release, 4-viewport prod cert) and §48 (security center, 44/44 + review-triad). §48 is certified-but-**undeployed** — see the evidence matrix for the deployment gap.
- **BLOCKED** marks genuine external gates, not "hard work remaining": `[G:SPEC90]` §90 (truncated spec tail), `[G:CAM]` gesture/camera cluster (§9, 93, 94, 130, 136), `[G:OSLAB]` OS-lab cluster (§39–43, 115–117), `[G:STAGING]` final cert (§159). Staging-gated *authority enablement* is noted inline on §23/§26/§97/§134/§152 rather than flipping those to BLOCKED, because their code exists and is testable locally — only the live-authority act is gated.
- **§45/§46 (finance/customer)** stay IN_PROGRESS, not BLOCKED: the surfaces are buildable now (render UNAVAILABLE honestly); only real-data/real-money enablement is gated on operator data provisioning.
- Statuses here are the **initial** derivation. As phases land, promote IN_PROGRESS→PASS only with matching rows in `KAI_OMNIPRESENCE_EVIDENCE_MATRIX.md`.
