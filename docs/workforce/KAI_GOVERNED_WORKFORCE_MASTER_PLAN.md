# KAI Governed Workforce — master plan (controlling document)

**Branch:** `feat/kai-hook-foundation-phase1` · **base:** `c69c4dfd` (Stage-0 tip, off the `feat/kai-freellmapi` line at `9f78176b`)
**Status:** `WORKFORCE_CONTRACTS_IMPLEMENTED_LOCALLY` (Phase 1 pure contracts built + tested, inert). Phase 0 research + Phase 1 `AgentCharacterManifest` schemas done; nothing imported, activated, merged, or deployed. Upstream intake (Phase 2) not started.
**Companion controlling docs:** `../kai/plans/KAI_HOOKS_MASTER_BUILD_PLAN.md`, `../kai/plans/KAI_CAPABILITY_EXCHANGE_RESEARCH_AND_CLAUDE_MISSION.md`, `../kai/plans/REQUIREMENTS_LEDGER.md`.

The deliverable is an **inert, reviewable, testable workforce catalog + control-plane foundation** — a governed roster of ≥270 specialist AI *characters* that work **for** KAI. It is NOT permission to run 270 agents, install upstream scripts, bind handlers, deploy, browse, message, move money, or touch the soak.

---

## 0. Companion documents (versioned, hash-linked)

The full durable requirements live in these repository-controlled companions
(linked by path + SHA-256 so a chat prompt is never the controlling source):

| Document | SHA-256 |
|---|---|
| [`AGENT_CHARACTER_CONTRACT.md`](./AGENT_CHARACTER_CONTRACT.md) — full manifest field contract | `916bf5eaa93ff9adcaba4d3060fd5bed13ef57f3dca18027ce6e0d29b6dd18df` |
| [`KAI_NATIVE_CHARACTERS.md`](./KAI_NATIVE_CHARACTERS.md) — the 40 required characters | `a5585119c5de2d1383eb8777342942c7a123324e9b086e95317b16d976de0dd5` |
| [`WORKFORCE_ORG_CHART.md`](./WORKFORCE_ORG_CHART.md) — divisions + workplaces + team rules | `e0ff14a35d0533b085d17ad77a1ef7a7d8b75245f01ff87edac75a7967d72adc` |
| [`FRAMEWORK_CAPABILITY_MATRIX.md`](./FRAMEWORK_CAPABILITY_MATRIX.md) — framework matrix (Angular 22.1.x / TS 6.0.3) | `8073e1f381fd80a0a490abca4ca082d3af4ec77da516eb4fc6a3b848f26d854a` |
| [`ADMISSION_AND_EVALUATION.md`](./ADMISSION_AND_EVALUATION.md) — intake/quarantine, lifecycle, tests, ≥270 acceptance, status labels | `fb2f7b0ac2621b12a6420fbbebad867b94709b9b407cd65b5f9c9e1e64a2061c` |

No "see mission §…" references remain; all requirements are embedded above or in
these companions.

## 1. Non-negotiable constitution

KAI remains the sole: mission owner · policy authority · approval authority · orchestration authority · model-routing authority · memory authority · tenant authority · completion authority · evidence authority · operator-facing identity.

Imported agents are **specialist characters**, not sovereign agents, substitute orchestrators, or competing brains. **A declaration is not permission.** A registered character is inert until KAI admits it, assigns it to one specific mission, grants bounded capabilities, and creates an isolated workplace.

**Never create:** a second KAI · an autonomous chief-of-staff with independent authority · an agent that creates missions without KAI · self-approval · self-declared completion · a second policy engine · a second long-term memory authority · an agent-controlled credential store · unrestricted agent-to-agent delegation · persistent autonomous loops · uncontrolled recursive spawning · a public dispatch/handler-binding surface · execution triggered merely by registration.

**Standing safety ceiling (unchanged):** no merge · no deploy · no production changes · `KAI_BROWSER_OPS_ENABLED=false` · soak untouched · Istanbul worktree/session untouched · no hook handler bound · no capability adapter bound · no new executable router mounted · no networked hook worker · **L3 (worker/test isolation) remains BLOCKING** · **no Alembic revision from this branch's stale 0006 head** (production 0007–0009 are on the same lineage and must be reconciled first). STOP if any instruction conflicts with these.

**"Brain" / "soul" are product metaphors:** *brain* = a KAI-controlled ModelRouter + tool-policy profile (not an independent mind). *soul* = a character constitution (values/boundaries). **No claims of consciousness, feelings, personhood, or sentience.**

