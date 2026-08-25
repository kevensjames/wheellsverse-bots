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
