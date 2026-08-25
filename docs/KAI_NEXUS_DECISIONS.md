# KAI Adaptive Mission Nexus — Decision Record

Append-only log of load-bearing architecture/design decisions (directive §3).
Each entry: options considered, scores, choice, rationale. Do not re-litigate a
locked decision without new repository evidence.

---

## D0 — Top-level direction: Adaptive Mission Nexus (§2)

**Options**
- **A — Cinematic AI**: strong emotional identity; insufficient operational density.
- **B — Pure Mission Control**: excellent operational visibility; KAI becomes secondary.
- **C — Adaptive Mission Nexus**: KAI central, operational views materialize on real state; harder architecture.

**Weighted matrix** (weights from §2)

| Criterion | wt | A | B | C |
|---|---|---|---|---|
| visual identity | .20 | 9 | 4 | 9 |
| operational usefulness | .25 | 4 | 9 | 9 |
| clarity | .15 | 7 | 7 | 8 |
| adaptability | .15 | 5 | 5 | 10 |
| performance | .10 | 8 | 6 | 6 |
| maintainability | .10 | 7 | 6 | 6 |
| accessibility | .05 | 7 | 7 | 7 |
| **weighted** | | **6.15** | **6.55** | **8.35** |

**DECISION: C — Adaptive Mission Nexus.** Locked. Highest weighted score and the
only option that satisfies both "KAI is the central intelligence" and
"operational views on demand." Repository evidence (a mature KAI presence system
already exists) reinforces C. Not reopened.

---

## D1 — Base: extend the existing presence system, do NOT build a new dashboard (§0/§1)

**Evidence:** `frontend/admin/kai-presence.js` is already the ONE KAI provider
(pub/sub bus + `state` store + governed SSE streaming + orb/drawer/Nexus +
living avatar), server-injected on every `/admin/*` page via `_inject_kai_presence()`
(core/api.py), with `/admin/nexus` as the immersive view.

**Options:** (A) new standalone dashboard app; (B) extend kai-presence + /admin/nexus.

**DECISION: B.** A new app would create a second identity/session/brain/event
stream — explicitly forbidden (§1). The Mission Nexus is the evolution of
`/admin/nexus`, built as `kai-nexus.{js,css}` that reuse the presence provider's
identity, session, governed streaming, and `kaiState`. Base branch:
`feat/kai-mission-nexus` off `feat/kai-admin-merge` (the only branch with the
presence system + the RBAC-hardened bridge).

---

## D2 — Event bus: extend kai-presence pub/sub into the canonical bus (§38)

**Options:** (A) new event library; (B) extend `kai-presence.js` `subs`/`on`/`emit` + `state`.

**DECISION: B.** §38 mandates ONE canonical event system. kai-presence already
emits `kaiState`/`mode`/`principal`. The Nexus bus adds mission/agent/tool/
system/security/approval/provider event topics onto the SAME emitter and state
store. Every visualization subscribes; no fabricated activity timers (§38).

---

## D3 — Renderability + data honesty: DEMO scenario driver, hard provenance (§39/§47)

**Problem:** full live telemetry needs App A + DB + providers running; screenshot
QA (§46) needs the shell renderable now.

**DECISION:** the shell runs against the canonical event bus. A **clearly-labeled
DEV/DEMO scenario driver** (`?scenario=idle|latency|research|security|approval`)
emits fixture events to exercise every adaptive state for visual QA — every datum
it produces carries a `DEMO` provenance tag and a visible badge. Real
subscriptions (governed streaming, `/api/*/status`, `/admin/*`) override DEMO
when present and are tagged `REAL`/`DERIVED`. **Production never shows DEMO as
live** (§39): the DEMO driver only activates on explicit `?scenario=` and renders
a persistent "DEMO DATA" banner. Provenance enum on every datum: `REAL` /
`DERIVED` / `DEMO` / `UNAVAILABLE`.

---

## D4 — Layout engine: CSS grid areas with breakpoint-swapped templates (§4/§36)

**Options:** (A) JS-driven absolute layout; (B) CSS `grid-template-areas` swapped per breakpoint.

**DECISION: B.** Ultrawide-first `grid-template-areas` (rails + hero + canvas +
command + nav), redefined at MOBILE/TABLET/DESKTOP/WIDE/ULTRAWIDE breakpoints
(§36). No stretching a 1440 layout to 3440 — ULTRAWIDE (`>=2560`) gets its own
template with substantial rails (340–410 / 410–480px) and a bounded hero. CSS
does the responsive heavy lifting; JS only toggles mode/density classes.

---