---

## 2. Controlling-document loop

Before starting, and after every implementation unit: reread both `kai/plans` controlling docs + this plan + the workforce requirements ledger; compare implementation to the ledger; inspect the diff; rerun the unit's tests + negative controls; confirm every safety-ceiling invariant; update the ledger with evidence; commit only that coherent unit; continue only if nothing drifted. "Tests pass" is never proof the plans were followed — do a plan-to-diff reconciliation each unit.

---

## 3. The Agent Character Contract

Every character (imported or KAI-native) gets a complete, versioned `AgentCharacterManifest` with six mandatory parts — **identity, personality, mission, brain, soul, workplace** — plus **capabilities** and **governance**. Name-and-generic-prompt is invalid; generic duplicates fail validation. **Full field contract: [`AGENT_CHARACTER_CONTRACT.md`](./AGENT_CHARACTER_CONTRACT.md)** (see Companion documents below for the SHA-256). Field set: identity (id/schema_version/display_name/codename/…/source_kind/source_path/source_commit/source_hash/license/reviewed_by), personality (5–7 traits + anti-traits + prohibited behaviors), mission (one-sentence + responsibilities/non-responsibilities/success/failure/escalation), brain (profile_id/reasoning_class/model_router_requirements/tool_categories/budgets/eval_suite), soul (values/boundaries/refusal/immutable principles), workplace (tenant/project/mission scope, read/write roots, network/browser/device/external-write policy — all **deny by default**, budgets, evidence stream, cleanup), capabilities (declared/forbidden/approval_required/consequential + schemas + evidence), governance (status/risk_tier/effect_class/activation_requirements/approval_policy/separation_of_duties/kill_control/expiry/revocation/audit).

Names: unique, readable, respectful, **deterministically derived from the manifest id** (no random renames across builds), collision-checked.

---

## 4. Size, divisions, workplaces, team composition

- **Size:** import every legitimate upstream agent at the pinned SHA (upstream README claims 230+; the "250" is a social-media claim — **derive the true count**), then add KAI-native characters to reach **≥270** validated manifests. The 40 required KAI-native characters — named in full (incl. Vera Complete the *independent* completion verifier, Cipher Ward, Tessa Boundary, Mira Proof, …) in **[`KAI_NATIVE_CHARACTERS.md`](./KAI_NATIVE_CHARACTERS.md)** — must not be silently renamed/omitted.
- **Divisions:** upstream divisions from `divisions.json` + KAI operational divisions (Executive Advisory, Governance & Approvals, Evidence & Reality, Tenant Security, Platform & Architecture, Data & Memory, Models & Evaluation, Browser & Device Safety, Nurtelle Healthcare Safety, SOL Governance, NarAI Commerce, Legal & Privacy, Release & Incident Ops). Any upstream "orchestrator/chief-of-staff" is **downgraded to advisory planning**.
- **Workplaces:** each is an isolation + policy profile (not a UI label); defaults deny network/browser/device/external-writes/publishing/messaging/financial-execution/prod-credentials.
- **Teams:** KAI selects the smallest sufficient team (usually 3–7): planner/lead + worker(s) + risk reviewer (when risk requires) + **independent** completion verifier. Planners can't silently execute; workers can't self-approve or self-complete; reviewers can't verify their own output; consequential actions need a fresh, bound, single-use approval; delegation tokens are mission/tenant/capability-scoped, expiring, non-forwardable; no recursive recruiting; hard fan-out/depth limits; typed-artifact handoffs with provenance.

---

## 5. Storage (proposed, adapt to repo conventions)

`backend/app/services/workforce/{schemas,catalog,importer,normalization,provenance,workplaces,brain_profiles,soul_contracts,team_planner,validation}.py` + `generated/`; `backend/tests/test_workforce_*.py`; `docs/workforce/*`; `frontend-pilots/kai-angular/src/app/workforce/*` (dark). **No DB migration** until the production migration lineage is reconciled — static versioned manifests suffice for inert Phase 1.

---

## 6. Catalog safety + the HookRegistry precedent

The first `WorkforceCatalog` is **catalog-only**: register/retrieve/filter/validate-provenance/inspect-status/summarize/propose-simulated-team. It must NOT expose bind/dispatch, run tools, call models, create missions, mutate env, start workers, access networks, mount routers, or enable a character by registration.

