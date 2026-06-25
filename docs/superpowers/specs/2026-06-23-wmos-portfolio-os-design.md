# Wheellsverse Portfolio Operating System (W-MOS) — Phase 0 Design

- **Date:** 2026-06-23
- **Status:** Approved design (pre-implementation). Implementation plan to follow via writing-plans.
- **Repo / branch:** `wheellsverse-bots` @ `_apexdeploy`
- **Author:** brainstormed with operator (Kevens James)

---

## 1. Purpose & Context

The operator wants an admin "toodle" for each of ten open-source-based businesses,
"exactly like SiteBoost," plus a Master Portfolio Supervisor above them, operating the
whole thing like a portfolio company (CEO/CTO/CFO/CMO + ops/growth/data supervisors)
rather than ten unrelated repos.

The ten businesses (whitelabel/fork plays on major OSS projects):

1. n8n Automation Agency · 2. Coolify Hosting · 3. Listmonk Email · 4. Ghost Publishing ·
5. Cal.com Scheduling · 6. Plausible Analytics · 7. Supabase SaaS Factory ·
8. Medusa Commerce · 9. AppFlowy Enterprise · 10. Penpot Design.

### Decisions captured during brainstorming

- **Current state: all greenfield.** Nothing is forked, deployed, or has infra/customers yet.
  Toodles are therefore a *command + build* structure that fills with real data as each
  business actually launches — never a wall of fake metrics.
- **Toodle role: active build-cockpit.** Buttons dispatch real work (research, scaffold,
  generate landing pages, draft SEO/outreach, provision infra), not just track status.
- **Pilot business: n8n Automation Agency.** Its verbs are mostly reversible artifacts with
  exactly one genuinely external action (outreach send), so it proves the full
  propose→approve→execute→audit rail without forcing infra on day one.