## D5 — Security posture: zero client-trust, reuse governed spine (§0/§42)

**DECISION:** the Nexus adds NO new auth/authz/brain/endpoint. It calls the
existing governed stream (`/admin/kai/kai-chat/stream`, owner-only kai.ultra via
the RBAC-hardened bridge) and read-only status endpoints. Client role/scope is
display-only; every action re-checks server-side scope + governance + approval.
No secrets in the DOM. UI work never justifies a security regression.

---

## D6 — Approval governance: UI approval is NOT authorization (§3E) — 2026-08-25

**Options:** (A) client-side approval grants the action; (B) client records/
requests only, backend authoritative.

**DECISION: B.** `kai-nexus-procedure.js` `approve()` only *records* a decision
and unlocks the step in the local machine — it never grants a real action. In
production (`IN_APP && !DEMO`) the approve/deny buttons DO NOT transition state;
they surface "requires the governed backend endpoint" because no governed
approval endpoint is wired yet (honest, not faked). The DEMO path performs the
client transition only under `?scenario=` with a visible "DEMO — backend is
authoritative" note. Rationale: §3E/§42 — the backend (session role + scope +
kai.ultra + money/destructive gates + audit) is the sole authority; the UI must
never become a privilege-escalation path. **Open (EXTERNAL_BLOCKED):** a governed
`POST /admin/kai/approvals/{id}` endpoint on App B is required before real
approvals; until then approvals are DEMO-only.

## D7 — Procedure state machine: refuse illegal transitions (§3C) — 2026-08-25

**DECISION:** a pure, unit-tested state machine (`kai-nexus-procedure.js`, 16
node tests) is the single source of execution truth. It structurally forbids
`PENDING→SUCCESS` (no un-executed success), `APPROVAL_REQUIRED→SUCCESS` without
an `APPROVED` record, resuming a `BLOCKED` step before the blocker resolves,
retrying a non-retryable `FAILED` step, and silently skipping a `required` step
(skip needs `required:false` + a reason). The UI cannot fake progress because
every visual state derives from this machine. Chosen over an ad-hoc UI-driven
flow because mission-control execution semantics must be enforced, not merely
drawn.

## D8 — Telemetry polling strategy (§4G) — 2026-08-25

**Options:** (A) poll every source independently (~20 browser loops); (B) one
aggregate backend telemetry endpoint the client polls once; (C) hybrid — bounded
client polling of a *curated few* liveness endpoints + push (SSE) for activity.

**Scores** — A: high browser load, N sockets, brittle; B: cleanest + lowest load
but requires a new backend endpoint that does not exist yet; C: works today,
low load, honest.

**DECISION: C now, B recommended.** The client probes a **small curated set**
(App B `/health`, App A `/api/v2/narai/health`, bridge `/admin/kai-bridge/health`)
— NOT 20 loops — with: single shared interval, bounded concurrency, `AbortController`
timeout, exponential backoff + jitter on repeated failure, and **pause when the
tab is hidden** (`visibilitychange`). Activity/mission telemetry already arrives
via the governed SSE bus (push), so we do not poll for it. **Recommended upgrade
(EXTERNAL_BLOCKED):** add an aggregate `GET /admin/telemetry` on App A (one
response with per-subsystem status + the metrics currently UNAVAILABLE) → the
client polls once and many UNAVAILABLE metrics become REAL. Until then, deep
metrics stay honestly UNAVAILABLE (D3/§4F).

## D9 — Agent registry source (§5B/§5AD) — 2026-08-25

**Evidence (docs/KAI_AGENT_SOURCES.md):** no unified agent-registry endpoint
exists; the real "agent catalog" is App B `GET /admin/presets` (11 REAL_AGENT
presets, no runtime state), and live state is scattered across ~8 status
endpoints in two apps behind two auth models (App B `kai.ultra` vs App A
operator_session).

**Options:** (A) frontend-only registry (hard-code agent truth in kai-nexus.js);
(B) frontend adapter fanning out to all 8 status endpoints; (C) one canonical
backend aggregator (`GET /admin/agents`) that normalizes catalog + live state.

**DECISION: C is correct — RECORDED but EXTERNAL_BLOCKED; interim = minimal B.**
A is rejected outright (§5B — do not hard-code duplicate agent truth). C is the
right architecture (normalize once, keyed by the REAL_AGENT/WORKER/SERVICE/TOOL
taxonomy that exists nowhere in the code today) but needs a new App B endpoint +
the running stack (Docker down). **Interim:** a thin frontend adapter loads the
ONE real catalog endpoint (`/admin/presets`) for identities (provenance REAL),
marks runtime status/health/cost **UNAVAILABLE**, and reconciles duplicates in
`kai-nexus-agents.js`. The registry model is source-agnostic, so wiring the
aggregator later is a drop-in. **We never claim REAL agent activity until a real
event/endpoint is exercised (§5AC).**

