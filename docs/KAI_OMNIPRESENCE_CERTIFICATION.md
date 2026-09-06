# KAI OMNIPRESENT HOLDING COMMAND OS — Final Pre-Production Certification (§159)

> The §159 certification report for the Omnipresent Holding Command OS build on
> `feat/kai-cyber-operations`. Every claim below cites a commit SHA, a test name + count, a review
> verdict, or a file path. Where a number was not measured, the cell says `UNVERIFIED` rather than a
> guess. Grounded in `docs/KAI_OMNIPRESENCE_BASELINE.md` (§1 gap matrix),
> `docs/KAI_OMNIPRESENCE_REQUIREMENTS.md` (§161), `docs/KAI_OMNIPRESENCE_EVIDENCE_MATRIX.md` (§162),
> `docs/KAI_OMNIPRESENCE_DECISIONS.md` (§163), `docs/KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md` (§44)
> and `docs/KAI_OMNIPRESENCE_OS_LAB.md` (§39–44).
>
> Status vocab is the program's own: **SATISFIED / PARTIAL / GAP / DEFERRED** (baseline) and
> **PASS / IN_PROGRESS / PENDING / N/A / UNVERIFIED / BLOCKED** (§161/§162).

---

## 0. VERDICT

> **PRE-PRODUCTION CERTIFIED — DARK BUILD (undeployed, nothing enabled).**
> **NOT production-certified: gates remain.**

