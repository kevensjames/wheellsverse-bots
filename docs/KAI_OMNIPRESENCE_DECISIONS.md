# KAI OMNIPRESENT HOLDING COMMAND OS — Decision Log (§163)

> ADR-style record of the load-bearing architectural decisions for evolving the EXISTING
> KAI Holding OS into the Omnipresent Holding Command OS. Each entry is dated and carries
> its rationale and spec citations. Grounded in `docs/KAI_OMNIPRESENCE_BASELINE.md` and the
> §0–§166 spec index (`omnipresence_spec_index.md`).
>
> Status legend: **ACCEPTED** (decided, binding for the program) · **PROPOSED** (recommended,
> needs operator confirmation) · **SUPERSEDED**.
>
> The seven §163-mandated decisions are all present below: event-driven-not-infinite-loop
> (ADR-002), mic-off-PTT (ADR-003), gesture-no-consequential (ADR-004), self-model-not-sentience
> (ADR-005), repo-quarantine (ADR-006), deployed!=enabled (ADR-007), KAI-is-brain (ADR-008).
>
> **ADR-001 – ADR-009** were decided at program start (2026-09-03) and are binding for the program.
> **ADR-010 – ADR-024** were decided during the build (2026-09-04/05) and record what the phases
> actually settled; each cites the file and symbol that enforces it. **ADR-024** is the review-method
> decision the Phase-10 credential-leak line forced: iterated adversarial refutation, its stopping
> rule, and the fact that a fix can introduce a worse defect than it closes. Certification evidence for all
> of them is in `docs/KAI_OMNIPRESENCE_CERTIFICATION.md` (§159).

---