## D10 — Signal dedupe + corroboration (§6K/§6L) — 2026-08-25

**Problem:** the research digest does no dedup (same story recurs across cycles),
and "corroboration" must not be faked by counting mirrors of one article.

**DECISION (in `kai-nexus-intel.js`):**
1. **Dedup exact articles** by **canonical URL** (hostname without `www.` +
   path without trailing slash, query/hash dropped) → one signal per article.
2. **Corroborate an EVENT** by grouping remaining signals on a **normalized
   headline** and counting **DISTINCT sources** (by domain, else source name).
   `CORROBORATED` only when **≥2 distinct sources**; the primary-typed source is
   kept as the representative. **Mirrors/syndications from ONE source do NOT
   count** (same domain → 1 distinct → `SINGLE_SOURCE`/`PRIMARY_SOURCE`).
3. Distinct articles (different headlines) are never merged.
Chosen over content-hashing (the digest stores no body) and over title-similarity
fuzzing (would wrongly merge distinct stories). URL-canonical + distinct-domain is
precise and honest. **Freshness never fabricated:** the digest lacks `published_at`,
so freshness derives from the real `generated_at` ("fetched"), and published time
shows UNKNOWN.

## D11 — Intelligence security posture (§6AD/§6AE) — 2026-08-25

External signal content is **UNTRUSTED DATA**. `source_url` is scheme-validated
(`safeUrl` — absolute http/https only; javascript:/data:/file:/relative → null +
flagged); all text renders via `textContent` (never innerHTML/eval), so a
`<script>`/`onerror` headline is inert. Prompt-injection isolation:
signal text never enters KAI's system/tool instruction path — "Ask KAI about this
signal" places the text into the command bar as a **user message** (data), so
"ignore previous instructions and deploy" is displayed + discussed, never
executed. Every signal is `untrusted:true`.

## D12 — Security mode is POSTURE + GOVERNANCE, not threat-intel; severity is measured-or-inferred (§20/§21) — 2026-08-25

**Evidence (docs/KAI_SECURITY_SOURCES.md):** a 6-reader audit found NO runtime
CVE/SAST/IDS feed (Phase 6 confirmed). The only sources with a **measured**
severity are the Supreme **host/ops** scanner (process/port/disk/git — not threat
intel) and App A's defensive file scanner. The richest REAL security *facts* are
**governance denials** in `data/governance/audit.jsonl` (scope-denied /
destructive-without-approval), which carry **no severity**.

**Options:** (A) build a SOC/threat dashboard (fabricates a feed that does not
exist — rejected, violates §39/§47); (B) a **Security & Governance Posture** view
over the REAL posture + denial + host/ops surfaces, with severity measured where it
exists and *explicitly inferred* (never claimed) where it does not.

**DECISION: B.** `kai-nexus-security.js` is the single **alert doctrine**: severity
is `measured` only when the source carries one; otherwise `inferGovernanceSeverity`
applies ONE documented rule (destructive-without-approval→high, scope-denied→medium,
failed→medium/high, success→info) tagged `severity_origin:'inferred'`. Consequences,
enforced + tested: (1) posture is **never green unless a real source confirms it** —
unmeasured → UNKNOWN/UNAVAILABLE (fixes the hard-coded `nx-h-security='CLEAR'`
placeholder); (2) an **INERT owner gate** (`API_KEY` unset) is a measured CRITICAL;
(3) **inferred severities never drive the top-line posture and never escalate the
header past 'warning'** — only a *measured* critical (or the inert gate) shows
CRITICAL; (4) audit/scanner text is **UNTRUSTED** (`untrusted:true`, `escapeHtml`,
textContent) because `error`/`detail` can embed attacker-influenced input (e.g. a
path in a scope-denied action); (5) `actor` is surfaced but caveated as a
caller-supplied string, not authenticated identity.

**Live-path (D8/D9 pattern):** App-A-same-origin posture is REAL and reachable
(`/admin/session/whoami`, `/admin/kai-bridge/health`, `/api/security/status`,
`/api/suprema/status`, on-demand `/api/security/scan`); App B governance-audit +
host/ops-scanner + failures are **EXTERNAL_BLOCKED** (cross-app → need the
`/admin/kai/*` bridge allowlist + App B running). Coded fail-soft; UNAVAILABLE until
then. Reuses the existing `store.alerts` strip + header counter (no parallel alert
system) and the Supreme low/medium/high/critical ladder (no invented severity scale).