**Precedent correction (in progress):** `HookRegistry` is being refactored to catalog-only (no `bind_handler`/`dispatch`/`is_armed`, no flag evaluation, `execution_supported=False`, kill-switch-inversion removed) with a negative control proving registered hooks can't execute. **Open finding:** `capability_exchange.py` still exposes `bind_adapter`+`execute` (the same in-process pattern) — recommend the same catalog/execution split before any workforce execution work, so the workforce does not inherit the mistake. Kill control and enable flag are **separate**; a kill switch defaults to **blocking** execution.

---

## 7. Lifecycle — implementation stops at INERT

`DISCOVERED → QUARANTINED → REVIEWED → ADMITTED → INERT → AVAILABLE → ASSIGNED → RUNNING → VERIFYING → COMPLETED|FAILED|CANCELLED|QUARANTINED|REVOKED`. **This mission stops at `INERT`.** "AVAILABLE" still ≠ "authorized for this mission." Transitions are KAI-controlled and evidence-recorded.

---

## 8. Phases (this mission: Phase 0 → inert only)

- **Phase 0 — Investigation** (done in the turn that created this doc): repo/branch/routes/execution-surface/migration-lineage printout + upstream intake strategy + stop conditions.
- **Phase 1 — Contracts:** the six-part manifest + BrainProfile + SoulContract + WorkplaceProfile + CapabilityDeclaration + WorkforceStatus schemas + pure validation tests.
- **Phase 2 — Quarantined import:** deterministic upstream parser at a pinned SHA; hostile-content handling; exact inventory + SHA-256 + provenance; no execution; no home-dir install; `docs/workforce/UPSTREAM_INTAKE_REPORT.md`.
- **Phase 3 — KAI normalization:** normalize every imported character to the full six-part identity; add the required KAI-native characters; reach ≥270; generate org chart + capability matrix.
- **Phase 4 — Inert catalog:** register/query/index/simulate-team only; no model/tool/router/handler/adapter.
- **Phase 5 — Dark Angular console:** static generated catalog + org chart + character/workplace views + team simulation; all action controls **disabled** and labeled `NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED`; no dependency install without a separate governed decision (retain the pinned Angular 22.1.x / TS 6.0.3).
- **Phase 6 — Independent review:** adversarial passes on policy authority, prompt injection, tenant isolation, execution inertness, supply chain, provenance/license, schema integrity, UI honesty, test integrity, migration safety, cost/fan-out. **No real execution stages in this mission.**

---

## 9. Tests / negative controls (must have teeth)

Inventory (count derived not hard-coded; duplicate ids rejected; hashes stable; provenance required; KAI-native never claims upstream provenance; MIT notice retained) · character quality (unique name; six parts present; generic/unsafe-autonomy/sentience/second-orchestrator text rejected; forbidden effects explicit) · tenancy (principal-derived tenant, cross-workspace/revoked/missing fail closed, non-enumerating) · control (registration + proposed team cannot execute; no handler/adapter/router/worker; browser/device/network off; flag false) · delegation (token can't cross mission/tenant/parent-capability; expired/reused rejected; non-forwardable; no self-approval) · separation of duties (worker≠verifier; planner≠silent-executor; reviewer≠evidence-editor; completion needs independent evidence) · prompt security (hostile upstream stays quoted data; overrides quarantined; no shell exec on import; secret requests rejected; embedded URLs don't trigger network) · team planning (bounded team; risk-tier-aware; includes reviewer; no whole-catalog recruit; no recursion; deterministic). Promotion beyond INERT needs ≥20 behavioral cases/agent (≥50 for security/finance/health/browser/device/deploy) — out of scope for this mission.

---

## 10. Status labels (honest)

Use: `WORKFORCE_RESEARCHED` · `WORKFORCE_CONTRACTS_IMPLEMENTED_LOCALLY` · `WORKFORCE_IMPORTED_IN_QUARANTINE` · `WORKFORCE_CATALOG_INERT_LOCALLY` · `WORKFORCE_UI_DARK_LOCALLY` · `WORKFORCE_INDEPENDENTLY_REVIEWED`. Never use `WORKFORCE_ACTIVE`/`DEPLOYED`/`CERTIFIED`/`PRODUCTION_READY` without separate evidence + owner authorization.

---

## 11. Genuine owner decisions that pause this mission

- The **migration-graph reconciliation** strategy (bring 0007–0009 onto this branch / rebase / consolidate) — blocks any workforce persistence migration.
- Whether to apply the **catalog/execution split to `capability_exchange`** now (recommended) vs. defer.
- Any promotion past `INERT`, framework installs, upstream execution, or external effects — each requires separate owner authorization.