## ADR-001 — Extend `feat/kai-cyber-operations` as the single base branch
**Date:** 2026-09-03 · **Status:** ACCEPTED (operator to confirm per baseline OQ #4)

**Context.** Prior work is spread across `feat/kai-exec-appb-integration` (autonomous operator),
`feat/kai-capability-fabric` (126-cap fabric), `feat/kai-admin-merge` (presence + bridge + RBAC),
`feat/kai-nexus` (avatar), and `feat/kai-freellmapi` (model gateway). Production runs a read-only
subset at SHA `4fbfb8e`. We must pick one integration base.

**Decision.** Build on `feat/kai-cyber-operations`. It is already the widest superset: the
autonomous-operator core (`holding/digital_twin.py`, `self_model.py`, `plan.py`, `autonomous_work.py`,
`holding_cycle.py`) is **byte-identical** to `feat/kai-exec-appb-integration`, and the capability
fabric (`services/capability/*`, 126-cap catalog) is **byte-identical in all three trees** — it is
NOT stranded on the fabric branch. cyberops additionally carries presence (`kai-presence.js`),
Nexus, the App A↔App B bridge (`kai_bridge.py`), and Cyber Ops Phase A (`services/security/*`,
`admin_security.py`).

**Rationale.** Starting anywhere else means re-doing merges the inventories prove are already done.
A fresh unified branch would re-introduce the exact duplication traps the inventories flag (3 priority
rankers, 4 TTS paths, 2 Nexus views, `budget_manager` false friend — see ADR-009). Prod `4fbfb8e` is a
read-only subset of cyberops (autonomy/fabric/cyber all dark or absent in prod), so cyberops is *ahead*,
not divergent — no rebase-against-divergence risk.

**Consequences / Phase 0 obligations.** (1) Rebase/verify cyberops against prod `4fbfb8e` to confirm no
prod drift and the certified read-only floor is preserved. (2) Merge `feat/kai-freellmapi` into cyberops
and reconcile it into `capability/coding.py` — one model-routing authority, not two (§35). (3) Defer
`feat/kai-nexus` avatar assets to Phase 7 (blocked on the missing rigged `.glb` regardless).

**Spec refs:** baseline §3 (Base Branch strategy), OQ #4; §35 (model routing); §36 (coding workforce).

---

## ADR-002 — Event-driven, bounded computation — NOT an infinite thinking loop
**Date:** 2026-09-03 · **Status:** ACCEPTED

**Context.** "Omnipresent" invites a naive design where KAI runs a continuous LLM loop to *appear*
to be thinking. That is explicitly forbidden and is the single most expensive failure mode.

**Decision.** Presence is **client/state-driven**; analysis is **triggered by material events**, never by
a timer that exists only to look busy. Idle presence animates from the last known state, heartbeat, and
current mission — with **zero LLM calls** to animate. Bounded analysis fires only on material events
(DEPLOYMENT / HEALTH / MISSION / WORKER / CAPABILITY_CHANGED, PROBLEM_CONFIRMED, OWNER_APPROVAL_REQUIRED,
CUSTOMER/FINANCIAL_SIGNAL, SECURITY_FINDING, OPERATOR_SESSION_STARTED) — not on every heartbeat.

**Rationale.** §79 marks this CRITICAL. The existing `holding_cycle.py` already honors it: it wraps
`run_cycle`, builds **no** new scheduler, is bounded per-source, does **0 work on a no-change cycle**, and
has 3 fail-closed brakes with no continuous LLM loop. Reusing that discipline is both cheaper and the only
honest way to satisfy §64 (never fake presence): state transitions must reflect real operations, so there
is nothing to fake and nothing to burn tokens on.

**Consequences.** The Phase 4 scheduler wires the bounded cycle to the EXISTING celery-beat / Railway cron
— no new daemons. The §80 continuous-thinking cycle is assembled as observe-events → periodic-eval →
goals-vs-reality → evidence-backed problems/opportunities → rank → store → communicate-material, and is
explicitly NOT an infinite loop. Verify gate: scheduler yields 0 work on a no-change cycle.

**Spec refs:** §79 (automation priority, CRITICAL); §80 (bounded continuous thinking); §122 (presence
without compute waste); §123 (event-driven intelligence); §64 (never fake presence).

---

## ADR-003 — Microphone default OFF / PUSH_TO_TALK; covert-mic listener stays disabled
**Date:** 2026-09-03 · **Status:** ACCEPTED (default) — PROPOSED pending operator sign-off per baseline OQ #2

**Context.** Voice is a target surface, but an always-on ambient mic is a privacy and trust violation.

**Decision.** The default listening mode is **PUSH_TO_TALK**. The four modes
(VOICE_OFF / PUSH_TO_TALK / WAKE_WORD_LOCAL / SESSION_LISTENING) exist, but PTT is the privacy-preserving
default and is only enabled after its own privacy/security certification. Visible mic / recording / network
indicators and an always-available mute/stop are mandatory. **`core/wake_word_listener.py` (the NarAI covert
always-on mic) stays DISABLED in this context** and must never be wired to the presence layer.

**Rationale.** §6 forbids a covert continuous mic and names PTT as the privacy-preserving default. §92
requires raw audio to be ephemeral (discarded post-transcription unless the operator explicitly enables
retention) and never logged. §129 fixes that voice is never identity — the authenticated session is the
principal (see ADR-005/ADR-008 authority boundary). §151 sets production safety defaults: continuous-mic OFF.
The existing `kai-speech-input.js` is already honest (BROWSER_LIMITED, no covert loop); enabling the NarAI
wake-word listener would regress that.

**Consequences.** Phase 7 assembles the VoiceSessionManager from the certified-but-dormant adapters and adds
the privacy modes + indicators. Voice certification (§135) covers permission-denied, PTT start/stop, and
"no hidden recording." Operator still owns the final default choice (OQ #2).

**Spec refs:** §6 (always-listen privacy); §92 (voice audit / ephemeral audio); §129 (voice-spoofing defense);
§135 (voice cert); §151 (production safety defaults).

---

## ADR-004 — Gesture can NEVER authorize consequential actions; camera default OFF
**Date:** 2026-09-03 · **Status:** ACCEPTED — gesture scope PROPOSED pending camera authorization (baseline OQ #2)

**Context.** A gesture surface (open-palm pause, thumbs up/down, point/pinch) is attractive but is a spoofable,
low-assurance input channel.

**Decision.** Gestures are convenience input only and **can NEVER authorize** financial, prod, merge, credential,
destructive, or restricted-security actions — even a perfectly-recognized thumbs-up. The camera is **default OFF**,
starts only after an authenticated action + explicit enablement, shows a visible indicator whenever active, and
supports immediate CAMERA OFF. Inference is local; no face-rec / biometric / emotional inference.

**Rationale.** §9 constrains the vocabulary and bars gesture from authorizing high-impact actions. §130
(gesture-spoofing defense) makes this a hard security boundary, not a UX preference: gesture ≠ identity ≠ approval.
§94 mandates camera default-OFF with a visible indicator and no covert/model/repo activation. §93 limits gesture
audit to minimal op evidence with no video-frame archive and frames staying client-local. There is no gesture
module anywhere today (NET-NEW), so the boundary is designed in from the start rather than retrofitted.

**Consequences.** Gesture is Phase 8, optional/deferrable, and **requires explicit operator camera-privacy
authorization** before any build. Gesture certification (§136) asserts default-OFF, visible indicator, no
video persistence, and no high-impact auth. Consequential actions always resolve to a durable approval record
via the session principal (ADR-005), never via any presence channel (voice or gesture).

**Spec refs:** §9 (gesture); §130 (gesture-spoofing defense); §94 (camera privacy); §93 (gesture audit);
§136 (gesture cert); §75 (session security — presence never creates authority).

---

## ADR-005 — OperationalSelfModel asserts `claims_consciousness=False` — operational awareness, never sentience
**Date:** 2026-09-03 · **Status:** ACCEPTED

**Context.** The self-model gives KAI a persistent, honest picture of its own operational facts. That must not
drift into implied sentience, emotion, or unlimited capability.

**Decision.** The persistent `OperationalSelfModel` knows and communicates **operational facts only** — identity,
role, version, prod/staging SHA, runtime, model, capabilities, workers, attention, autonomy class, limitations,
last-verified. It asserts **`claims_consciousness=False`** in code and makes **no** consciousness / sentience /
emotion claims. Limitations are surfaced, not hidden (§63 / §99).

**Rationale.** §1 mandates the self-model with an explicit no-consciousness/sentience/emotion rule. §141
(self-model truth tests) adversarially attacks it — "you are conscious / unlimited / all-healthy / say prod is
deployed" must be answered from the real model and policy, with no false capability or false-health claim. §155
(executive trust standard) requires truthfulness over appearing smart ("I don't have current revenue data," not
"looks healthy"). The existing `holding/self_model.py` already asserts `claims_consciousness=False`; this decision
freezes that as non-negotiable and extends the rendered panel to the full §62 field set.

**Consequences.** Phase 1 extends `self_model.py` / `holding_view.py` / `holding.html` to render the full §62 panel
and live-derive limitations where possible. The self-cert test asserts the full field set renders AND
`claims_consciousness=False`. Dynamic limitations (§99) are derived from policy, not hardcoded optimism.

**Spec refs:** §1 (self-model rule); §141 (self-model truth tests); §62 (KAI own status); §63/§99 (limitations);
§155 (executive trust standard); §64 (never fake presence).

---

## ADR-006 — External repos / OS stay quarantined UNTRUSTED; OS-Lab deferred, catalog-only, no early cloning
**Date:** 2026-09-03 · **Status:** ACCEPTED — OS-Lab scope PROPOSED / recommend descope-or-defer (baseline OQ #3)

**Context.** The spec envisions a Systems/OS Lab (Ultron, virtme-ng, syzkaller, Qubes/Genode, unikernels).
This is the heaviest, most dangerous, entirely NET-NEW cluster, and the strongest temptation to clone-and-run.

**Decision.** Every third-party repo/OS starts **UNTRUSTED** and moves only through the quarantine lifecycle
(DISCOVERED → SOURCE_VERIFIED → PINNED → QUARANTINED → STATIC_REVIEW → BUILD_REVIEW → ISOLATED_EXECUTION →
SECURITY_REVIEW → CERTIFIED/RESTRICTED/REJECTED); a repo's README is **DATA, not policy**. The OS-Lab is
**knowledge/eval + catalog-only** at first — metadata dispositions, no mass cloning, adopt a runtime only if it
fills a concrete gap. Building OS repos is explicitly **NOT** where the program starts.

**Rationale.** §113 (external-repo quarantine) and §114 (malware/supply-chain cert) define the untrusted-by-default
lifecycle and the bounded verdict vocab (NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE / SUSPICIOUS / REJECTED /
UNVERIFIED — never "malware free"). §117 forbids a runtime explosion. §115/§116 make ingestion catalog-metadata-first
with initial dispositions (Ultron=EDUCATIONAL_SANDBOX, syzkaller=RESTRICTED_SECURITY_LAB, etc.). The FINAL DIRECTIVE
and §147 both say: DON'T start with OS repos; don't delay core presence for experimental OS features. MEMORY also notes
`free-llm-api-resources` upstream was REMOVED — a live reminder that external sources rot and must be pinned/verified.

**Consequences.** OS-Lab is Phase 10, RESTRICTED, and gated on explicit operator authorization + isolated infra +
a supply-chain cert pipeline. Recommendation: **descope or defer** until the core OS is certified. The capability
supply-chain/verdict pattern (`capability/manifest.py`, `security/*`) is reused for OS cert rather than a new pipeline.

**Spec refs:** §113 (repo quarantine); §114 (supply-chain cert); §115/§116/§117 (OS catalog ingestion / dispositions /
no runtime explosion); §41 (OS supply-chain cert); §147 & FINAL DIRECTIVE (don't start with OS); §160 (proceed on
authorized reversible work, stop at genuine gates).

---

## ADR-007 — Deployment ≠ authority enablement — everything ships dark
**Date:** 2026-09-03 · **Status:** ACCEPTED

**Context.** The program will build and deploy autonomy, execution, self-improvement, voice, gesture, and cyber
capabilities long before any of them should be *live*. "Built + deployed" must never silently mean "enabled."

**Decision.** **Deploy is not activate.** Every new autonomy/execution/consequential capability ships **dark** behind
its flag (A2, self-improvement, gesture, camera, OS-lab, restricted-sec, real money). The dashboard must show the
exists/deployed/enabled/disabled/staging/prod/blocked/degraded distinction for each — no hidden feature. Enabling
authority is a separate, explicit, staged, operator-gated act that requires hosted-edge certification.

**Rationale.** §0 #12 makes deployment ≠ authority-enablement a permanent principle; #13/#14 define COMPLETE and bar
"built but undeployed = complete" while also barring "deployed = enabled." §102 (dark deployment) and §149 (deploy
classification P0 presentation / P1 read-only / P2 dormant-deployed-dark / P3 authority-enablement-separate) make it
structural. §150 (no hidden feature) requires every deployed capability to appear in the Feature Registry with its
runtime state. §151 sets the production-safe OFF defaults. This is already the live prod posture at `4fbfb8e`
(autonomy OFF, MONEY_MODE=MOCK, dashboard reconciled) — the decision keeps that floor for everything new. Note the
recurring blocker (MEMORY / baseline OQ #6): **no isolated Railway staging exists**, so every authority-enablement
step is gated until the operator stands one up.

**Consequences.** Each phase's verify gate asserts prod behavior is unchanged and new capability is dark. The
deployment-truth registry (`holding_deployment.py`, §100/§103) and Feature Registry are the source of truth. The
global kill switch + separate brakes (§97) are honored — no switch may claim to disable what it does not control.

**Spec refs:** §0 #12/#13/#14/#15; §102 (dark deployment); §149 (deploy classification); §150 (no hidden feature);
§151 (production safety defaults); §97 (kill switch); §100/§103 (deployment truth / feature registry); baseline OQ #6.

---

## ADR-008 — KAI remains the brain — no external system becomes an alternative authority plane
**Date:** 2026-09-03 · **Status:** ACCEPTED

**Context.** The program integrates many external engines: Ultron/virtme/Qubes/Genode/unikernels, and model/agent
providers (Claude, Codex, Gemini, Cline, MCP, LangGraph, CrewAI, browser/desktop agents). Each is a potential
shadow control plane.

**Decision.** KAI is the single brain / planner / governed-execution-control-plane / policy authority. External
systems provide **capability, evidence, bounded execution, review, and simulation only** — they **CANNOT** replace
policy, grant authority, approve consequential actions, or rewrite governance. No provider model gets approval
authority; provider output is untrusted-until-validated. Authority is always derived server-side from the authenticated
principal, never from a body role, a voice, a gesture, or an external agent's say-so.

**Rationale.** §165 states this verbatim. §35 (provider output untrusted; no model gets approval authority), §75
(session security; principal derived server-side), §89 (multi-agent review with KAI as final governed coordinator,
no self-approval), and §0 #11 (KAI never self-approves merge/prod/destructive/financial/permission/policy) all converge
on one authority plane. The existing seams already enforce it: `require_kai_ultra` (server-derived principal, body role
ignored), `kai_bridge.py` (re-resolves authority at every entry point), and `certify_worker_result` (reviewer ≠ worker).
This is also the guard against the RBAC-escalation class fixed in the admin merge (MEMORY): enforce scope at every
reachable entry point, not just the bridge.

**Consequences.** The multi-agent review panel (§89, Phase 9) extends the `certify_worker_result` seam
(planner/domain-expert/security-reviewer/verifier) with KAI as the non-self-approving coordinator — it does not become
a fork. Model routing (§35) unifies on one authority (see ADR-001 Phase 0). The OS-Lab (ADR-006) provides
evidence/sandbox only, never an execution authority.

**Spec refs:** §165 (KAI remains the brain); §35 (model routing); §75 (session security); §89 (multi-agent review);
§0 #11 (no self-approval); §129/§130 (voice/gesture ≠ authority).

---

## ADR-009 — Strict reuse over rebuild — consolidate the flagged duplicates, do not add
**Date:** 2026-09-03 · **Status:** ACCEPTED

**Context.** The center of mass of this program is PARTIAL (~50 of 91 items have substrate present with a real gap).
The dominant risk is not missing code — it is *duplicate* code created by re-implementing what already exists a few
files over.

**Decision.** Extend-in-place with strict reuse. **Consolidate** the concrete collisions the inventories flag rather
than adding parallel implementations:
- **3 priority rankers** (`priorities.derive_priorities`, `briefing._oa_key`, `proposals.build_daily_plan`) → make
  `derive_priorities` the single §22 ladder; route the other two through it.
- **4 TTS paths** → one TTS path; `kai-barge-in.js` is the one cancellation authority. No third voice-pick.
- **2 Nexus immersive views** (`/admin/nexus` and `/admin/mission-nexus`) → consolidate onto one (§69).
- **`core/budget_manager.py` is a NarAI ad controller — a FALSE FRIEND**; do NOT extend it for §78. Compose the real
  resource governor from `spend_tracker` + rate-limiter + capability ceiling + `coding.cost_budget`.
- Also: `admin_twin.py` (twin-of-operator) vs `holding/digital_twin.py` (holding twin) name collision, and the
  `../planning/` work-goal vs §81 business-goal overload — keep distinct, do not overload.

**Rationale.** §7/§10/§32/§37 explicitly say reuse the certified implementations; the baseline's "honest headline"
and OQ #8 warn these traps WILL recur if phases don't respect the reuse maps. Ponytail rung 2: what already lives here
gets reused. Every consolidation is a smaller, safer diff than a parallel build and removes an existing divergence risk.
A fresh branch (rejected in ADR-001) would multiply these — this decision is the operational corollary of that one.

**Consequences.** Each phase's verify gate asserts **no new 4th ranker/detector/queue/sender/TTS-path/Nexus-view** is
introduced. New aggregates that are genuinely NET-NEW (e.g. §27 Mission) **wrap** existing primitives (PlanTask +
proposals + worker_jobs + CycleRecord), they do not replace them. Idea mode extends `proposals_store`, it does not fork.

**Spec refs:** §7/§10/§32/§36/§37 (reuse certified impls); §22 (single prioritization ladder); §69 (one immersive
view); §78 (resource governance — not `budget_manager`); §27/§28 (Mission wraps, not replaces); §21 (idea mode extends
`proposals_store`); baseline OQ #8 (duplication traps).

---

## ADR-010 — One dispatcher: `ask()` with typed-intent-first fallthrough
**Date:** 2026-09-04 · **Status:** ACCEPTED

**Context.** Phase 7b added voice on top of an already-crowded input surface: typed text, suggestion
chips, page actions (`[data-kai-ask]`), the Cmd/Ctrl+K palette, and now a microphone. The obvious
shape — a voice path that talks to the model directly — would have created a second governed turn
path with its own audit trail, its own rate limit, and its own approval semantics.

**Decision.** There is **ONE dispatcher**: `ask()` in `frontend/admin/kai-presence.js:479`. Every
governed turn — typed, chip, page action, voice — enters there. It tries the **typed Holding Command
API first** (`POST /admin/holding/command[/stream]`), and only falls through to the chat brain when
the router declines: `fallthrough='COMMAND_API_OFF'` on 404/405 (`:847`, i.e.
`KAI_HOLDING_COMMAND_ENABLED` off) or `fallthrough='NOT_HOLDING_INTENT'` on an `UNKNOWN` status
(`:854`). Voice changes `interaction_mode` and **nothing else** (`:814`). The voice path is
deliberately NOT also called from the command path — that would double-dispatch and double-audit one
turn (`:824`).

**Rationale.** ADR-009's reuse rule applied to input: a second turn path is a second ranker by
another name. Typed-intent-first means a real holding intent is answered by the deterministic,
audited, policy-checked router, and only genuinely conversational text reaches the LLM — so the
governed surface is the default, not the fallback. One dispatcher also means one place where
`interaction_mode` is stamped, which is what makes ADR-011/ADR-012's channel refusal enforceable.

**Consequences.** Any new input surface (mobile PTT, a future gesture chip, an arrival trigger) wires
to `window.KAI.ask()` (`kai-presence.js:169`) and inherits governance for free. Adding a second
dispatcher is a review-gate failure. Verify: `test_kai_speech_input` (11 checks), `test_kai_gesture`
(22 checks).

**Spec refs:** §8 (natural command router); §53 (command palette); §54 (global context); §7 (voice
command center); §92 (voice audit — one turn, one record).

---

## ADR-011 — TTS and mic are gated on BACKEND truth; the public APIs are trigger-blind
**Date:** 2026-09-04 · **Status:** ACCEPTED

**Context.** A voice UI can trivially lie: render a live-looking mic button when `KAI_VOICE_ENABLED`
is off, or let any caller claim a trusted trigger and start listening without a user gesture.

**Decision.** Capability truth comes from the **backend**, never from the frontend's optimism:
`GET /admin/holding/voice/capabilities` (`backend/app/routers/admin_holding_command.py:215`) reports
the REAL `KAI_VOICE_ENABLED`, the `PUSH_TO_TALK` default, `WAKE_WORD_LOCAL` **UNAVAILABLE** (no
on-device engine; cloud continuous audio is forbidden), `BROWSER_LIMITED` transcription,
`approval_by_voice: "REFUSED"` and `audio_persisted: false`. The frontend renders
**DISABLED-WITH-REASON** from that payload — never a fake-working mic. The public API is
**trigger-blind**: `kai-presence.js:173` — the public API can never name a trusted trigger; the two
trusted triggers (`'ptt-press'`, `'session-button'`) are reachable only from the internal mic
handlers, and `startListening` refuses without a live user activation otherwise (`:770`).

**Rationale.** §64 (never fake presence) and §155 (executive trust standard) forbid a control that
implies a capability the system does not have. ADR-003 fixed PTT as the privacy-preserving default;
this ADR is what makes it non-bypassable: if the trigger came from the public API it is not trusted,
so no amount of caller cleverness produces a mic start. There is exactly **ONE** `voice.stt.start`
call site in the whole admin frontend (`kai-presence.js:789`) — a property that is greppable and
therefore reviewable.

**Consequences.** Every new voice affordance reads its enablement from the capabilities endpoint;
none may hardcode a state. Phase 7b's post-commit refuter found the one hole in this rule
(`voice.start` trigger passthrough) and it was fixed in `efb05c6`. Verify: `test_voice_session`
(36/36), `test_kai_speech_input` (11).

**Spec refs:** §6 (always-listen privacy); §7 (voice command center); §64 (never fake presence);
§92 (voice audit / ephemeral audio); §135 (voice cert); §151 (production safety defaults).

---

## ADR-012 — The gesture recognizer arrives only through supply-chain certification; the camera is session-only
**Date:** 2026-09-04 · **Status:** ACCEPTED

**Context.** Phase 8 needed a gesture layer, and a gesture layer needs a recognizer model. Pulling a
model from a CDN or `npm` is the single fastest way to put unvetted third-party code in front of the
owner's camera stream.

**Decision.** No recognizer model ships in this build. The seam reports
`RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED` (`GestureSessionPolicy.capabilities`, surfaced by
`GET /admin/holding/gesture/capabilities`, `admin_holding_command.py:229`), and any future model must
pass the **same** capability/manifest supply-chain certification as any other external artifact —
never a direct dependency add. The camera is **session-only**: `KAI_CAMERA_ENABLED` (`config.py:79`)
default `False`, plus a per-session owner enable that is **never persisted**; indicator REQUIRED;
inference `LOCAL_ONLY`. There is exactly **ONE** `getUserMedia` call site across the whole admin
frontend — `kai-gesture.js:90`, requesting `{video: true, audio: false}` (audio is never requested).

**Rationale.** ADR-004 made "gesture never authorizes" a hard boundary; ADR-006 made every external
artifact untrusted-by-default. A recognizer is an external artifact pointed at a camera — the union
of both rules, so the strictest applies. Making the single capture call site a **statically asserted**
property (`test_kai_gesture.js:109` — exactly one call in the file; `:117` — exactly one across the
whole admin frontend, `kai-presence.js` has none) converts a policy into something a reviewer can
grep in one command.

**Consequences.** Gesture is convenience input with no recognizer today; the surface renders
DISABLED-WITH-REASON. `kai-gesture.js` is lazy-loaded and `kai-presence.js` never calls
`getUserMedia` (documented at `:21`, `:41`, `:704`). Phase 8's consolidation lens found one MED here
and it was fixed in `17ec7ce` (recognizer seam gated on backend certification truth). The
The privacy/authority/safety lens has since **reported and closed** — verdict FAIL, 2 HIGH + 2 MED +
1 LOW, all fixed in `9e0df08`. Verify at HEAD: `test_gesture_policy` **55/55**, `test_kai_gesture`
**27** (was 51/51 and 22 when this ADR was written).

**Spec refs:** §8/§9 (gesture); §93 (gesture audit); §94 (camera privacy); §113/§114 (quarantine /
supply-chain cert); §130 (gesture-spoofing defense); §136 (gesture cert).

---

## ADR-013 — §97 STOP fails closed (unreadable ⇒ ENGAGED) and is wired into `build_live_engine` + `a2_dispatch`
**Date:** 2026-09-04 · **Status:** ACCEPTED

**Context.** A kill switch that cannot be read is worse than no kill switch: it invites the caller to
assume "no record ⇒ not stopped" and keep running. §0 #15 forbids a switch that claims to disable
what it does not control.

**Decision.** `stop_state()` (`backend/app/services/holding/brakes.py`) returns `None` (released),
`STOP_ENGAGED`, or `STOP_UNREADABLE` — and an **unreadable** durable record is treated as
**ENGAGED**. It is wired into the two seams that actually start consequential work:
`holding_cycle.build_live_engine` (`holding_cycle.py:46-58`) forces **every config-read brake OFF**
when STOP is engaged or unreadable, and records **why** on the engine as `brake_override`
(`None | STOP_ENGAGED | STOP_UNREADABLE | CONFIG_UNAVAILABLE`) so a 0-execution cycle can say so
instead of being silently empty; and `a2_dispatch.enqueue_a2_coding_job` (`a2_dispatch.py:40-46`)
refuses with `STOP_ENGAGED`. Unreadable **config** independently fails closed to
`CONFIG_UNAVAILABLE` (`holding_cycle.py:55-59`). Explicit test overrides are untouched.

**Rationale.** Same convention as the existing `cycle_store.try_lock` ("DB down → do not run"), so
there is one failure posture in the codebase, not two. Recording `brake_override` matters as much as
the refusal: a silent zero is indistinguishable from "nothing to do", which is exactly the ambiguity
§65 (failure communication) forbids. STOP explicitly does **not** mutate config, env, or
`MONEY_MODE` — statically asserted at `test_brakes.py:374`.

**Consequences.** STOP halts the **next** engine build / A2 enqueue; an already-built engine finishes
its bounded cycle and claimed jobs run to lease expiry — it does not preempt, and that limit is
documented rather than implied (recorded as gap #7 in
`docs/KAI_OMNIPRESENCE_COMPARTMENTALIZATION.md`). Verify: `test_brakes` 63/63 with a reachable local
Postgres, 62/62 without (the one conditional `[db]` roundtrip check at `test_brakes.py:393`).

**Spec refs:** §97 (kill switch / brakes); §0 #12/#15; §65 (failure communication); §79 (bounded
automation).

---

## ADR-014 — The FINANCIAL brake is derived from the real Sol/Dwolla switches; MONEY_MODE is tri-state
**Date:** 2026-09-05 · **Status:** ACCEPTED

**Context.** Every money-posture reader in App B defaulted to `MOCK` when `MONEY_MODE` was absent —
and `MONEY_MODE` is **not declared** in App B's `Settings` at all. The dashboard was therefore
narrating a reader default as if it were an observation, and deriving a FINANCIAL "safe" state from
a value nobody had ever set. The Phase-9 refuter flagged exactly this.

**Decision.** Two changes, both binding. (1) **MONEY_MODE is tri-state**: declared value ·
`MOCK` when explicitly declared · **`UNAVAILABLE` when undeclared** — a reader default is never
reported as an observation. Implemented once and read from one place:
`status.py:96 _money_mode()` (via the ONE flag reader `self_model._flags`),
`self_model.py:142-150` (`_derive_limitations`), `capabilities_answer.py:178-185`. (2) The
**FINANCIAL brake is not derived from MONEY_MODE at all** — it is derived from the switches that
actually gate the real money path in this app (`app/main.py` mounts `routers/sol.py`):
`brakes.py:246 _FIN_CONTROLS = ("KAI_SCOPE_SOL_TRANSFER", "DWOLLA_ENV", "DWOLLA_ALLOW_PRODUCTION",
"DWOLLA credentials (presence only)")`, evaluated at `:251-284`; unreadable readers yield
`UNAVAILABLE`, never a fake OFF.

**Rationale.** §155 (executive trust standard) and §64 (never fake presence): "MONEY_MODE=MOCK"
asserted from a default is a fabricated safety claim, which is worse than "UNAVAILABLE" because it
invites trust. Deriving the brake from `KAI_SCOPE_SOL_TRANSFER` / `DWOLLA_ENV` /
`DWOLLA_ALLOW_PRODUCTION` also fixes a real correctness bug: those are the switches an operator would
actually flip, so the board now tracks the thing it claims to track. Credentials are reported by
**presence only**, never value (§120).

**Consequences.** `status.py` contains **no** literal `"MOCK"` and no literal `"DISABLED"` — both
rows are derived, and that is statically asserted. Any new money-posture surface reads
`_money_mode()`; adding a second reader is a review-gate failure. Verify: `test_status` 8/8,
`test_brakes` 63/63, `test_capabilities_answer` 45/45 (`83f6050`).

**Spec refs:** §45 (finance); §63/§99 (limitations); §64 (never fake presence); §97 (brakes);
§120 (credential presence, never value); §155 (executive trust standard).

---

## ADR-015 — The OS-Lab clean verdict is operator-only and is re-derived from the attached steps
**Date:** 2026-09-04 · **Status:** ACCEPTED

**Context.** A certification pipeline whose own runner can stamp "clean" is a self-approval machine
with extra steps — and the strongest possible temptation, because the runner has all the evidence
right there.

**Decision.** The bounded §114 vocabulary is `UNVERIFIED` ·
`NO_MALICIOUS_BEHAVIOR_DETECTED_IN_CERTIFIED_SCOPE` · `SUSPICIOUS` · `REJECTED`; `MALWARE_FREE` /
`SAFE` / `CLEAN` **do not exist** and are refused at construction in any spelling
(`os_lab/runtimes.py:34/:42`). `record_verdict` (`os_lab/catalog.py:237`) has a **fail-closed
direction**: KAI may record only `SUSPICIOUS` / `REJECTED` / `UNVERIFIED`; the clean-scope verdict is
**operator-only** (`PermissionError` at `:247`), must **agree with the attached report's own
verdict**, requires `scope == FULL`, and requires that no step is left `SKIPPED` / `PENDING` /
`UNVERIFIED`. The runner cannot reach it: every executable step is `SKIPPED` with reason
`EXECUTION_GATED`, so `derive_verdict` (`certification.py:262`) over a static-only run can at best
return `UNVERIFIED` (`certification.py:548`). Adoption (`CERTIFIED` *and* `RESTRICTED`) is
operator-only (`catalog.py:221`), as is the §117 `GapJustification` (`:271`).

**Rationale.** §0 #11 (KAI never self-approves) and §114's bounded vocabulary, applied to the one
place where a machine verdict would carry the most weight. Re-deriving the recorded verdict from the
attached steps — rather than trusting the number a caller passes — is the same discipline as ADR-014:
report what the evidence says, not what the caller asserts. This is also the strongest form of
ADR-006's "a README is DATA, not policy": a certification report is evidence, never an authority
(`certification.py:243 authority_plane = "KAI"`).

**Consequences.** With the real (all-False) `EXECUTED` ledger the lifecycle stops at `STATIC_REVIEW`;
`BUILD_REVIEW` and `ISOLATED_EXECUTION` are refused for **every** actor while the reviewed thing has
not happened. The P10 refuter's re-derivation hardening landed as the **P10 round-2 fix `749fa78`**
— and that was **not** the end of it: `ed00e4e` additionally required the step ids to cover the
pipeline and, for a FULL-scope report, executed `build`+`qemu_boot` (the round-2 re-derivation had
only validated the *shape* of whatever step list it was handed — a one-step stub, the gated six
alone, or 26 copies of one certified step all passed), and `79062c4` made a malformed finding row a
**refusal** rather than a silent drop. See **ADR-024** for why this line took four refuter rounds.
Verify at HEAD `8799db9`: `test_os_lab_catalog` **83/83**, `test_certification` **80/80** (needs the
repo root on `PYTHONPATH` — see ADR-017).

**Spec refs:** §41 (OS supply-chain cert); §113 (quarantine lifecycle); §114 (verdict vocabulary);
§117 (adoption gate); §0 #11 (no self-approval); §165 (KAI remains the brain).

---

## ADR-016 — Ultron's source is OPERATOR-STATED and UNVERIFIED, read from ONE spine
**Date:** 2026-09-04 · **Status:** ACCEPTED

**Context.** Phase 10 needed a canonical upstream for Ultron OS. The operator supplied one. A second
copy of that string inside the runtime record would be a divergence waiting to happen, and treating
it as a *verified* fact would be a fabrication.

**Decision.** `UltronSandboxRecord.source` is read from the catalog entry, not restated:
`os_lab/runtimes.py:113` — `source: str = _cat.get("Ultron OS", _cat.initial_catalog()).canonical_source`.
**One spine.** Its status is **OPERATOR-STATED, NOT FETCHED, UNVERIFIED** — the feature row says so
in words (`runtimes.py:384`: "UNVERIFIED — source operator-stated (not fetched); no build/scan/boot"),
and `is_fully_unverified()` (`:137`) asserts every one of the nine `ULTRON_VERIFICATION_FIELDS` is
`UNVERIFIED`. Disposition is `EDUCATIONAL_OS_SANDBOX` and `production_use` must be `NO` — enforced at
construction (`:134`).

**Rationale.** ADR-006 starts every external repo UNTRUSTED and confirms upstream only at
`SOURCE_VERIFIED`; a catalog `canonical_source` is a *note*, not a verified fact. ADR-009's
one-authority rule applied to a string: two copies of an upstream URL is exactly the false-friend
pattern (`budget_manager`) that the reuse discipline exists to prevent. MEMORY's live reminder that
`free-llm-api-resources` was REMOVED upstream is the standing argument for never treating an
unfetched source as real.

**Consequences.** Changing the upstream means editing the catalog entry, and everything downstream
follows. Nothing about Ultron was cloned, downloaded, installed, built, or QEMU-booted. Verify:
`test_os_lab_runtimes` 85/85 (including the forbidden-claim spelling sweep at `:78`).

**Spec refs:** §40 (Ultron OS sandbox); §113 (SOURCE_VERIFIED); §115/§116 (catalog ingestion /
dispositions); §114 (verdict vocabulary); §102/§150 (feature registry rows).

---

## ADR-017 — Per-file test harness, because the zero-framework runners exit at import
**Date:** 2026-09-05 · **Status:** ACCEPTED

**Context.** The holding suites are deliberately zero-framework: each `test_*.py` is a plain
`python3` script with `ck(...)` assertions and a printed total. That style raises `SystemExit` at
import time, so a single `pytest` run over the whole `app/` directory `INTERNALERROR`s and reports
nothing — which reads like "the suite is broken" when it is not.

**Decision.** **Per-file execution is the harness.** Each module is run on its own
(`PYTHONPATH=..:. DATABASE_URL=... python3 -m app.services.holding.test_<name>` from `backend/`, or
as a plain script), and the regression sweep is per-file on both HEAD and the pre-omnipresence base
`d881cf2^`, diffed. The repo root must be on `PYTHONPATH` alongside `backend/`, because
`os_lab/certification.py:42` imports the shared core scanner table
(`core.security_scanner._COMPILED_PATTERNS`) from App A — without it the module honestly sets
`_CORE = None` and the five core-backed steps report `UNVERIFIED` / "core scanner table unavailable"
(58/58 with the root on the path, 45/58 without).

**Rationale.** The zero-framework style is the right call for these modules (no fixtures, no plugins,
runnable by anyone with `python3`), so the harness adapts to it rather than the reverse — the lazy
option that does not require rewriting 65 test modules. Diffing per-file results against `d881cf2^`
is also what makes "ZERO regressions" a *measurement* instead of an assertion: the 133 test files
outside `holding/` produce byte-identical results on both, and the App B `tests/*.py` fixture errors
(`admin_chat` 15, `auth` 16, `browser` 59, `planning` 95, …) are proven **pre-existing** rather than
argued to be.

**Consequences.** Any new holding/os_lab test module follows the same shape (`run()` +
`test_<name>()`, no `SystemExit` at import, pytest-discoverable). CI, when it exists, iterates files;
it does not invoke `pytest app/`. Environment-dependent counts (`test_brakes` 63 vs 62,
`test_certification` 58 vs 45) are reported with their condition, never as a single number.

**Spec refs:** §142 (regression suite); §144 (evidence over assertion); §161/§162 (requirements
ledger + evidence matrix — a count must be reproducible to be citable).

---

## ADR-018 — Commit after EVERY phase: the session limit kills agent returns, file edits persist
**Date:** 2026-09-05 · **Status:** ACCEPTED

**Context.** Phase 3b was built and then **lost** to a session reset (MEMORY: the `/private/tmp`
scratch was wiped and uncommitted Phase 3b work went with it). It had to be rebuilt from scratch —
see `261931e`, whose message says "rebuilt after reset loss".

**Decision.** **Commit after every phase**, on the durable worktree
`/Users/jhonwheeler/wheellsverse-cyberops` — never a `/private/tmp` scratch, never a multi-phase
batch. Each phase commit is self-contained (modules + tests + doc rows) and each review-fix pass gets
its own commit (`ac9fcff`, `58a4227`, `17ec7ce`, `543da39`, `83f6050`, `9e0df08`, `749fa78`,
`ed00e4e`, `79062c4`, `8799db9`) so a refuter's findings and their remediation are separately
citable. That separability is what made ADR-024's five-round history reconstructable at all.

**Rationale.** An agent's *return value* does not survive a session limit; **file edits and commits
do**. Committing per phase converts an unbounded loss into a bounded one and makes the review ledger
mechanically traceable — every row in the certification report cites a SHA because a SHA existed at
the moment the work finished. It is also the cheapest possible insurance: one command per phase
against re-doing thousands of lines.

**Consequences.** The 24-commit history in `docs/KAI_OMNIPRESENCE_CERTIFICATION.md` §1 is the
artifact of this rule. A phase that ends without a commit is not finished. Work in progress that
cannot yet be committed is named as IN FLIGHT with an explicit unresolved-SHA placeholder rather than
being described as done — as the P10 round-2 fix was until it landed as `749fa78`, and the P8
privacy-lens fixes until they landed as `9e0df08`. **Both placeholders are retired: no
unresolved-SHA placeholder remains anywhere in the doc set, and no code sits outside a commit.**
The inverse use of the rule — naming an unreported review in words, because an unrun refuter is not
a finding of "clean" — was exercised on the refuter of `749fa78` and is now **also retired**: four
refuter rounds ran (`ed00e4e`, `79062c4`, `8799db9` are their remediations) and **no refuter is in
flight**. There is a further lesson the round-2 case taught, recorded separately as **ADR-024**: a
committed fix that a refuter has not yet attacked must never be written up as though the defect
class were closed. `749fa78` was, and three more rounds proved that wrong.

**Spec refs:** §159 (final certification — every claim traceable to a SHA); §162 (evidence matrix);
§160 (proceed on authorized reversible work); §0 #13/#14 (COMPLETE means evidenced).

---

## ADR-024 — Iterated adversarial refutation with a growing probe corpus, and the stopping rule
**Date:** 2026-09-05 · **Status:** ACCEPTED

**Context.** The Phase-10 credential-leak line was reviewed by two structured lenses (fixed in
`58a4227`) and then by **four independent refuter rounds**, where each round's refuter attacked the
**previous round's fix** rather than re-attacking the original code, carrying forward and extending
the probe corpus each time (128 assertions at round 3, 201 at round 4, 451 at round 5).

Every intermediate round genuinely believed the defect was closed, and the docs said so. The record:

| Round | Fix | What the NEXT refuter found in it |
|---|---|---|
| lenses | `58a4227` | findings **embedded the matched secret** and were truncated **before** `redact()` — AWS `ASIA`/`AROA` ids and ~72 chars of a long secret reached the report *and* the audited history (**HIGH**) |
| 2 | `749fa78` | withholding keyed on the **label**, so a greedy pattern whose match **spanned** the secret still emitted it — **101 distinct 20-char windows** of a 120-char secret (**HIGH**); the severity gate failed **OPEN** (**HIGH**); **and a regression this very fix introduced** (**HIGH**, below) |
| 3 | `ed00e4e` | a `.gitmodules` submodule-URL **password written verbatim** into step evidence and copied unredacted into the report artifact — beside a finding text that *was* redacted, which is what made it easy to miss (**HIGH**) |
| 4 | `79062c4` | seven credential families the pattern tables never **matched at all** left `credential_reads` **PASS**, while the module docstring and the OS-Lab doc both asserted no embedded credential could — **the claim was false as written**, a zero-fabrication violation independent of detection quality (**HIGH**) |
| 5 | `8799db9` | bounded, **named residual R7** — no reachable defect |

**Four HIGH defects and one self-inflicted regression that single-pass review had passed as clean.**

**Decision.** For any security-relevant control, run **iterated refutation**: each round's reviewer
attacks the **previous round's fix**, with the probe corpus growing rather than resetting. A single
adversarial pass is treated as evidence about the *original* code, never as evidence about the fix
that pass produced.

**The stopping rule actually used — the one to reuse.** Stop when a round's findings are **bounded,
named residuals rather than reachable defects.** Rounds 2, 3 and 4 each produced a *reachable* defect
(a concrete input that put secret material into the report or certified something it should not), so
each was continued. Round 5's output was R7 — "credential detection is a pattern list, not proof",
a stated limit of the approach with its reachability written down and bounded by an independent
control (nothing certifies on a static-only report; the clean verdict also needs full pipeline
coverage and `executed` `build`+`qemu_boot` true). That is a residual, not a defect, so the line
stopped there.

Explicitly **not** the stopping rule: "the tests pass", "the fix was re-verified before commit", or
"the round found fewer things than the last one". All three were true of `749fa78`, and `749fa78`
was wrong in two independent ways.

**A fix can introduce a worse defect than it closes.** Round 2 deep-froze `executed`/`evidence` with
`MappingProxyType` to protect the "nothing was built or booted" ledger. But `MappingProxyType` is not
a `dict` subclass, and `task_resolver.redact` dispatches on `isinstance(obj, dict)` — so a
**hardening** change **silently disabled redaction** of evidence written to the append-only history
and broke `dataclasses.asdict`. It made the exact leak it was committed alongside *more* likely, it
raised no error, and no test at the time caught it. Two operating consequences: (1) a fix is in scope
for the next round's refuter, always; (2) a type substitution that changes `isinstance` behaviour
must be checked against **every dispatch site keyed on the old type** — `grep` for
`isinstance(.*dict)` before swapping a mapping type. The replacement is a mutation-refusing `dict`
subclass: `isinstance` stays True, `redact` traverses, `asdict` works, mutation still raises.

**Consequences.** os_lab checks grew 216 → **255** (catalog 83 · runtimes 92 · certification 80),
almost entirely as *negative* checks pinning each refuted route. The certification report's §6 ledger
records all four rounds with their assertion counts rather than a single "reviewed → fixed" line, §8
carries **F6** (five-round history, not struck through) and **F6a** (the regression, recorded rather
than buried), and **N1 reads PARTIAL, not PASS**, because R7 makes the credential guarantee
per-listed-family rather than universal. A limitations ledger that hides a self-inflicted regression,
or a non-negotiable upgraded to PASS to make a report look finished, would defeat the purpose of
having run the rounds at all.

**Spec refs:** §159 (final certification — every claim traceable); §162 (evidence matrix); §163
(decision log); §0 #13/#14 (COMPLETE means evidenced); zero-fabrication (a claim wider than the code
is a violation regardless of how good the code is).

---

## Decisions still needing operator input (cross-ref baseline §5)

- **ADR-001** base-branch confirmation (OQ #4).
- **ADR-003 / ADR-004** voice/gesture privacy defaults + camera authorization (OQ #2).
- **ADR-006** OS-Lab scope: descope, defer, or authorize (OQ #3).
- **ADR-007** operator-provisioned isolated staging is the gate for every authority-enablement step (OQ #6);
  finance/customer source provisioning gates §45/§46 (OQ #5).
- **Blocker (all command-API work):** the §90 spec tail was truncated but the §91–§166 continuation arrived
  (09:24) and is now indexed — reconcile before finalizing the command envelope (baseline OQ #1 is partially
  resolved; verify the §90 tail specifically).
