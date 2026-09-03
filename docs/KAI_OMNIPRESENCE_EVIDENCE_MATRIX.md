# KAI OMNIPRESENT HOLDING COMMAND OS — Evidence Matrix (§162)

> Mandated by spec §162: mechanically-traceable evidence per requirement.
> Columns: requirement · implementation · unit_test · integration_test · adversarial_proof ·
> runtime_proof · browser_proof · deployment · SHA · status.
>
> **This is a living doc and it is honest — `pending` means pending, not "assumed done".**
> Only rows with real evidence collected **this session** are filled; every other §0–166 row is
> present as a pending row so the matrix stays complete and traceable. Promote a row only when the
> named artifact actually exists. Status mirrors `KAI_OMNIPRESENCE_REQUIREMENTS.md` (§161).

## Status vocab
`NOT_STARTED` · `IN_PROGRESS` · `PASS` · `BLOCKED` · `REJECTED` · `N/A`
Cell value `pending` = evidence not yet collected. `—` = not applicable to this requirement.

---

## Seeded rows — real evidence collected this session

| requirement | implementation | unit_test | integration_test | adversarial_proof | runtime_proof | browser_proof | deployment | SHA | status |
|-------------|----------------|-----------|------------------|-------------------|---------------|---------------|------------|-----|--------|
| §2 Current release | Holding OS dashboard + `kai-presence.js`(orb + governed streaming drawer) + Nexus + `kai_bridge.py` + deployment-truth registry | suite green | bridge App A↔App B verified | RBAC hardening (MEMORY: 2 HIGH escalations found+fixed on merge lineage) | BOTH prod services healthy; authority OFF/MOCK/IN_SYNC; `report_value`→UNAVAILABLE for un-sourced money | **Playwright 4-viewport cert this session** (3440×1440/1920×1080/1440×900/390×844) | BOTH prod: App A `app.wheellsverse.com` + App B `kai.wheellsverse.com` | `4fbfb8e` (PR #67) | **PASS** |
| §48 Security center | `services/security/{evidence_bus,posture,risk_score,aikido_adapter}.py` + `routers/admin_security.py`(10 read-only `/admin/cyber/*`) + `cyber-operations.html` + `kai-nexus-security.js` | **44/44 pass** | pending | **6-lens adversarial review-triad this session** | pending (undeployed) | pending (page built, not on a live surface) | **undeployed** — flag `KAI_CYBER_OPS_ENABLED` dark | on `feat/kai-cyber-operations` | **PASS** (code+tests+review; not deployed) |
| §70 Visual language | `holding.html` + `cyber-operations.html` + `kai-nexus.css` (Space Grotesk, navy/cyan, original KAI identity, no JARVIS assets) | — | — | pending | live in prod (holding dashboard) | covered under §2 4-viewport cert | LIVE (holding.html in prod) | `4fbfb8e` | IN_PROGRESS |
| §73 Offline/degraded | `cyber-operations.html` + holding cyber card — AbortController → NOT_CONNECTED/OFFLINE/DEGRADED, **no fake AI response** | pending | pending | honesty pattern verified (degraded renders w/o fabricated AI output) | pending | pending | undeployed (cyber card) / holding card LIVE | `4fbfb8e` (holding) | IN_PROGRESS |

---

## Pending rows — full §0–166 traceability (seed for the living matrix)

> `implementation` cites the reuse anchor where one exists (from the baseline gap matrix); all
> evidence columns are `pending` until the artifact is actually produced. Deployment/SHA reflect
> **current** truth (`4fbfb8e` = live in prod; `dark` = deployed-but-flag-off; `—` = not deployed).

| requirement | implementation | unit_test | integration_test | adversarial_proof | runtime_proof | browser_proof | deployment | SHA | status |
|-------------|----------------|-----------|------------------|-------------------|---------------|---------------|------------|-----|--------|
| §0 Permanent principles | `a2_framework.py`, `coding.certify_worker_result`, `holding_cycle.py`, `kai_bridge`, `results.Provenance` | pending | pending | pending | pending | — | continuous gate | — | IN_PROGRESS |
| §1 OperationalSelfModel | `self_model.py`, `digital_twin.py`, `capability/graph.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §3 Target dashboard surfaces | `holding.html` (~16/26) | pending | pending | pending | pending | pending | LIVE (subset) | `4fbfb8e` | IN_PROGRESS |
| §4 KaiPresenceState | `kai-presence.js`, `kai-nexus-embodiment.js` | pending | pending | pending | pending | pending | LIVE (frontend) | `4fbfb8e` | IN_PROGRESS |
| §5 Always present | `_inject_kai_presence()` | pending | pending | pending | live all `/admin/*` | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §6 Always-listen privacy | `kai-speech-input.js` | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §7 Voice command center | `kai-speech-input.js`, `kai-tts-provider.js`, `kai-barge-in.js`, `voice_router.py` | pending | pending | pending | pending | pending | — (dormant) | — | IN_PROGRESS |
| §8 Natural command router | `capability/brain.py`, `command.py`, `task_resolver.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §9 Gesture | — | — | — | — | — | — | — `[G:CAM]` | — | BLOCKED |
| §10 Avatar | `kai-avatar-driver.js`, viseme suite, `kai-glb-renderer.js`, `kai-avatar-lab.html` | pending | pending | pending | video-swap live | pending | dormant | — | IN_PROGRESS |
| §11 ProactiveBriefingEngine | `watch.py`, `self_improvement_detect` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §12 Arrival brief | `briefing.today_for_you()` (stub) | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §13 DailyHoldingBrief | `reports.build_morning_briefing()`, `briefing.run_morning_briefing()` | pending | pending | pending | powers dashboard+spoken | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §14 HoldingDigitalTwin | `digital_twin.py`, `registry.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §15 SystemKnowledgeIndex | `repo_inspect.py`, `tech_doc_lookup.py`, `log_inspect.py`, `deployment_status.py`, `../kg/` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §16 Knowledge freshness | `digital_twin.fact()`/`_freshness()` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §17 CurrentAttentionModel | (assemble) `what_am_i_doing`, `portfolio_view`, `plan`, `owner_queue` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §18 Problem detection | `priorities.derive_priorities()`, `self_improvement_detect.Candidate` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §19 Solution engine | `proposals._template()`, `owner_review_package()` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §20 OpportunityEngine | (reuse) Candidate shape | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §21 Idea mode | (extend) `proposals_store.py` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §22 Prioritization | `priorities.derive_priorities()` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §23 Autonomy A0–A5 | `plan.py::AutonomyClass`, `autonomous_work.py` | pending | pending | pending | flags dark in prod | — | dark | `4fbfb8e` | IN_PROGRESS |
| §24 Approval conversation | `/proposals/approve|reject`, `risk.evaluate_policy`, `owner_queue.OwnerAction` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §25 Owner decision center | `owner_queue.prepare_owner_actions`, `today_for_you` | pending | pending | pending | pending | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §26 Safe execution loop | `autonomous_work.run_cycle`, `holding_cycle.run_persistent_cycle`, `executor.execute_approved` | pending | pending | pending | pending | — | dark (staging-only run) | — | IN_PROGRESS |
| §27 Mission system | (wrap) `PlanTask`+proposals+worker_jobs+CycleRecord | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §28 Proactive missions | `watch.diff`, `reconcile_plan`+`owner_queue` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §29 KAI working now | `holding_view.py::kai_working` | pending | pending | pending | pending | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §30 Background scheduler | `watch.run_watch`, `run_morning_briefing`, `status.cron_status` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §31 Notification policy | `watch.py`, `delivery.send_alert`, `telegram_notify_severity` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §32 Memory | `../memory/store.py`, `../kg/`, `proposals_store.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §33 Self-improvement | `self_improvement.py`, `_guardrails.py`, `_detect.py` | pending | pending | pending | flag `KAI_SELF_IMPROVEMENT_ENABLED` dark | — | dark | — | IN_PROGRESS |
| §34 Eval harness | (clone) `risk_score.py` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §35 Model routing | `capability/coding.py::CodingWorkerRouter` (+reconcile `feat/kai-freellmapi`) | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §36 Coding workforce | `capability/coding.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §37 Capability fabric pipeline | `brain.py`, `registry.py`, `execution.py`, `risk.py`, `results.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §38 Capability dashboard | `admin_capabilities.py`, `kai-capabilities.html`, 126-cap catalog | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §39 Systems/OS Lab | — | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §40 Ultron OS sandbox | — | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §41 OS supply-chain cert | (pattern) `capability/manifest.py`, `security/*` | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §42 virtme-ng | — | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §43 syzkaller | — | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §44 Qubes/Genode principles | `operator_session.ROLE_SCOPES`, `execution._ip_forbidden`, worktree isolation, `kai_bridge` allowlist | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §45 Finance | `digital_twin.py` (fact→UNAVAILABLE), `holding.html` placeholder | pending | pending | pending | MONEY_MODE=MOCK | pending | LIVE (UNAVAILABLE) | `4fbfb8e` | IN_PROGRESS |
| §46 Customer intelligence | twin `customers_summary` Fact | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §47 Marketing/sales | — | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §49 Digital human | `kai-nexus-embodiment.js`, `kai-subtitles.js`, TTS, barge-in | pending | pending | pending | video-swap live | pending | dormant | — | IN_PROGRESS |
| §50 Voice personality | `kai-presence.js::_pickVoice`, `tts-provider.scoreVoice` | pending | pending | pending | pending | pending | LIVE (voice-pick) | `4fbfb8e` | IN_PROGRESS |
| §51 Speech length | `speak()` truncation | pending | pending | pending | pending | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §52 Interruptions | `kai-barge-in.js`, `kai-presence.js`(stopStream/stopSpeak) | pending | pending | pending | pending | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §53 Command palette | `kai-presence.js` Cmd/Ctrl+K, `window.KAI.ask()` | pending | pending | pending | pending | pending | LIVE (basic) | `4fbfb8e` | IN_PROGRESS |
| §54 Global context | `kai-presence.js`(conversationId+context) | pending | pending | pending | P13 Nexus continues conversation | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §55 Multi-company reasoning | (grounded) `registry.all_entities()`, `portfolio_view()` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §56 HoldingSystemGraph | `capability/graph.py`, `../kg/`, `kai-nexus-systems.js` | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §57 Holding health score | `holding/signals.py::health_block` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §58 KAI confidence | `registry.Confidence` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §59 Evidence drawer | `security/evidence_bus.py`, `evidence_refs` | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §60 Approval evidence package | `self_improvement.owner_review_package` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §61 Holding timeline | Nexus timeline UI (DEMO+SSE) | pending | pending | pending | DEMO tagged as DEMO | pending | — | — | IN_PROGRESS |
| §62 KAI own-status panel | `self_model.snapshot()/describe()`, `holding_view.py`, `holding.html:195` | pending | pending | pending | `claims_consciousness=False` | pending | LIVE (field gaps) | `4fbfb8e` | IN_PROGRESS |
| §63 Limitations | `self_model._KNOWN_LIMITATIONS` | pending | pending | pending | pending | pending | not rendered | — | IN_PROGRESS |
| §64 Never fake presence | real-SSE-driven states; `?scenario=`-only DEMO w/ banner | pending | pending | pending | provenance REAL/DEMO/UNAVAILABLE tagged | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §65 Failure communication | `grounding.py`, `cyber-operations.html` degraded states | pending | pending | pending | pending | pending | partial | — | IN_PROGRESS |
| §66 Owner arrival | `/admin/session/whoami`, `kai_completed_since_last_visit` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §67 Presence settings | — | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §68 Quiet mode | — | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §69 Fullscreen command mode | `/admin/nexus`, `/admin/mission-nexus` (⚠ 2 views) | pending | pending | pending | pending | pending | LIVE (2 views) | `4fbfb8e` | IN_PROGRESS |
| §71 Accessibility | `cyber-operations.html`, `kai-presence.{js,css}` | pending | pending | pending | pending | ⚠ `holding.html` fails a11y | partial | `4fbfb8e` | IN_PROGRESS |
| §72 Performance/lazy-load | Nexus code-split (9 modules) | pending | pending | pending | pending | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §74 Network failure | AbortController, `idempotency_key`, proposal states | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §75 Session security | `operator_session.py`, `operator_session_web.py`, `kai_bridge.py` | pending | pending | pending | pending | live (re-resolve every entry) | — | `4fbfb8e` | IN_PROGRESS |
| §76 Prompt-injection defense | `results.scan_for_injection`, `sanitize_external_result`, `invocation.py`, `reasoning_sanitizer.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §77 Proactive idea safety | `proposals.py`, `governance.actions.audited` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §78 Resource governance | `spend_tracker.py`, rate limiters, `coding.cost_budget` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §79 Automation priority | `holding_cycle.py` (bounded, 0 on no-change, 3 brakes) | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §80 Continuous thinking | bounded observe→reconcile→plan→work cycle | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §81 HoldingGoalRegistry | (reuse) `../planning/` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §82 Goal-gap analysis | (reuse) `priorities`/`reconcile_plan` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §83 Strategic/weekly review | (reuse) `reports`, `kpi_history` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §84 Morning/arrival report | celery-beat `holding-morning-briefing`, `GET /admin/holding/briefing` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §85 Company deep dive | `reports.company_portfolio`, `GET /admin/holding/entities/{id}` | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §86 System deep dive | `CapabilityRegistry`, `CodingWorkerRouter`, `seed.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §87 Self-explanation | `self_model.py`, `priorities.py`, `grounding.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §88 Review/challenge mode | (extend) `certify_worker_result` seam | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §89 Multi-agent review | `coding.certify_worker_result` (reviewer≠worker) | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §90 Holding Command API | (pattern) `admin_capabilities.InvokeBody`→Brain | — | — | — | — | — | — `[G:SPEC90]` | — | BLOCKED |
| §91 Streaming command | `kai-presence.js` streaming drawer, `/admin/kai-chat/stream` | pending | pending | pending | Gate3 STREAMING PASS (MEMORY: 88 frames/4.3s, cancellation, owner-only) | pending | LIVE (basic stream) | `4fbfb8e` | IN_PROGRESS |
| §92 Voice audit | (reuse) audit_log | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §93 Gesture audit | — | — | — | — | — | — | — `[G:CAM]` | — | BLOCKED |
| §94 Camera privacy | — | — | — | — | — | — | — `[G:CAM]` | — | BLOCKED |
| §95 Mobile | (extend) presence layer | pending | pending | pending | pending | pending | — | — | NOT_STARTED |
| §96 Notifications (one model) | `delivery.py`, `watch.py`, `telegram_notify_severity` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §97 Global kill switch | `holding_cycle.py`(3 brakes), authority flags, `autonomous_work` kill switches | pending | pending | pending | flags dark in prod | — | dark | `4fbfb8e` | IN_PROGRESS |
| §98 Dynamic "what can you do?" | capability `registry.py`, 126-cap catalog | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §99 Dynamic limitations | `self_model._KNOWN_LIMITATIONS` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §100 Deployment truth | `holding_deployment.py` | pending | pending | pending | live in prod (part of §2) | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §101 Deploy reconciliation | `holding_deployment.py`, dashboard reconciliation | pending | pending | pending | reconciled this session | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §102 Dark deployment | authority flags, `holding_deployment` | pending | pending | pending | deployed-but-dark live | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §103 Feature registry | `holding_deployment.FEATURE_REGISTRY` | pending | pending | pending | pending | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §104 Presence header | `kai-presence.js` orb, `holding.html` header | pending | pending | pending | pending | pending | LIVE (field gaps) | `4fbfb8e` | IN_PROGRESS |
| §105 Holding snapshot | `holding.html`, `what_am_i_doing`, `portfolio_view` | pending | pending | pending | pending | pending | LIVE (partial) | `4fbfb8e` | IN_PROGRESS |
| §106 Problem cards | `priorities.derive_priorities`, `owner_queue`, `holding.html` | pending | pending | pending | pending | pending | LIVE (partial) | `4fbfb8e` | IN_PROGRESS |
| §107 Opportunity cards | (depends) §20 | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §108 Idea conversation | (depends) §21+§54 | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §109 Simulation | (reuse) capability results shape | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §110 Financial simulation | (depends) §109+§45 | pending | pending | pending | MONEY_MODE=MOCK | — | — | — | NOT_STARTED |
| §111 Audit model | `governance.actions.audited`, audit_log | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §112 Central redaction | `task_resolver.redact`, `kai_bridge._STRIP_REQUEST`, `invocation.py`, `reasoning_sanitizer.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §113 External repo quarantine | `capability/manifest.py`, `results.scan_for_injection` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §114 Malware/supply-chain | `capability/manifest.py`, `security/aikido_adapter.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §115 OS catalog ingestion | — | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §116 Initial OS dispositions | — | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §117 No runtime explosion | — | — | — | — | — | — | — `[G:OSLAB]` | — | BLOCKED |
| §118 Resource observability | `spend_tracker.py`, rate limiters | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §119 Worker health | `CodingWorkerRouter`, worker_jobs | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §120 Coding worker truth | `capability/coding.py` | pending | pending | pending | Codex certified; Claude secondary (MEMORY) | — | — | — | IN_PROGRESS |
| §121 Worker routing | `capability/coding.py::CodingWorkerRouter` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §122 Presence without compute waste | `kai-presence.js` (client-driven orb) | pending | pending | pending | no LLM-to-animate | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §123 Event-driven intelligence | `watch.py`, `holding_cycle.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §124 Operator return | (depends) §66 | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §125 Greeting dedupe | (depends) §124/§66 | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §126 Presence context | `kai-presence.js`(conversationId+context) | pending | pending | pending | P13 Nexus continues conversation | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §127 Company context switch | `registry.all_entities`, `GET /admin/holding/entities/{id}` | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §128 Consequential confirmation | `risk.evaluate_policy`, `owner_queue` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §129 Voice spoofing defense | `operator_session`, §75 | pending | pending | pending | session-is-principal, voice-no-authority | — | — | — | IN_PROGRESS |
| §130 Gesture spoofing defense | (enforcement) `operator_session` scope model | — | — | — | — | — | — `[G:CAM]` | — | BLOCKED |
| §131 Untrusted content rendering | `cyber-operations.html` esc(), `results.scan_for_injection` | pending | pending | pending | pending | pending | partial | — | IN_PROGRESS |
| §132 Browser security | hardened CSP, `operator_session` cookies, CSRF | pending | pending | pending | pending | live (CSP enforced) | — | `4fbfb8e` | IN_PROGRESS |
| §133 3rd-party interaction deps | (pattern) capability supply-chain review | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §134 Testing pyramid | unit/security/adversarial/browser tiers (§2/§48) | partial | pending | partial | §2 4-viewport | §2 4-viewport | HOSTED/DEPLOY `[G:STAGING]` | `4fbfb8e` | IN_PROGRESS |
| §135 Voice cert | (depends) §7 | pending | pending | pending | pending | pending | — | — | NOT_STARTED |
| §136 Gesture cert | — | — | — | — | — | — | — `[G:CAM]` | — | BLOCKED |
| §137 Presence state cert | `kai-presence.js` state machine (§64) | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §138 Proactive brief cert | `watch.diff`, reconcile | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §139 Opportunity quality cert | (depends) §20 | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §140 Approval adversarial | `owner_queue`, `idempotency_key`, `operator_session` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §141 Self-model truth tests | `self_model` `claims_consciousness=False` | pending | pending | pending | assertion holds | — | — | — | IN_PROGRESS |
| §142 Prompt-injection suite | `results.scan_for_injection`, `sanitize_external_result` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §143 Safe malware fixtures | (substrate) `aikido_adapter` | pending | pending | pending | pending | — | — | — | NOT_STARTED |
| §144 Visual cert | Playwright | pending | pending | pending | pending | §2 holding 4-viewport this session | LIVE (subset) | `4fbfb8e` | IN_PROGRESS |
| §145 Perf cert | Nexus code-split | pending | pending | pending | pending | pending | — | — | IN_PROGRESS |
| §146 A11y cert | `cyber-operations.html`, `kai-presence.{js,css}` | pending | pending | pending | pending | ⚠ holding.html fails | partial | `4fbfb8e` | IN_PROGRESS |
| §147 Required delivery phases | baseline §4 phase plan | — | — | — | — | — | — | — | IN_PROGRESS |
| §148 Final dashboard hierarchy | `holding.html` (subset) | pending | pending | pending | pending | pending | LIVE (partial) | `4fbfb8e` | IN_PROGRESS |
| §149 Deploy classification | `holding_deployment`, dark-deploy | pending | pending | pending | dark-deploy live | — | LIVE (pattern) | `4fbfb8e` | IN_PROGRESS |
| §150 No hidden feature | `holding_deployment.FEATURE_REGISTRY`, dashboard-truth | pending | pending | pending | pending | pending | LIVE (partial) | `4fbfb8e` | IN_PROGRESS |
| §151 Production safety defaults | authority flags dark, MONEY_MODE=MOCK | pending | pending | pending | certified this session via §2 | pending | LIVE | `4fbfb8e` | IN_PROGRESS |
| §152 Release pipeline | §2 prod pipeline (App B→App A) | pending | pending | pending | pending | proven via §2 | prod pipeline proven; STAGING `[G:STAGING]` | `4fbfb8e` | IN_PROGRESS |
| §153 Rollback | `docs/ROLLBACK_ceo_dashboard.md`, `holding_deployment` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §154 Audit experience | audit_log, WorkResults, `cycle_store` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §155 Executive trust standard | `grounding.py`, `report_value`→UNAVAILABLE, `self_model` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §156 End-to-end operator acceptance | (depends) full build | pending | pending | pending | pending | pending | — | — | NOT_STARTED |
| §157 Final security acceptance | (partial) §48 review-triad, RBAC fixes | pending | pending | pending | pending | pending | — `[G:STAGING]` | — | NOT_STARTED |
| §158 Final product acceptance | (depends) full build | pending | pending | pending | pending | pending | — | — | NOT_STARTED |
| §159 Final certification report | — | — | — | — | — | — | — `[G:STAGING]` | — | BLOCKED |
| §160 Execution behavior | agent directive | — | — | — | — | — | — | — | N/A |
| §161 Requirements ledger | `docs/KAI_OMNIPRESENCE_REQUIREMENTS.md` | — | — | — | created this session | — | — | — | IN_PROGRESS |
| §162 Evidence matrix | **this file** | — | — | — | created this session | — | — | — | IN_PROGRESS |
| §163 Decision log | `docs/KAI_OMNIPRESENCE_DECISIONS.md` (pending) | — | — | — | — | — | — | — | NOT_STARTED |
| §164 Threat model | `docs/KAI_OMNIPRESENCE_THREAT_MODEL.md` (pending) | — | — | — | — | — | — | — | NOT_STARTED |
| §165 KAI remains the brain | `a2_framework.py`, `coding.py`(no model gets approval authority), `execution.py` | pending | pending | pending | pending | — | — | — | IN_PROGRESS |
| §166 Final product principle | whole program | — | — | — | — | — | — | — | IN_PROGRESS |

---

## How to use this matrix
1. A requirement is **PASS** only when its row shows real artifacts in the tiers §134 requires for its class (unit + adversarial at minimum; browser + runtime + deployment for anything user-facing shipped to prod) — and the ledger (§161) agrees.
2. `[G:*]` gate tags mirror the ledger: `SPEC90` (truncated spec), `CAM` (camera/gesture authorization), `OSLAB` (OS-lab authorization + infra), `STAGING` (no isolated staging env for hosted-edge cert).
3. Never fill a cell from expectation. Paste the real evidence pointer (test id, run log, screenshot path, deploy id, SHA) when the artifact exists — `pending` until then.
4. `SHA` records where the evidence was taken: `4fbfb8e` = certified prod floor (§2); a branch name = code exists there but not in prod; `—` = not deployed.