- **Dispatch model: full autonomous orchestration (the operator's "C" choice).** A scheduled
  Master Portfolio Supervisor drives each cockpit through KAI's existing autonomous CEO /
  planning / research subsystems with budget ceilings. *Reuses KAI's brain; does not
  re-implement it.*
- **Autonomy envelope: maximum autonomy on non-negotiable safety floors** (see §3). The loop
  thinks/plans/drafts/queues continuously; irreversible/costly actions are bounded by caps,
  allowlists, teardown-required, first-of-kind approval, and a kill-switch.

### Non-goals (Phase 0)

- Building ten fully-functional dashboards wired to live infra (the businesses don't exist yet).
- Re-implementing a CEO/CTO/CFO/CMO from scratch (KAI already provides these).
- Arming the production scheduler (ships dormant; armed in a later spec after hand-verification).
- Wiring the other nine businesses' real integrations (each gets its own future spec).

---

## 2. The Autonomy Envelope (load-bearing safety contract)

Every cockpit and the Master Supervisor obey a traffic-light classification on each action type.
This is the single most important invariant in the system.

- **🟢 GREEN — runs unattended, continuously.** Research, plan generation (inert draft plans),
  artifact generation (n8n workflow templates, landing-page drafts, SEO drafts, lead lists,
  outreach *copy* drafts), self-tests, status/digest updates, internal state writes. Reversible,
  no external side effects, bounded only by token/compute budget.
- **🟢🔓 AUTO-FIRE-WITHIN-CAPS — fires without per-batch approval, only when every precondition
  holds.** Per operator's "looser, most-aggressive" choice this tier contains **outreach sends,
  landing-page publishes, and infra deploys**:
  - *Outreach send:* sending domain finished 14-day warmup · recipient passes suppression +
    dedupe · message carries valid unsubscribe + postal address (CAN-SPAM) · sequence + lead
    list were operator-approved at least once · under operator-set hard daily cap (default
    50/domain/day) · kill-switch live · auto-pause on bounce/spam-complaint spike.
  - *Landing-page publish:* page was approved once · reversible (unpublish handle present).
  - *Infra deploy:* **first-of-kind is still AMBER** (one approval); equivalent repeats auto-fire ·
    deploy target is allowlisted (pre-approved provider account only) · under hard cost ceiling ·
    carries a teardown handle (reversibility is a precondition, not an afterthought).
- **🟡 AMBER — one-click operator approval.** Paid-ad spend; the first-of-kind of any deploy type;
  anything spending external money without a proven-good precedent. The loop assembles these fully
  (with a stored preview/diff) so approval is one tap; it never fires them itself.
- **🔴 RED — never touched by the loop.** Signing agreements, legal/financial commitments,
  production-secret use/rotation, customer PII/payment config, data deletion. Always 100% manual.

### Invariants (each mirrors an existing Wheellsverse pattern)

1. **Budget ceiling** — per-tick, per-business, and portfolio-wide token/compute *and* dollar caps;
   breach → pause + escalate (cf. KAI CEO budget floor).
2. **Kill-switch** — one flag (env `WMOS_KILL` + a Portfolio-HQ button) halts the entire
   orchestrator instantly, mid-tick (cf. browser envelope double kill-switch).
3. **Dormant by default** — scheduler ships OFF behind `WMOS_ORCHESTRATOR_ENABLED`; built,
   hand-verified tick-by-tick, *then* armed (cf. Security worker, Digest scheduler).
4. **Allowlist + teardown for deploys** — same allowlist/SSRF discipline as browser-use; no
   teardown handle ⇒ no auto-fire.
5. **Audit, redaction-by-construction** — every action appended to one audit log; AMBER/auto-fire
   actions store a preview; never raw secrets (cf. Security Center).

---

## 3. Architecture

Poured into the existing SiteBoost toodle mold: FastAPI router + single-file vanilla-JS HTML +
`core/` modules + file-backed JSON + Command Center card + `try/except` mount in `core/api.py`.

### 3.1 Surfaces

| Surface | Route | Job |
|---|---|---|
| **Portfolio HQ** (Master Supervisor) | `/admin/portfolio` | Rollup of 10 businesses; AMBER approval queue; orchestrator/kill-switch/budget controls; executive-council views; audit. |
| **Build Cockpit** (×10, one template) | `/admin/portfolio/<slug>` | Per-business: thesis, phase, plan, dispatch verbs, generated artifacts, outreach campaigns, infra status, audit. |

### 3.2 New backend modules — `core/portfolio/`

Each module has one clear purpose and is testable in isolation.

- `registry.py` — the 10 businesses as data: `{slug, name, thesis, oss_repo, integrations, loop_ref, phase}`.
- `loops.py` — the supervisor-loop engine. One **tick** = `review state → select next action →
  dispatch → record`. **Selection rule (Phase 0, explicit):** pick the first step in `loop.json`
  order that is not yet satisfied and whose preconditions are met; loop order *is* priority.
  (Weighted ROI ranking across businesses is a Phase-2 refinement, out of scope here.)
  Pure/deterministic given state + clock; clock injected.
- `actions.py` — traffic-light classifier + dispatcher + cap enforcement. **The envelope lives here.**
- `orchestrator.py` — the Master Supervisor: schedules ticks across businesses, enforces portfolio
  budget, owns the kill-switch. Dormant behind `WMOS_ORCHESTRATOR_ENABLED`.
- `budget.py` — per-tick / per-business / portfolio spend ceilings + tracking.
- `state.py` — per-business state, artifact store, audit log, approval queue.

### 3.3 API routers — `narai/api/routes/`

- `portfolio_admin.py` — Portfolio HQ endpoints (`/api/narai/portfolio/*`): dashboard rollup,
  approvals queue (list/approve/reject), orchestrator controls (arm/disarm/kill/budget), council
  rollups, audit/events.
- `portfolio_cockpit_admin.py` — Cockpit endpoints (`/api/narai/portfolio/<slug>/*`): overview,
  plan, dispatch a verb, list/inspect artifacts, outreach campaigns (approve-once + status),
  infra/deploy status, audit. One router parameterized by slug serves all 10 cockpits.

Both use the existing `verify_admin_api_key` (X-API-Key / HMAC) auth pattern. Mounted via the
existing `try/except` block in `core/api.py`; HTML served via `@app.get("/admin/portfolio...")`.

### 3.4 KAI integration (in-process, no new infra)

These routers live in the same FastAPI app as KAI's admin routers, so the engine calls KAI
services directly:
- research verbs → KAI **research agent** / tools,
- plan & build verbs → KAI **planning module** (produces an *inert draft plan*, like the
  remediation bridge),
- council reasoning → KAI **CEO** service (inside its existing budget/safety floor),
- auto-fire/AMBER external actions → KAI **gated execution + audit**.

Reused existing modules: `cold_outreach` (gated send + unsubscribe + suppression), `places_scanner`
(lead lists), `siteboost_warmup` (domain ramp), brain wrapper (LLM, local-first), audit log.

### 3.5 Data layout

```text
data/launches/portfolio/
  portfolio.json                 # global: budget ceilings, scheduler flags, kill-switch state
  approvals.jsonl                # AMBER queue (append + status updates)
  audit.jsonl                    # one portfolio-wide audit log (redaction-by-construction)
  <slug>/
    state.json                   # phase, KPIs, last tick, committed spend
    loop.json                    # the executable supervisor loop (see §4)
    artifacts/                   # generated drafts (workflows, landing pages, SEO, leads, proposals)
    campaigns/                   # outreach campaigns + approval + send state
    deploys.json                 # infra deploy records + teardown handles
```
Production override via env vars (e.g. `WMOS_DATA_PATH` → Railway persistent volume), matching the
SiteBoost `SITEBOOST_*_PATH` convention.

---

## 4. Supervisor Loops as Executable Config

This is the bridge from the operator's prose loops to running code. Each business carries a `loop`
definition; the engine ticks through its steps, honoring each step's action class + preconditions.

```jsonc
// data/launches/portfolio/n8n/loop.json
{
  "business": "n8n",
  "steps": [
    { "verb": "research_niche",        "agent": "kai.research",   "class": "green" },
    { "verb": "build_workflow_pack",   "agent": "kai.planning",   "class": "green" },
    { "verb": "generate_lead_list",    "agent": "places_scanner", "class": "green" },
    { "verb": "draft_outreach",        "agent": "cold_outreach",  "class": "green" },
    { "verb": "run_outreach_campaign", "agent": "cold_outreach",  "class": "auto_capped",
      "preconditions": ["warmup_complete", "campaign_approved_once", "under_daily_cap"] },
    { "verb": "publish_landing_page",  "agent": "site_builder",   "class": "auto_capped",
      "preconditions": ["page_approved_once", "unpublish_handle"] },
    { "verb": "deploy_demo_instance",  "agent": "infra",          "class": "auto_capped",
      "preconditions": ["first_of_kind_approved", "under_cost_ceiling", "teardown_handle"] },
    { "verb": "draft_proposal",        "agent": "kai.research",   "class": "green" }
  ]
}
```

The **executive council** (CEO/CTO/CFO/CMO) are portfolio-level loops in the same schema —
e.g. CFO ticks `roll_up_spend → check_ceilings → forecast` (all 🟢). The council tabs in
Portfolio HQ are *views over this shared data*, not four separate engines.

---

## 5. Portfolio HQ tabs

**Overview** (10 businesses × phase / status / revenue=$0 / next-action / risk / committed-spend) ·
**Approvals** (AMBER one-click queue with diff/preview) · **Orchestrator** (arm/disarm scheduler,
kill-switch, budget ceilings, tick cadence) · **Council** (CEO/CTO/CFO/CMO rollups) ·
**Activity/Audit** (append-only).

## 6. Build Cockpit template tabs

**Overview** (thesis, phase, KPIs) · **Plan** (KAI roadmap + inert draft plans) · **Build** (dispatch
verbs as buttons, each badged 🟢/🟢🔓/🟡/🔴) · **Artifacts** (reviewable drafts) · **Outreach**
(campaigns: approve-once → auto-send within caps + suppression + warmup state) · **Infra** (deploy
status + teardown handles) · **Audit**.

## 7. n8n pilot — end-to-end acceptance path

Research an automation niche → generate an n8n workflow pack (artifact) → build a lead list (via
`places_scanner`) → draft a 3-touch outreach sequence (via `cold_outreach`) → operator approves the
campaign once → sends auto-fire within warmup + daily cap → replies tracked → KAI drafts proposals.
One AMBER path exercised: first demo-instance deploy → approve → subsequent equivalent deploys
auto-fire under cost ceiling + teardown handle.

---

## 8. Error handling / safety behaviors

- Budget breach → pause + escalate.
- Daily-cap breach → hold remaining sends.
- Bounce / spam-complaint spike → auto-pause the campaign.
- Deploy without teardown handle → refuse (never auto-fire).
- First-of-kind deploy → route to AMBER even in auto-fire tier.
- Kill-switch → halt all ticks mid-flight; orchestrator will not schedule new ticks.
- Dormant-by-default → no production ticks until `WMOS_ORCHESTRATOR_ENABLED=1` after hand-verification.
- All actions audited; AMBER/auto-fire actions persist a preview before firing.

## 9. Testing

- Unit tests per `core/portfolio/` module (clock + KAI services injected/mocked).
- **Envelope tests**: a 🔴 action must never dispatch; an `auto_capped` action must refuse when any
  precondition is false; budget/cap breaches must pause; kill-switch must halt mid-tick.
- Dormant-state verification (no ticks when flag off).
- `--dry-run` engine mode (plan ticks without side effects).
- The repo `truth_verification` skill applies: every "done/sent/deployed/published" is
  assertion-verified against real state, never a return code or status string.

## 10. Scope of this spec (Phase 0)

**In scope:** Portfolio HQ + Cockpit template + engine (dormant) + envelope/caps/budget/kill-switch/
audit + approvals queue + **n8n wired end-to-end** + all 10 registry entries so HQ shows the full
portfolio (9 in planning-mode with stubbed integrations) + Command Center cards + tests.

**Out of scope (future specs):** real integrations for the other nine businesses; arming the
production scheduler; Phase-2 cross-business ROI optimization. Each subsequent business = config +
content on the proven template, not new engineering.

---

## Appendix A — SiteBoost template reference (the mold being reused)

- Router: `narai/api/routes/siteboost_admin.py` (FastAPI `APIRouter`, X-API-Key auth).
- UI: `frontend/admin/siteboost.html` (single-file vanilla JS, tab-based).
- Core modules: `core/siteboost_state.py`, `core/siteboost_instantly.py`,
  `core/siteboost_onboarding.py`, `core/siteboost_scheduler.py` (+ digest/warmup/events support).
- Mount: `try/except` import + `app.include_router(...)` in `core/api.py`; HTML served via
  `@app.get("/admin/siteboost")`; card in `frontend/admin/index.html`.
- Storage: file-backed JSON under `data/launches/siteboost/`, env-var path overrides for Railway volume.
