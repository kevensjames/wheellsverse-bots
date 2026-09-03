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

## Decisions still needing operator input (cross-ref baseline §5)

- **ADR-001** base-branch confirmation (OQ #4).
- **ADR-003 / ADR-004** voice/gesture privacy defaults + camera authorization (OQ #2).
- **ADR-006** OS-Lab scope: descope, defer, or authorize (OQ #3).
- **ADR-007** operator-provisioned isolated staging is the gate for every authority-enablement step (OQ #6);
  finance/customer source provisioning gates §45/§46 (OQ #5).
- **Blocker (all command-API work):** the §90 spec tail was truncated but the §91–§166 continuation arrived
  (09:24) and is now indexed — reconcile before finalizing the command envelope (baseline OQ #1 is partially
  resolved; verify the §90 tail specifically).