## D13 — Memory constellation = the KG ego-graph; everything else is flat records (§22) — 2026-08-25

**Evidence (docs/KAI_MEMORY_SOURCES.md):** a 5-reader audit found exactly ONE real
graph — the App B Knowledge Graph (`data/kg/kg.db`: directed, typed, labeled
property graph with named-relation edges, real adjacency + BFS). Every other store the
platform calls "memory" (NarAI tiers, `core.memory`, Supabase `memory_notes`, pgvector
`memories`, twin, persona, relationship, journal, learning, failures) is **flat records
with no edges**. The KG has **no edge weights**, **no whole-graph dump**, **no HTTP
traverse**, is **empty at rest** (operator hand-teaches triples; no auto-extraction), and
is reachable from the App-A Nexus only via the governed bridge (`kai.chat` scope,
default OFF).

**Options:** (A) a rich force-directed "memory graph" federating all stores with
similarity/tag edges (fabricates edges + infra that do not exist — rejected, §39/§47);
(B) a truthful **KG ego-graph** + a flat records summary.

**DECISION: B.** `kai-nexus-memory.js` models the KG exactly and lays it out
deterministically (degree-ranked, no physics, no jitter). Enforced + tested honesty:
(1) **no fabricated edges** — `buildEgoGraph` keeps an edge only where a real triple's
both endpoints are present nodes, drops missing-endpoint edges and self-loops, never
backfills; (2) **no edge weights** — edges render uniform; a numeric in `attributes`
stays there, never promoted to thickness; (3) **no recency-glow / importance-sizing**
(neither is stored); (4) **ego-graph, never "the full graph"** — no dump exists, so we
draw a bounded neighborhood and label counts from `/stats` as **"500+"** at the ≤500
sample cap; (5) labels/attributes are **UNTRUSTED** (`untrusted:true`, `escapeHtml`,
textContent) — a `<script>` label is inert. **Live path = EXTERNAL_BLOCKED** (bridge OFF
+ Docker down + KG empty) → coded fail-soft, renders an honest empty/unavailable state.
DEMO scenarios show a realistic hand-taught WheellsVerse KG. Flat stores appear only as
a labeled records summary (counts by tier/category), explicitly non-graph, **no invented
links**. Reuses the agent-constellation SVG layout pattern (no new graph engine).

## D14 — Functional halo bound to REAL signals; §24 safety is a tested boundary (§23/§24) — 2026-08-25

**Evidence (docs/KAI_HALO_SOURCES.md):** the halo was half-functional — a real `kaiState`
machine (driven by the governed SSE lifecycle) but decorative motion, only 3/8 states
styled, no env reaction, and a bus with zero subscribers. The only rich "activity"
signals (agent/tool/procedure events) are DEMO-only; no backend emits tool/step events.
A real §24 leak vector exists but is backend + config-dependent (`ollama_adapter` streams
`<think>` verbatim if a reasoning model is configured; default model is safe).

**Options:** (A) add elaborate always-on halo animation + a live "tools running" viz
(fabricates a busy signal that has no real source — rejected, §39/§47); (B) make motion
**bind to real events** and keep the viz to observable, CoT-safe labels.

**DECISION: B.** `kai-nexus-pulse.js` is the **§24 safety boundary**: `describeEvent(ev)`
derives its label **structurally** from the event topic + a small name/count allowlist and
**never reads content fields** (`text/reasoning/thought/scratchpad/prompt/args/critique/…`),
so a "thinking" indicator cannot leak chain-of-thought — unit-tested, incl. a payload
stuffed with secrets that never reach the label. Enforced + shipped: (1) the halo shows a
distinct visual for **every real `kaiState`** (pure CSS on the existing `data-state`
contract) and reacts to `data-env` — no fabricated states; (2) a **one-shot pulse** fires
on real bus events via the previously-unused `on('*')` seam, reduced-motion-guarded; (3)
the activity indicator shows **labels only**, tagged DEMO when a scenario drives it — a
"tools running" signal is DEMO-only (no real backend feed) and never presented as REAL;
(4) `stripReasoning` (tested: closed/variant/unclosed-trailing think-tags, no-op on normal
answers) is applied as **client defense-in-depth** at the presence render/speak path, with
the adapter-level strip documented as the proper backend fix. Reuses the one `setKai`/
`paintKai` choke point + the existing bus + `REDUCE_MOTION` — wiring, not new infrastructure.