This build is certified **only** for what it actually is: a dark, undeployed, all-flags-off branch
whose modules are tested and adversarially reviewed in a local worktree.
It is **NOT deployed to production**, has **not** been merged, has **no** open PR, and **nothing is
enabled**. Production (release #67, SHA `4fbfb8e`, App A `app.wheellsverse.com` + App B `kai-prod`)
is **UNCHANGED** by this build.

**Remaining gates — all operator-only, none of them passable by KAI:**

| # | Gate | Status | Blocks |
|---|------|--------|--------|
| G1 | Provision an isolated Railway staging environment | **PENDING** — none exists (baseline OQ #6, MEMORY) | G2, G3, G4 |
| G2 | Hosted-edge certification on that staging environment | **PENDING** (blocked by G1) | G3, G4 |
| G3 | Production merge / deploy go-ahead | **PENDING** | any prod presence |
| G4 | Any authority enable — deploy ≠ enable (ADR-007), one flag at a time | **PENDING** | all 9 flags in §4 |
| G5 | Credential provisioning (finance/customer sources, provider keys) | **PENDING** | §45/§46 real values (OQ #5) |
| G6 | Restricted-security activation (syzkaller is never auto-selected) | **PENDING** | §43 / OS Lab execution |

Until G1–G6 are passed in order, the honest statement of this build is: **built, tested, reviewed,
dark.** Nothing here claims a runtime, hosted, or production certification.

---

## 1. SCOPE

| Field | Value |
|---|---|
| Branch | `feat/kai-cyber-operations` |
| Durable worktree | `/Users/jhonwheeler/wheellsverse-cyberops` |
| HEAD at certification | `8799db98f8ffaf735137e47b0010a6de79bf64d1` (`8799db9`) |
| Working tree | **clean of code** — the P10 credential-leak line took five rounds to close: `cd3b96d` → `58a4227` → `749fa78` → `ed00e4e` → `79062c4` → `8799db9`. Each of those fixes was believed final when it landed; an independent refuter of each one found a new route to the same class of defect. The P8 privacy-lens fixes are committed as `9e0df08`. |
| Deployed | **NO** — nothing deployed, nothing merged, no PR |
| Production affected | **NO** — release #67 / SHA `4fbfb8e` unchanged |
| In-flight changes | **NONE.** No code sits outside a commit, and **no refuter is in flight** — four ran, the last (of `79062c4`) reported 451 assertions / 439 held and its two findings are fixed in `8799db9`. Every count in §2 and §5 is measured at HEAD `8799db9` unless the row says otherwise. What remains is not a review act but a **named residual**: R7 — credential detection is a pattern list, not proof (see N1 and §8 F6). |

**Commit list (oldest → newest):**

`d881cf2` P0 baseline+governance docs & P1 self-model/twin/knowledge · `8be9f2d` P2 attention/goals/memory ·
`8b9c2fe` P3a problems/single-ranker/cross-company · `261931e` P3b opportunity/idea/notification/proactive ·
`d395f24` P4 mission aggregate/working-now/dark cycle · `6247f22` P5 typed Holding Command API/streaming/NL
router/approval/injection · `12a28f6` P6a health score/system graph/timeline/approval package · `c3e3f8c`
P6b-1 12 owner-gated read endpoints + `/view` · `4d7999d` P6b-2 `holding.html` command center · `bee61fd`
P7a VoiceSessionManager · `85b5de0` P7b voice frontend + embodiment + Nexus consolidation · `cd3b96d` P10
OS Lab framework · `6fa5119` P9 governance · `efb05c6` P8 camera+gesture · `ac9fcff` P9 review fixes ·
`58a4227` P10 review fixes · `17ec7ce` P8 review fix · `543da39` UI-contract regression fix ·
`83f6050` P9 round-2 fixes · `9e0df08` P8 privacy-lens fixes · `749fa78` P10 round-2 fix ·
`ed00e4e` P10 round-3 fix · `79062c4` P10 round-4 fix · `8799db9` P10 round-5 fix (**HEAD**).

---

## 2. WHAT WAS BUILT — PER PHASE

Diffstats are `git show --stat`. Test counts are the runner's own per-module totals.

| Phase | Commit | Modules (primary) | Tests | Review lenses → verdict → fix SHA |
|---|---|---|---|---|
| P0+P1 self-model / twin / knowledge | `d881cf2` (12 files, +1756/−29) | `self_model.py`, `digital_twin.py`, `knowledge_index.py`, `registry.py`, `holding_view.py`, `holding.html`, 5 governance docs | `test_omnipresence_phase1` **35/35 PASS**; `test_self_model` **8 PASS** | in-session review triad before commit (see git message + evidence-matrix seeded rows) |
| P2 attention / goals / memory | `8be9f2d` (7 files, +1439) | `attention_model.py`, `goal_registry.py`, `holding_memory.py` | `test_attention_model`, `test_goal_registry`, `test_holding_memory` (counts in-module) | in-session review triad before commit |
| P3a problems / single ranker / cross-company | `8b9c2fe` (7 files, +1266/−40) | `holding_problems.py`, `cross_company.py`, `priorities.py` (single §22 ladder), `briefing.py`, `proposals.py` | `test_holding_problems`, `test_cross_company` | in-session review triad before commit |
| P3b opportunity / idea / notification / proactive | `261931e` (17 files, +2360/−10) | `opportunity_engine.py`, `proactive_engine.py`, `notification_policy.py`, `arrival.py`, `kpi_history.py`, `proposals_store.py` | `test_opportunity_engine`, `test_proactive_engine`, `test_notification_policy`, `test_arrival`, `test_ideas`, `test_weekly_review`, `test_company_deep_dive` | in-session review triad before commit |
| P4 mission / working-now / dark cycle | `d395f24` (11 files, +999/−3) | `mission.py`, `worker_jobs.py`, `holding_cycle.py`, `workers/holding_tasks.py`, `workers/celery_app.py` | `test_mission`, `test_holding_schedule`, `test_holding_view` | in-session review triad before commit |
| P5 typed Command API / streaming / NL router / approval | `6247f22` (9 files, +1114/−2) | `routers/admin_holding_command.py`, `command_router.py`, `approval_dialog.py`, `capability/results.py`, `nai_brain/brain.py` | `test_omnipresence_phase5`, `test_approval_dialog` | in-session review triad before commit |
| P6a health / graph / timeline / approval package | `12a28f6` (9 files, +1475/−8) | `health_score.py`, `system_graph.py`, `timeline.py`, `approval_package.py` | `test_health_score`, `test_system_graph`, `test_timeline` (**34**), `test_approval_package` | in-session review triad before commit |
| P6b-1 12 owner-gated read endpoints + `/view` | `c3e3f8c` (1 file, +280/−22) | `routers/admin_holding.py` (`/health`, `/system-graph`, `/timeline`, `/attention`, `/missions`, `/problems`, `/cross-company`, `/opportunities`, `/goals`, `/knowledge`, `/proactive`, `/system-model`, + `/view`) — router-level `Depends(require_kai_ultra)` | covered by module suites | in-session review triad before commit |
| P6b-2 command center UI | `4d7999d` (1 file, +1125/−283) | `frontend/admin/holding.html` | UI contract **7/7 PASS** (after `543da39`) | regression found post-commit → **`543da39`** restored Ready-for-review + Self-Improvement surfaces and re-pinned the contract test |
| P7a VoiceSessionManager | `bee61fd` (3 files, +648) | `voice_session.py`, `config.py` (`KAI_VOICE_ENABLED`) | `test_voice_session` **36/36 PASS** | in-session review triad before commit |
| P7b voice frontend / embodiment / Nexus consolidation | `85b5de0` (16 files, +1201/−289) | `kai-presence.js`, `kai-presence.css`, `kai-speech-input.js`, `kai-tts-provider.js`, `kai-nexus*.{js,css,html}`, `nexus.html`, `core/api.py`, `admin_holding_command.py` | `test_kai_speech_input` **11 PASS**; frontend suite total **18 node suites / 258 checks** | **2 lenses → 1 HIGH + 7 MED + 10 LOW → all fixed → post-commit refuter: 11/12 hold, 1 MED (`voice.start` trigger passthrough) → fixed in `efb05c6`** |
| P8 camera + gesture | `efb05c6` (9 files, +941/−37) | `gesture_policy.py`, `frontend/admin/kai-gesture.js`, `kai-presence.js`, `config.py` (`KAI_CAMERA_ENABLED`), `core/api.py` | at `efb05c6`: `test_gesture_policy` **51/51 PASS**, `test_kai_gesture` **22 PASS**; at HEAD after `9e0df08`: **55/55** and **27** | **consolidation lens PASS w/ 1 MED → fixed `17ec7ce`** (recognizer seam gated on backend certification truth); **privacy/authority/safety lens FAIL w/ 2 HIGH + 2 MED + 1 LOW → all fixed `9e0df08`** |
| P8 privacy-lens fixes | `9e0df08` (5 files, +89/−6) | `gesture_policy.map_gesture` (non-finite confidence fails closed — `import math` + `isfinite`), `kai-gesture.js` `start()` (policy gate + visibility re-read in the `getUserMedia` **resolve** handler; changed state stops the resolved stream and returns `STOPPED_DURING_START`), `kai-presence.js` (`!e.isTrusted` refused on the §67 camera-enable change handler **and** on the mic press/keydown handlers that mint `ptt-press`/`session-button`), CAMERA-ON indicator rebuilt when missing or `!isConnected` | `test_gesture_policy` **51→55/55 PASS**; `test_kai_gesture` **22→27 PASS** (three tests exercise the real async-gap race); 18 frontend suites; `test_voice_session` **36/36**; `test_approval_dialog` **43/43** | closes the P8 privacy/authority/safety lens: 2 HIGH (camera-lifecycle async gap, camera-activation via script-dispatched event), 2 MED (indicator caching, mic-activation same root cause — code-path finding, not runtime-verified), 1 LOW (NaN confidence beat the threshold gate) |
| P9 governance maturation | `6fa5119` (28 files, +4358/−18) | `brakes.py`, `review_panel.py`, `eval_harness.py`, `challenge.py`, `resource_governor.py`, `explain.py`, `capabilities_answer.py`, `what_i_did.py`, `worker_health.py`, `improvement_cycle.py`, `a2_dispatch.py`, `timeline.py`, `holding_cycle.py`, `capability/coding.py`, `docs/KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md` | Phase-9 modules **394 checks** (brakes 63, capabilities_answer 44, challenge 27, eval_harness 36, explain 32, improvement_cycle 24, resource_governor 43, review_panel 27, what_i_did 32, worker_health 32, timeline 34) | **2 lenses → 3 HIGH + 8 MED + 4 LOW → fixed `ac9fcff` → refuter: 8/9 probes hold, 1 MED (MONEY_MODE reader default narrated) + 2 LOW → round-2 fix `83f6050`** |
| P9 round-2 | `83f6050` (8 files, +143/−10) | `self_model._derive_limitations` (MONEY_MODE tri-state), `review_panel` (certified-clamp on EVERY exit incl. INCOMPLETE), `status.autonomy_status` (derived, not hardcoded), new `test_status.py` | `test_status` **8/8 PASS**; re-run: self_model **8**, phase1 **35/35**, capabilities_answer **45/45**, review_panel **28/28**, brakes **63/63** | closes the P9 refuter's 1 MED + 2 LOW |
| P10 OS Lab framework | `cd3b96d` (16 files, +2133) | `os_lab/{__init__,catalog,certification,runtimes}.py`, `os_lab/fixtures/mimic_repo/` (§143 inert fixtures), `docs/KAI_OMNIPRESENCE_OS_LAB.md` | at `58a4227`: os_lab **216** (catalog **73/73**, runtimes **85/85**, certification **58/58**) | **2 lenses → 1 HIGH + 8 MED + 7 LOW → fixed `58a4227` → then FOUR iterated refuter rounds, each attacking the previous round's fix: `749fa78` → `ed00e4e` → `79062c4` → `8799db9`** (4 HIGH + 1 self-inflicted regression across the four; see §6) |
| P10 round-2 | `749fa78` (8 files, +220/−49) | `os_lab/certification.py` (credential snippets withheld when the **label** looked secret-named; clean verdict re-derived from the attached steps; `walk_truncated` on a capped walk), `os_lab/catalog.py`, `os_lab/runtimes.py` (deep freeze of `executed`/`evidence` via `MappingProxyType`, forbidden-claim + §165 guard normalization, enum-safe verdict compare), `task_resolver.py`, `docs/KAI_OMNIPRESENCE_OS_LAB.md` | os_lab **216 → 226**: catalog **76/76**, runtimes **87/87**, certification **63/63** | closes the P10 refuter's 1 HIGH + 2 MED + 4 LOW. **Believed final when it landed — it was not.** The next refuter showed the label-keyed withholding still emitted secrets via a greedy match, and that the `MappingProxyType` deep freeze **silently disabled `redact()`** on evidence written to the audited history. See rounds 3–5. |
| P10 round-3 | `ed00e4e` (7 files, +198/−63) | `os_lab/certification.py` (snippet boundary moved from the **label** to the **match length** — >40 chars ⇒ withheld; severity gate **fails closed**), `os_lab/catalog.py` (step ids must cover the pipeline; FULL scope requires executed `build`+`qemu_boot`), `os_lab/runtimes.py` (§165 guard `oslab` prefix-anchored), `task_resolver.py` deep-freeze replacement | os_lab **226 → 235** | refuter of `749fa78`: **128 assertions, 119 held, 9 failed** → 3 HIGH. (a) label-keyed withholding was bypassed by a greedy pattern whose match **spanned** the secret — a curl line with a custom auth header put **101 distinct 20-char windows** of a 120-char secret into the report; (b) the severity gate failed **OPEN** (`'critical'`, `'Critical'`, `'crit'`, `9`, `None`, `['CRITICAL']` all certified); (c) **a regression introduced by round 2** — `MappingProxyType` is not a `dict` subclass and `task_resolver.redact` dispatches on `isinstance(obj, dict)`, so the deep freeze silently disabled redaction of evidence written to the append-only history and broke `dataclasses.asdict`. Replaced with a mutation-refusing `dict` subclass. |
| P10 round-4 | `79062c4` (7 files, +239/−66) | `os_lab/certification.py` (**`StepResult.__post_init__` redacts `evidence` at construction** — redacted at the source *and* at the one door; malformed finding rows refused; credential rows floored at MEDIUM; 20-char pre-context dropped; real line numbers via `finditer`), `os_lab/catalog.py`, `os_lab/runtimes.py` (`EXECUTED` ledger read-only with a `simulated_ledger` test seam) | os_lab **235 → 248**: catalog **83/83**, runtimes **92/92**, certification **73/73** | refuter of `ed00e4e`: **201 assertions, 192 held** → 5 findings, 1 HIGH — a `.gitmodules` submodule-URL password was written **verbatim** into step evidence and copied unredacted into the report artifact, while the finding text beside it **was** redacted, which made it easy to miss. |
| P10 round-5 | `8799db9` (3 files, +52/−8) | `os_lab/certification.py` `_CRED_MATERIAL` — seven credential families added (GitHub PAT, GitHub fine-grained PAT, Slack token, OpenAI key, GitLab PAT, bearer/authorization value, credential-in-URL); module docstring + `docs/KAI_OMNIPRESENCE_OS_LAB.md` claim restated | os_lab **248 → 255**: catalog **83/83** · runtimes **92/92** · certification **73 → 80/80** | refuter of `79062c4`: **451 assertions, 439 held** → 2 findings, 1 HIGH. Flooring the **severity** of rows `credential_reads` already matched did nothing for a credential the pattern tables never **matched at all** — all seven families left the step `PASS`, while the module docstring **and** the OS-Lab doc asserted *"an embedded credential can never leave it PASS"*. That claim was **false as written** — a zero-fabrication violation independent of detection quality. Both halves fixed: each family proved to `FAIL` the step with **no window of the secret in the report**, and the claim narrowed to the true one (per **listed** family) with the gap named as residual **R7**. |

**Totals (per-file runner output; os_lab re-measured at HEAD `8799db9`):** backend `holding/` + `os_lab/` = **67 test
modules** (64 in `holding/`, 3 in `holding/os_lab/` — `test_status.py` added by `83f6050`),
**1521 checks, 1520 PASS**. The single failure is `test_si_calc_guard` `bucket(0)` (6 passed,
1 failed), the deliberate BEFORE-state self-improvement fixture, which fails identically on the
pre-omnipresence base `d881cf2^`. Frontend: **18 node suites, 263 checks**, all pass.

**How the 1521 is obtained, stated exactly:** a fresh per-file sweep of all 67 modules was run directly at
HEAD `8799db9` (each module executed as `python3 -m app.services.holding.<mod>`, its own reported total
summed). It is a measurement, not a carry-forward. An earlier draft of this report inferred the figure as
`1452 (measured at 749fa78) + 29 (os_lab delta)` = 1481; the real sweep returned **1521**, so that inference
was wrong by 40 and has been replaced. The lesson is recorded rather than quietly fixed: a derived count in a
certification document is a claim like any other and must be measured before it is published.

At `83f6050` the same sweep measured **67 modules / 1437 checks / 1436 PASS** and **258** frontend
checks. The growth is the tests added by `9e0df08` (`test_gesture_policy` 51→55, `test_kai_gesture`
22→27) and the five P10 rounds (os_lab 216→**255**): **+14** backend attributable by name at
`749fa78`, **+29** more from rounds 3–5, **+5** frontend. The
measured backend total moved by **+15**, one more than those named additions; the extra check is a
conditional one (the `test_brakes.py:393` `[db]` roundtrip runs only when a Postgres is reachable —
see §5), so it is named here rather than silently absorbed. Both totals are honest measurements.

---

## 3. NON-NEGOTIABLES — VERIFICATION

| # | Non-negotiable | Verdict | Evidence (file · symbol · test) |
|---|---|---|---|
| N1 | **Credentials are never exposed** | **PARTIAL** — *not* upgraded to PASS. The controls are verified **for the listed credential families**; residual **R7** means the guarantee is per-family, not universal, so an unqualified "credentials are never exposed" would be exactly the kind of over-broad claim round 5 had to retract. | **Standing controls (unchanged and holding):** `worker_health.credential_present` reports env-key PRESENCE only, never a value (§120); `governance/audit_log.py:95 _redact`; `core/kai_bridge.py:46 _STRIP_REQUEST = {"x-api-key"}` (raw key never forwarded, `:107`).<br><br>**The certification reporter took FIVE rounds to close, and this row must not imply the first fix worked.** The leak was opened by the refuter of `58a4227` and was believed closed at `749fa78` — it was not. Four independent refuters, each attacking the previous round's *fix*, each found a **new route to the same class of defect**: (1) `749fa78` withheld the snippet keyed on the **label**, so a greedy pattern whose match **spanned** the secret still emitted it — 101 distinct 20-char windows of a 120-char secret reached the report; (2) `ed00e4e` moved the boundary to **match length**, made the severity gate fail closed, and undid **a regression round 2 had introduced** (the `MappingProxyType` deep freeze silently disabled `redact()` on evidence written to the audited history — see §8 F6a); (3) `79062c4` found a `.gitmodules` submodule-URL password written verbatim into step evidence and copied unredacted into the report artifact, and fixed it at the source **and** at the one door (`StepResult.__post_init__` now stores `redact(evidence)`); (4) `8799db9` found that seven credential families the pattern tables never **matched** left `credential_reads` `PASS` — while the code and docs claimed no embedded credential could — added those families and **restated the claim to the narrower true one**.<br><br>**What this verdict rests on:** (a) the committed code at `8799db9`; (b) `test_certification` **80/80** at HEAD (repo root on `PYTHONPATH`), os_lab **255** total; (c) four independent refuter runs — 128/119, 201/192, 451/439 assertions held on rounds 3/4/5 respectively — each of whose findings is fixed and re-verified, with every added family proved to `FAIL` the step with **no window of the secret** anywhere in the report JSON.<br><br>**What it does NOT rest on, and why this is PARTIAL:** **R7 — credential detection is a pattern list, not proof.** A secret in a shape none of the listed families match still leaves the step `PASS`. That residual is bounded, not benign: nothing certifies on a static-only report — the clean verdict additionally requires full pipeline coverage and an `executed` ledger with `build` and `qemu_boot` true, neither of which this phase can produce. Nor does this rest on any hosted/runtime execution: the OS-Lab pipeline has never run outside these local tests, and no credential has ever been provisioned to this build (G5 PENDING). Scope is *code + local tests*, not *operated system*. |
| N2 | **No self-approval** | **PASS** | `review_panel.py:28` imports `assert_independent_reviewer` from `capability.coding` — the SAME identity rule as `certify_worker_result`, not a fork; `:68` refuses a panel with no author identity; `:72` normalizes every panelist through it; `:85` refuses when distinct reviewer identities < roles; `:78` records `final_decision_by: COORDINATOR, advisory: True` (§165). OS Lab: `os_lab/catalog.py:221` — only the operator may adopt (`CERTIFIED`/`RESTRICTED`); `:237 record_verdict` is operator-only for the clean-scope verdict (`:247 PermissionError`); `:271 justify_adoption` operator-only. Approval channel: `approval_dialog.py:54/:100` `ConfirmationStatus.REFUSED_CHANNEL` — voice/gesture cannot authorize; asserted by `test_approval_dialog.py:51`, `test_voice_session.py:191` ("even explicit 'approve 42' over VOICE"), `test_gesture_policy.py:139`. Suites: `test_review_panel` **28/28**. |
| N3 | **Deployment ≠ enablement** | **PASS** | All 9 flags default `False` in `backend/app/config.py` — see the flag table in §4. `holding_cycle.build_live_engine` (`holding_cycle.py:25-60`) reads them per build and fails CLOSED on unreadable config (`override = "CONFIG_UNAVAILABLE"`). Nothing in this build is deployed or enabled; ADR-007 is the governing decision. |
| N4 | **Zero fabrication** | **PASS** | `UNAVAILABLE`: `self_model.py:142-150`, `status.py:96-100` (`_money_mode`), `brakes.py:9` (`UNAVAILABLE` = controlling flag unreadable, never a fake OFF), `digital_twin.report_value` → UNAVAILABLE for un-sourced money. `NOT_CONNECTED`: `services/security/{models,posture,capabilities,risk_score}.py`, `routers/admin_security.py`. `INSUFFICIENT_DATA`: `health_score.py`, `self_model.py`, `routers/admin_holding.py`. Certification honesty: `os_lab/certification.py` steps report `UNVERIFIED` with note `core scanner table unavailable` rather than a fake PASS, and every executable step is `SKIPPED` with reason `EXECUTION_GATED`. Forbidden claims (`MALWARE_FREE`/`SAFE`/`CLEAN`) are refused at construction — `runtimes.py:34 FORBIDDEN_CLAIMS`, `:42 _forbidden_claim`, asserted at `test_os_lab_runtimes.py:78`. |
| N5 | **MONEY_MODE / finance truth** | **PASS** | `MONEY_MODE` is **not declared** in App B `Settings`; readers default `MOCK`, so a reader default is explicitly **not** treated as an observation. Tri-state: `capabilities_answer.py:178-185` and `self_model.py:142-150` report **UNAVAILABLE when undeclared**, `MOCK` / declared-value when declared. `status.py:96` `_money_mode()` reads the ONE flag reader and returns `"UNAVAILABLE"` when undeclared. The FINANCIAL brake is derived from the REAL switches, not from MONEY_MODE: `brakes.py:246 _FIN_CONTROLS = ("KAI_SCOPE_SOL_TRANSFER", "DWOLLA_ENV", "DWOLLA_ALLOW_PRODUCTION", "DWOLLA credentials (presence only)")`, `:251-284`. Tests: `test_status` **8/8** (incl. "static: `status.py` writes neither literal 'MOCK' nor 'DISABLED' — both rows are derived"), `test_brakes` **63/63**, `test_capabilities_answer` **45/45**. |
| N6 | **No covert mic / camera** | **PASS** | **ONE** `getUserMedia` call site across the whole admin frontend: `frontend/admin/kai-gesture.js:90` (`{video: true, audio: false}` — audio never requested); statically asserted by `test_kai_gesture.js:109` (exactly one call site in the file) and `:117` (`getUserMedia( call sites: {"kai-gesture.js": 1}` across the whole admin frontend; `kai-presence.js` has none — also documented at `kai-presence.js:21/:41/:704`). **ONE** `voice.stt.start` call site: `kai-presence.js:789`. Trigger-blind public API: `kai-presence.js:173` — the public API can never name a trusted trigger; `:770` refuses a start without a live user activation unless the trigger is `ptt-press`/`session-button`, which are reachable only from the internal mic handlers. Backend truth, not UI optimism: `GET /admin/holding/voice/capabilities` and `/gesture/capabilities` (`routers/admin_holding_command.py:215/:229`) report the real `KAI_VOICE_ENABLED`/`KAI_CAMERA_ENABLED`, PTT default, `WAKE_WORD_LOCAL` UNAVAILABLE, `RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED`, indicator REQUIRED, inference LOCAL_ONLY — the frontend renders DISABLED-WITH-REASON from these. The NarAI covert always-on `core/wake_word_listener.py` remains disabled and unwired (ADR-003). **P8 privacy/authority/safety lens (fixes committed `9e0df08`)** hardened this further and proved the rest under attack: the policy gate + page visibility are re-read in the `getUserMedia` **resolve** handler — the one place every start funnels through — so a stop / sign-out / mute / tab-hide arriving during the async gap (lazy script load + `getUserMedia`) now stops the resolved stream and returns `STOPPED_DURING_START` (was: the camera turned ON afterwards, including inside an already-hidden tab); `!e.isTrusted` is refused on the §67 camera-enable control **and** on the mic press/keydown handlers that mint the activation-exempt `ptt-press`/`session-button` triggers, so a page script can no longer piggyback an unrelated real click (`efb05c6` had closed only the API leg); the mandatory CAMERA-ON banner is rebuilt when missing or `!isConnected`, so a detached node can no longer mean a live camera with no indicator. Proved clean under attack: exactly ONE `getUserMedia` site with zero frame/network/storage APIs near the stream; the live `MediaStream` is unreachable from the page (module scope); persisted `localStorage camera_enabled:true`, `KAI.settings.set({camera_enabled:true})` and `KAI.gesture.start()` are all neutralized; backend `camera_allowed` rejects truthy non-bools. Tests: `test_gesture_policy` **55/55**, `test_kai_gesture` **27** (three exercise the real async-gap race). |
| N7 | **Gestures / voice never authorize** | **PASS** | `approval_dialog.py:54` — `REFUSED_CHANNEL` = "voice/gesture cannot authorize (§75) → require typed confirm"; `:100` returns unauthorized. `voice_session.py:410-413` persists `APPROVAL_REFUSED_VOICE`. `routers/admin_holding_command.py:249/:256/:259` — `interaction_mode` is descriptive, the server derives the owner principal + channel, a forged role is not modeled (`extra="ignore"`), and voice/gesture confirmation fails CLOSED with no write. `kai-gesture.js:22` documents the same boundary client-side. Tests: `test_approval_dialog.py:51`, `test_voice_session.py:191`, `test_gesture_policy.py:139-144` (**55/55** at HEAD), `test_approval_dialog` **43/43**, `test_voice_session` **36/36**. **Attacked directly by the P8 privacy/authority/safety lens and held:** no gesture path reaches a consequential action — every vocabulary string, `'approve'`, prototype keys, a crafted event carrying its own `action`/`handler` property, string / `NaN` / `±Infinity` confidence, and non-owner roles all ran only the five injected non-consequential helpers; an approval over `channel=gesture` hits `REFUSED_CHANNEL` **before verb parsing** and writes nothing durable; `/gesture/capabilities` is owner-only and dormant; the `17ec7ce` backend gating of `registerRecognizer` holds. One seam-drift LOW was found and fixed in `9e0df08`: a `NaN` confidence beat every comparison and slipped past the threshold gate to be MAPPED while the frontend refused it as MALFORMED — `gesture_policy.map_gesture` now fails closed on non-finite values (`import math` + `isfinite`). |
| N8 | **KAI remains the brain (§165)** | **PARTIAL** | Declared and enforced within the OS Lab package: `os_lab/runtimes.py:327-376` `OsLabAuthorityGuard` / `GUARD` (an `os_lab:*` source may yield EVIDENCE only; authority actions → `REJECTED`, unknown → `REJECTED_UNKNOWN_ACTION`, fail closed); `catalog.py:39 AUTHORITY_PLANE = "KAI"`, `:176`; `certification.py:243 authority_plane = "KAI"`; `review_panel.py:21` (panel is ADVISORY, KAI is the final coordinator); `improvement_cycle.py:117`. **Gap:** `GUARD` has **no production caller** — grep for `OsLabAuthorityGuard` outside `os_lab/` returns nothing. Already recorded as gap #6 in `docs/KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md`. See §8 F1. |

---

## 4. FLAGS — DEPLOYMENT ≠ ENABLEMENT (§0 #12 / ADR-007)

All nine default `False` in `backend/app/config.py`. Verified by grep at `83f6050`; `config.py` is
untouched by `9e0df08`, `749fa78`, `ed00e4e`, `79062c4` and `8799db9` (`git diff --stat
749fa78..8799db9` touches only `os_lab/` + the OS-Lab doc), so the posture is unchanged at HEAD
`8799db9`.
`KAI_CAMERA_ENABLED` in particular is still `False` — the P8 privacy fixes hardened the path, they
did not enable it.

| Flag | Line | Default | Guards |
|---|---|---|---|
| `KAI_HOLDING_COMMAND_ENABLED` | `config.py:64` | `False` | typed Holding Command API (P5) |
| `KAI_VOICE_ENABLED` | `config.py:72` | `False` | VoiceSessionManager (P7a/P7b) |
| `KAI_CAMERA_ENABLED` | `config.py:79` | `False` | camera + gesture (P8) |
| `KAI_CYBER_OPS_ENABLED` | `config.py:83` | `False` | Cyber Ops Phase A/B |
| `KAI_HOLDING_CYCLE_ENABLED` | `config.py:101` | `False` | bounded cycle scheduling (grants NO authority) |
| `KAI_PROACTIVE_ENABLED` | `config.py:106` | `False` | proactive engine (P3b) |
| `KAI_CAPABILITY_EXECUTION_ENABLED` | `config.py:111` | `False` | brake #1 — capability execution |
| `HOLDING_AUTONOMY_ENABLED` | `config.py:115` | `False` | brake #2 — global autonomy |
| `KAI_A2_EXECUTION_ENABLED` | `config.py:128` | `False` | brake #3 — A2 prepare-only |

`MONEY_MODE` is **not declared** in App B `Settings` — see N5. Readers default `MOCK`; Phase 9
reports it **UNAVAILABLE** when undeclared and derives the FINANCIAL brake from the real Sol/Dwolla
switches instead.

---

## 5. REGRESSION EVIDENCE

**Per-module totals (runner output). os_lab re-measured at HEAD `8799db9`; the other rows measured
per-file at `749fa78` and carried forward on the `git diff --stat 749fa78..8799db9` evidence that the
three new commits touch only `os_lab/` — see the derivation note in §2.**

| Scope | Modules | Checks | Result |
|---|---|---|---|
| backend `holding/` + `os_lab/` | 67 | **1521** (1520 PASS) — fresh per-file sweep measured at HEAD `8799db9`; os_lab component 255→255 | PASS except one by-design fixture (below) |
| Phase-9 governance modules | 11 | **394** | PASS |
| Phase-10 `os_lab/` | 3 | **255** at HEAD `8799db9` (catalog **83/83** · runtimes **92/92** · certification **80/80**) — 226 at `749fa78` (76 · 87 · 63), 216 at `83f6050` (73 · 85 · 58) | PASS |
| Phase-8 `test_gesture_policy` | 1 | **55/55** at HEAD `9e0df08` — was 51/51 | PASS |
| Voice `test_voice_session` | 1 | **36/36** | PASS |
| Frontend node suites | 18 | **263** (`test_kai_gesture` **27** · `test_kai_speech_input` 11) — was 258 | PASS |
| UI contract `test_holding_ui_contract` | 1 | **7/7** | PASS (after `543da39`) |

**Known by-design / environment-dependent results — named, not hidden:**

- `test_si_calc_guard` `bucket(0)` **FAILS by design.** It is the deliberate BEFORE-state
  self-improvement fixture and fails **identically on the pre-omnipresence base `d881cf2^`** — it is
  not a regression introduced by this build.
- `test_brakes` is **63/63 with a reachable local Postgres, 62/62 without.** The difference is the
  single conditional `[db]` roundtrip check at `test_brakes.py:393` ("RELEASED roundtrip persists +
  reads back"), which only runs when a DB is reachable. Both totals are honest; neither is a failure.
- `test_certification` is **80/80 at HEAD `8799db9` (63/63 at `749fa78`, 58/58 before it) only when the repo root is on
  `PYTHONPATH`** (`PYTHONPATH=..:.`
  from `backend/`), because `certification.py:42` imports the shared core scanner table
  (`core.security_scanner._COMPILED_PATTERNS`). Without it the module sets `_CORE = None` and the
  five core-backed steps honestly report `UNVERIFIED` / note `core scanner table unavailable`
  (measured at the 58-check revision: 45/58, the 13 deltas being assertions that expect a core-table
  FAIL; the same harness requirement holds for the 63 at `749fa78` and the 80 at `8799db9`). This is the
  designed fail-closed honesty path, not a defect — but the documented harness
  (`docs/KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md` §3, `docs/KAI_OMNIPRESENCE_OS_LAB.md`) must be
  used or the count differs.

**Regression sweep — zero diff.** 133 test files outside `holding/` (`./tests` 60, `./backend/tests`
54, `backend/app/services/capability` 13, `./tests/api` 6 — covering capability, security, registry,
router, `nai_brain`, App B `tests/`, App A `tests/`) were run **per-file on `83f6050` and on
`d881cf2^`**: **ZERO diff**. None of `9e0df08`, `749fa78`, `ed00e4e`, `79062c4` or `8799db9` touches
any file outside `holding/` + `os_lab/` + `frontend/admin/kai-{gesture,presence}.js`, so the sweep
has **not** been re-run at `8799db9` — stated as fact, not extrapolated to a claim. The App B `tests/*.py` fixture errors (`admin_chat` 15, `auth` 16,
`browser` 59, `planning` 95, …) are **identical on the baseline** — pre-existing environment errors,
not regressions.

**Harness note (why per-file).** The zero-framework runners raise `SystemExit` at import, so a
single `pytest` run over the whole `app/` directory `INTERNALERROR`s. Per-file execution is the
harness (ADR-017). Each holding/os_lab test file is also a plain `python3` script.

---

## 6. ADVERSARIAL REVIEW LEDGER

| Phase | Lenses | Found | Fixed | Refuter | Status |
|---|---|---|---|---|---|
| P1–P7a | in-session review triads before each commit | — (recorded in git messages + `KAI_OMNIPRESENCE_EVIDENCE_MATRIX.md` seeded rows) | in the phase commits | — | **PASS** (pre-commit triad) |
| P7b voice frontend / embodiment / Nexus | 2 (workflow-run, structured) | 1 HIGH + 7 MED + 10 LOW | all fixed | **11/12 hold**; 1 MED (`voice.start` trigger passthrough) | fixed in **`efb05c6`** → **PASS** |
| P8 camera + gesture (consolidation lens) | 1 | 1 MED | `17ec7ce` (recognizer seam gated on backend certification truth) | — | **PASS** |
| P8 camera + gesture (privacy / authority / safety lens) | 1 | **FAIL — 5 findings: 2 HIGH + 2 MED + 1 LOW.** HIGH `privacy-camera-lifecycle` (`kai-gesture.js` `start()`: the gate was never re-validated after the async gap, so a stop / sign-out / mute / tab-hide arriving in that window was lost and the camera turned ON afterwards, including inside an already-hidden tab). HIGH `privacy-camera-activation` (`kai-presence.js` §67 control accepted script-dispatched events, so a page script piggybacking any unrelated real click could mint `'owner-click'` with the settings panel closed). MED `privacy-indicator` (the mandatory CAMERA-ON banner was cached — a detached node meant a live camera with no indicator). MED `privacy-mic-activation` (same untrusted-event root cause on the mic DOM path — code-path finding, **not** runtime-verified by the reviewer). LOW `input-validation` (`gesture_policy.map_gesture`: `NaN` beats every comparison, so a `NaN` confidence slipped past the threshold gate and was MAPPED while the frontend refused it as MALFORMED — seam drift). | **ALL 5 fixed `9e0df08`** | proved clean under attack: no gesture path reaches a consequential action (vocabulary strings, `'approve'`, prototype keys, crafted event with its own `action`/`handler`, string/`NaN`/`±Infinity` confidence, non-owner roles — only the five injected non-consequential helpers ever ran); approval over `channel=gesture` hits `REFUSED_CHANNEL` before verb parsing and writes nothing durable; `/gesture/capabilities` owner-only + dormant; exactly ONE `getUserMedia` site, zero frame/network/storage APIs near the stream; the live `MediaStream` unreachable from the page (module scope); persisted `camera_enabled:true`, `KAI.settings.set(...)` and `KAI.gesture.start()` all neutralized; the `17ec7ce` recognizer gating holds; backend `camera_allowed` rejects truthy non-bools | **CLOSED → PASS.** Post-fix: `test_gesture_policy` **51→55**, `test_kai_gesture` **22→27** (three tests exercise the real async-gap race), 18/18 frontend suites, `test_voice_session` **36/36**, `test_approval_dialog` **43/43** |
| P9 governance maturation | 2 (workflow-run, structured) | 3 HIGH + 8 MED + 4 LOW | `ac9fcff` | **8/9 probes hold**; 1 MED (MONEY_MODE reader default narrated) + 2 LOW | round-2 **`83f6050`** → **PASS** |
| P10 OS Lab (initial 2 lenses) | 2 (workflow-run, structured) | 1 HIGH + 8 MED + 7 LOW | `58a4227` | **all 16 requested probes HOLD**; 7 new (1 HIGH credential-snippet leak, 2 MED, 4 LOW) | → round 2. **This is where the credential leak opened.** |
| P10 round 2 — refuter of `58a4227` | independent refuter | 1 HIGH + 2 MED + 4 LOW. HIGH: credential-snippet findings **embedded the matched secret** and were truncated to 100 chars **before** `redact()` ran, so AWS `ASIA`/`AROA` key ids and ~**72 chars** of a long secret reached the report **and** the audited catalog history. | `749fa78` — snippet withheld when the **label** looked secret-named; clean verdict re-derived from the attached steps; walk-cap truncation honesty; `MappingProxyType` deep freeze; enum-safe verdict compare | HIGH re-verified before commit; suites 216→**226** | **BELIEVED CLOSED — IT WAS NOT.** Two of these fixes were themselves defective: the label-keyed boundary was bypassable, and the deep freeze introduced the round-3 regression. |
| P10 round 3 — refuter of `749fa78` | independent refuter, **128 assertions, 119 held, 9 failed** | **3 HIGH** + 1 MED + 1 LOW. **H1** the withholding keyed on the **label**, so a greedy pattern whose match **spanned** the secret still emitted it — a curl line with a custom auth header put **101 distinct 20-char windows** of a 120-char secret into the report. **H2** the severity gate failed **OPEN**: `'critical'`, `'Critical'`, `'crit'`, `9`, `None`, `['CRITICAL']` all certified. **H3 — A REGRESSION INTRODUCED BY ROUND 2:** `MappingProxyType` is not a `dict` subclass and `task_resolver.redact` dispatches on `isinstance(obj, dict)`, so the round-2 deep freeze **silently disabled redaction** of evidence written to the append-only history, and broke `dataclasses.asdict`. | `ed00e4e` — boundary moved to **match length** (>40 chars ⇒ withheld), removing the "which labels are secret-named" judgement from the leak boundary entirely; severity **fails closed** (unknown severities refused, no case-guessing); deep freeze replaced with a **mutation-refusing `dict` subclass** (`isinstance` stays True, `redact` traverses again, `asdict` works, mutation still raises `TypeError`); step ids must cover the pipeline; §165 guard `oslab` prefix-anchored | suites 226→**235** | **BELIEVED CLOSED — IT WAS NOT.** |
| P10 round 4 — refuter of `ed00e4e` | independent refuter, **201 assertions, 192 held** | **1 HIGH** + 3 MED + 1 LOW. HIGH: a `.gitmodules` submodule-URL **password was written verbatim** into step evidence and copied unredacted into the report artifact — while the finding text beside it **was** redacted, which is precisely what made it easy to miss. | `79062c4` — redacted **at the source AND at the door**: `StepResult.__post_init__` now stores `redact(evidence)`, so no future step can leak through that path. Plus malformed finding rows **refused** (not silently dropped), a credential **severity floor** at MEDIUM, the 20-char pre-context **dropped entirely**, and the `EXECUTED` ledger hardened to a read-only mapping read live | suites 235→**248** (catalog 83 · runtimes 92 · certification 73) | **BELIEVED CLOSED — IT WAS NOT.** |
| P10 round 5 — refuter of `79062c4` | independent refuter, **451 assertions, 439 held** | **1 HIGH** + 1 MED. HIGH: flooring the **severity** of the rows `credential_reads` already matched did nothing for a credential the tables never **matched at all** — a GitHub PAT, GitHub fine-grained PAT, Slack token, OpenAI key, GitLab PAT, bearer/authorization value, or credential-in-URL each left `credential_reads` **PASS**, while the module docstring **and** `docs/KAI_OMNIPRESENCE_OS_LAB.md` both asserted *"an embedded credential can never leave it PASS"*. **That claim was false as written — a zero-fabrication violation independent of the detection quality.** | `8799db9` — the seven families added to `_CRED_MATERIAL`, each proved to **FAIL** the step with **no window of the secret in the report**; the claim **restated** to the true, narrower one (per **listed** family) and the gap named as residual **R7** rather than left silent | suites 248→**255** (catalog 83 · runtimes 92 · certification **80**) | **CLOSED.** Round 5's remaining output is a **bounded, named residual (R7)**, not a reachable defect — which is the stopping rule (ADR-024). |

**No refuter is outstanding, and no cell in this doc set defers to one.** Four
independent refuter rounds ran against the P10 credential-leak line, each attacking the *previous
round's fix*, and each found a genuinely new route to the same class of defect: label-keyed
withholding bypassed by a greedy match, a severity gate failing open, a self-inflicted regression
that silently disabled redaction, a submodule-URL password written verbatim into evidence, and seven
credential families the tables never matched at all — **four HIGH defects plus one regression that a
single-pass review had passed as clean.** The line closed at `8799db9` when the round's output was a
bounded named residual (**R7**) rather than a reachable defect. The P8 privacy/authority/safety lens
is likewise CLOSED (verdict FAIL, all 5 findings fixed in `9e0df08`). **R7 is not a review cell to
close; it is a standing limitation** — recorded at §8 F6 and in N1, and it is why N1 reads PARTIAL.

---

## 7. HONEST NOT-BUILT / NOT-RUN

Verbatim, so nothing reads as more finished than it is:

- **No gesture recognizer model.** The seam reports `RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED`; any model
  must pass capability/manifest supply-chain certification first.
- **No local wake-word engine.** `WAKE_WORD_LOCAL` is UNAVAILABLE; the covert NarAI mic listener
  stays disabled.
- **OS Lab: nothing cloned, downloaded, installed, built, or QEMU-booted.** Catalog + lifecycle +
  static-only certification pipeline. Ultron source is **OPERATOR-STATED, UNVERIFIED**.
- **Credential detection is not proof (R7).** `credential_reads` FAILs on a **listed** family only —
  the core rows plus the round-5 additions. A secret in an unlisted shape still leaves the step
  `PASS`. This is the narrow claim that replaced the false universal one at `8799db9`; it is the
  reason N1 reads PARTIAL. Bounded by: a static-only report never certifies — the clean verdict also
  needs full pipeline coverage and `executed` `build`+`qemu_boot` true, which this phase cannot
  produce.
- **GLB avatar `ASSET_UNAVAILABLE`** (`kai-avatar-driver.js:5/:95/:101`) → video fallback.
- **No isolated Railway staging exists** — this blocks any authority-enable and any hosted
  certification.
- **Brakes board / OS-lab view / gesture caps**: the §165 guard is **not yet wired into the execution
  seams** (documented — see §8 F1/F2).
- **Cyber Ops phases C–F not built.**
- **Finance / customer data provisioning not done** — `report_value` → UNAVAILABLE.

---

## 8. KNOWN LIMITATIONS + FOLLOW-UPS

Each row was verified with grep/ls at HEAD before being listed (`83f6050` originally, re-checked at
`749fa78` for the rows the two new commits touch).

| # | Limitation | Verified by | Severity | Follow-up |
|---|---|---|---|---|
| F1 | **§165 `OsLabAuthorityGuard` guards nothing live.** `GUARD` (`os_lab/runtimes.py:376`) has no production caller; grep for `OsLabAuthorityGuard` outside `os_lab/` returns nothing. Exercised by tests only. | grep (re-checked at `749fa78`) | MED (by design — Phase 10 is catalog-only) | Wire at the first real `os_lab:*` evidence-consumption seam, before any OS Lab execution step. Already gap #6 in `KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md`. **`749fa78` normalized the guard's action matching (fail-closed), but did not wire it** — still no caller outside `os_lab/`. |
| F2 | **No HTTP surface for the brakes board or the OS-lab view.** `brakes.brakes()` (`brakes.py:359`) and `os_lab.runtimes.os_lab_view()` (`runtimes.py:459`) have **no** router caller — grep of `backend/app/routers/` finds only `/gesture/capabilities` and `/voice/capabilities` from the Phase-8/7b cluster. Only `stop_state` is consumed at execution seams (`holding_cycle.py:48`, `a2_dispatch.py:46`). | grep of `backend/app/routers/` (re-checked at `749fa78` — still no router caller) | MED | Add owner-gated read endpoints alongside the 12 P6b-1 routes when the §97 board is surfaced on `/admin/holding`. |
| F3 | **`/admin/holding` is served via `FileResponse`** (`core/api.py:947-953`), which **skips** `_inject_kai_presence` (`core/api.py:1348`), so `holding.html` must carry its own presence tags — it does: `holding.html:5` (`kai-presence.css`) and `:1172` (`kai-presence.js` module). | read | LOW (working as intended, but fragile) | Keep the two tags pinned by a UI-contract check, or move the route to `HTMLResponse(_inject_kai_presence(...))` like the five other admin pages. |
| F4 | **Double-escaped evidence subtitle (cosmetic).** `holding.html:528` applies `esc(meta.subtitle)`, while callers at `:640`, `:673` and `:778` already pass `esc(...)` into `subtitle`. Entities render literally (`&amp;`) for subtitles containing `& < >`. No injection risk — it escapes twice, never zero times. | read | LOW | Drop the `esc()` at the call sites, or at `:528`; keep exactly one. |
| F5 | **Dead CSS `.kaip-vsel` / `.kaip-vlab`.** Present only in `frontend/admin/kai-presence.css` (`:121`, `:123`, `:124`, `:125`, `:137`, `:201`, `:202`); no JS or HTML emits either class. | grep across `frontend/` + `backend/` | LOW | Delete, or emit the voice-select control the rules were written for. |
| F6 | **Credential material reaching the certification report — CLOSED at `8799db9` after FIVE rounds, not one.** Opened by the refuter of `58a4227`: findings **embedded the matched secret** and were truncated **before** `redact()`, so AWS `ASIA`/`AROA` key ids and ~72 chars of a long secret reached the report and the audited history. **It was believed closed at `749fa78` and it was not.** Round 3 (`ed00e4e`) showed the label-keyed withholding was bypassed by a greedy match spanning the secret (**101 distinct 20-char windows** of a 120-char secret in the report) and that the severity gate failed **open**; round 4 (`79062c4`) found a `.gitmodules` submodule-URL **password written verbatim into step evidence** and copied unredacted into the report artifact, with the finding text beside it redacted — which is what made it easy to miss; round 5 (`8799db9`) found seven credential families the pattern tables **never matched**, leaving `credential_reads` PASS while the code and docs claimed otherwise. **This row is deliberately not struck through: three intermediate "resolutions" of it were wrong, and a ledger that presents this as a one-shot fix would misrepresent how it was actually found.** | four independent refuter runs (128/119, 201/192, 451/439 assertions held on rounds 3/4/5) → fixes `749fa78` → `ed00e4e` → `79062c4` → `8799db9`; each round's HIGH re-verified before its commit; `test_certification` **80/80**, os_lab **255** at HEAD | **CLOSED as a reachable defect** (was HIGH) — but see **R7** below, which is what remains | The leak path is closed at the source and at the door (`StepResult.__post_init__` redacts `evidence` at construction). What is **not** closed is R7: `credential_reads` is a **pattern list, not proof**, so a secret in an unlisted shape still leaves the step PASS. R7 is recorded in `docs/KAI_OMNIPRESENCE_OS_LAB.md` §residuals and is the reason **N1 reads PARTIAL, not PASS**. Bounded by: nothing certifies on a static-only report — the clean verdict also requires full pipeline coverage and an `executed` ledger with `build`+`qemu_boot` true, which this phase cannot produce. Adding a family is one regex plus one test row; re-check the list whenever a new token format matters. |
| F6a | **A fix in this line introduced a worse defect than it closed — recorded, not buried.** Round 2 (`749fa78`) deep-froze `executed`/`evidence` with `MappingProxyType` to stop the "nothing was built or booted" ledger being flipped in place. But `MappingProxyType` is **not a `dict` subclass**, and `task_resolver.redact` dispatches on `isinstance(obj, dict)` — so the freeze **silently disabled redaction of evidence written to the append-only history**, and additionally broke `dataclasses.asdict`. It was self-inflicted by a hardening change, it was silent (no error, no failing test at the time), and it made the very leak F6 was about **more** likely, not less. Found only by the round-3 refuter (`ed00e4e`); a single-pass review had passed round 2 as clean. | refuter of `749fa78` (H3 of 3 HIGH) → fix `ed00e4e` | **CLOSED** (was HIGH) — regression window `749fa78`..`ed00e4e`, both undeployed | Fixed by replacing the proxy with a **mutation-refusing `dict` subclass**: `isinstance(obj, dict)` stays True so `redact` traverses it, `asdict` works, and mutation still raises `TypeError`. Standing lesson (ADR-024): **a security fix can introduce a worse defect than it closes**, and a type substitution that changes `isinstance` behaviour must be checked against every dispatch site that keys on the old type — `grep` for `isinstance(.*dict)` before swapping a mapping type. |
| F7 | **STOP does not preempt.** It refuses NEW consequential work (next `build_live_engine` / A2 enqueue); claimed/running jobs run to completion or lease expiry. | `brakes.py` docstring + `holding_cycle.py:44-47` | MED (documented, accepted) | Accepted for this build; revisit only if in-flight kill becomes a requirement. |
| F8 | **`neutralize_untrusted_context` has exactly ONE call site** (`nai_brain/brain.py:77`). Any new prompt-composition path is unfenced unless it routes through it explicitly. | `KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md` gap #5 | MED | Make it a required step of any new prompt-composition seam. |
| F9 | **No OS-level protection domain; ambient credentials; per-operation (not per-process) egress guard; coarse human roles.** | `KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md` gaps #1–#4 | MED (accepted, documented) | Out of scope for this build; each closure needs a named enforcement point + a check, never a prose promise. |

---

## 9. OPERATOR GATES + EXACT NEXT STEPS

Strictly in order. KAI passes none of these.

1. **G1 — Provision an isolated Railway staging environment.** Separate project/services from App A
   (`wheellsverse-v2`) and App B (`kai-prod`); separate Postgres/Redis; no production credentials.
   This is the standing blocker (baseline OQ #6, ADR-007, MEMORY). Nothing downstream can start
   without it.
2. **No review cell is open — carry R7 forward instead.** Both former blockers are **done**: the P8
   privacy/authority/safety lens is closed (FAIL → 5 findings → all fixed in `9e0df08`;
   `test_gesture_policy` **55**, `test_kai_gesture` **27**), and the P10 credential-leak line is
   closed at `8799db9` after **four independent refuter rounds** (os_lab **255**, with
   `PYTHONPATH=..:.`). Nothing is waiting on a commit and no refuter is in flight. What carries
   forward is the **named residual R7** (credential detection is a pattern list, not proof — §8 F6,
   N1). R7 does not block G1, and it does not block G2 as a *defect*; it does mean the G2 report must
   state the credential guarantee in its narrow, per-listed-family form and must not restate the
   claim round 5 had to retract.
3. **G2 — Hosted-edge certification on staging.** Follow
   `docs/KAI_ADMIN_MERGE_HOSTED_EDGE_AND_PROD_RUNBOOK.md`. Certify with **every** flag in §4 still
   `False` first: the dark-build posture must be provable on a hosted edge before any flag moves.
4. **G4 — Enable by flag, ONE at a time, on staging only.** Suggested order, least authority first:
   `KAI_HOLDING_COMMAND_ENABLED` → `KAI_VOICE_ENABLED` → `KAI_CAMERA_ENABLED` →
   `KAI_HOLDING_CYCLE_ENABLED` → `KAI_PROACTIVE_ENABLED` → `KAI_CYBER_OPS_ENABLED`. The three brakes
   (`KAI_CAPABILITY_EXECUTION_ENABLED`, `HOLDING_AUTONOMY_ENABLED`, `KAI_A2_EXECUTION_ENABLED`) are
   last and separate. After each single flag: re-certify, confirm the dashboard reflects the new
   exists/deployed/enabled state, then stop.
5. **G5 — Credential provisioning** for the finance/customer sources (§45/§46, OQ #5). Its former
   precondition, F6 (the certification reporter leaking credential material), is **closed in
   `8799db9`** — after five rounds, not the one round `749fa78` was believed to be; G5 itself remains
   an operator gate, and R7 is a standing caveat on it.
6. **G3 — Production merge / deploy go-ahead.** Open the PR from `feat/kai-cyber-operations` only
   once steps 1–4 pass on staging. Deploy dark; **deploy is not enable** (ADR-007). Re-run the
   4-viewport Playwright certification against production after deploy, with all flags still off.
7. **G6 — Restricted-security activation** (§43 syzkaller / OS Lab execution) is a separate, explicit
   authorization. syzkaller is never auto-selected; OS Lab execution additionally needs isolated
   infra plus a passing supply-chain certification, and adoption needs a §117 `GapJustification`
   recorded by the operator.

**Operator authorizations already recorded (2026-09-04 ~04:10 ET):** build camera + gesture
(§8/§94); `WAKE_WORD_LOCAL` (§6); OS Lab (§39–44) DARK; §160 autonomous execution directive; "Deploy
App A now" (release #67 only). None of these authorize a deploy, a merge, or an enable of anything in
this build.

---

## 10. CERTIFICATION STATEMENT

At HEAD `8799db9` on `feat/kai-cyber-operations`, the Omnipresent Holding Command OS build is
**PRE-PRODUCTION CERTIFIED — DARK BUILD (undeployed, nothing enabled)**. It is **NOT
production-certified** and has **NOT been deployed to production**; gates G1–G6 remain.

Of the two adversarial-review cells that were open at `83f6050`, both are now closed in code. The P8
privacy/authority/safety lens returned FAIL with 5 findings, all fixed in `9e0df08`. The P10
credential-leak line took **five rounds** — `cd3b96d` → `58a4227` → `749fa78` → `ed00e4e` →
`79062c4` → `8799db9` — and every intermediate round genuinely believed it was done. Four
independent refuters, each attacking the previous round's *fix*, found **four HIGH defects and one
self-inflicted regression** (`749fa78`'s `MappingProxyType` freeze silently disabling `redact()`)
that single-pass review had passed as clean. **No refuter is in flight.**

**Non-negotiable N1 is PARTIAL, not PASS.** The credential-exposure controls are verified for the
listed families with refuter evidence, but residual **R7** — credential detection is a pattern list,
not proof — means the guarantee is per-family, not universal. Round 5 exists precisely because a
universal claim was written down and was false; this statement does not repeat it. The certified
floor — release #67, SHA `4fbfb8e` — is unchanged by this work.
