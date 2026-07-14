# W-MOS Transformation Plan — Prototype → Controlled Company Operating System

**Scope:** the Portfolio Operating System ("W-MOS") living under `core/portfolio/` in this
monorepo (`/Users/jhonwheeler/conductor/workspaces/wheellsverse-bots/istanbul`), its FastAPI
surface in `narai/api/routes/portfolio_*.py` and `core/api.py`, and its operator UI in
`frontend/admin/portfolio*.html`.

**Author's stance:** this is a staged engineering plan grounded in the *actual* code as it
exists today (verified file-by-file, line references below). It is deliberately incremental:
the existing safety seed — `core/portfolio/actions.dispatch` — is preserved and *grown into*
the universal gateway rather than replaced. No big-bang rewrite.

**Status legend:** ☐ not started · ◐ in progress · ☑ done (this branch or the C1 containment branch).

---

## 0. Where W-MOS actually is today (audited baseline)

W-MOS is a real, well-factored prototype with a correct *safety intent* but non-functional
*safety enforcement*. The good bones:

| Asset | File | Why it's load-bearing |
|---|---|---|
| Fail-closed action envelope | `core/portfolio/actions.py:65-114` | `dispatch()` refuses RED, queues AMBER, auto-fires AUTO_CAPPED only if every precondition is truthy, executes GREEN; any unknown class refuses. Pure w.r.t. side effects (injected `adapter.run`, `on_queue`, `on_audit`). This is the natural chokepoint seed. |
| Correct in-process CAS | `core/portfolio/state.py:143-160` | `compare_and_set_approval` transitions `approved→executing` only if *every* row for the id is exactly `approved`; fails closed on tampered/duplicate rows. Prevents double-fire. |
| Action-class model | `core/portfolio/actions.py:20-25` | `GREEN / AUTO_CAPPED / AMBER / RED` enum — the seed of the autonomy ladder. |
| Approval queue | `core/portfolio/state.py:89-140` | JSONL queue + `resolve_approval` atomic rewrite. |
| Adapter registry | `core/portfolio/adapters/__init__.py` | Verb→adapter map behind the `AgentAdapter` protocol; `NoopAdapter` fallback. Adapters are injectable/testable. |

The load-bearing **defects** the audit found (each pinned to code):

- **C1 (CRITICAL, being contained separately — treat as DONE for planning):** the platform
  `API_KEY` is string-substituted into *unauthenticated* `/admin/*` HTML bodies —
  `core/api.py:1697-1700` (`serve_portfolio_admin`), and the same pattern at 1710-1713,
  1746-1749, 1773-1776; the placeholder it fills is `frontend/admin/portfolio.html:82`
  (`const INJECTED='%%API_KEY%%';`). A regression pin already exists in
  `tests/test_wmos_containment.py`. **Follow-ups still owed** (this plan): (1) real
  server-side admin sessions + RBAC to replace the shared key entirely; (2) remove
  **query-param** key acceptance in the global middleware —
  `core/api.py:873` (`request.query_params.get("api_key")`) inside the auth block ending at
  `core/api.py:880`.
- **C2 (CRITICAL): the budget ceiling is decorative.** The orchestrator sweep explicitly
  *defers* the budget check (`core/portfolio/orchestrator.py:7-11` comment; the sweep at
  `orchestrator.py:67-83` never calls `budget.would_exceed`). `budget.record_spend`
  (`core/portfolio/budget.py:36`) has **zero production callers** (only `tests/`), so
  `spend.jsonl` is never written, so `budget.spent()` always returns `0.0`. The one place a
  cost precondition *is* checked, `core/portfolio/preconditions.py:36`, passes
  `amount=0.0` — i.e. it asks "would spending nothing exceed the ceiling?" (always False).
  Net effect: **no spend is ever recorded and no ceiling can ever trip.**
- **H1 (HIGH): the only LIVE path to billable adapters has no kill/dormancy check.**
  `POST /api/narai/portfolio/biz/{slug}/tick`
  (`narai/api/routes/portfolio_cockpit_admin.py:73-79`) calls `loops.tick(...)` directly.
  `loops.tick` → `actions.dispatch` enforces action-class rules, but the **orchestrator kill
  switch and dormancy gates** (`orchestrator.kill_engaged()` / `orchestrator.is_enabled()`)
  live only in the *sweep* (`orchestrator.run_once`), which this route bypasses. A killed or
  dormant portfolio can still be ticked one business at a time through this endpoint.
- **H3 (HIGH): the daily-send cap is dead.** `state.record_send`
  (`core/portfolio/state.py:50`) has **zero production callers** (only `tests/`).
  `under_daily_cap` (`preconditions.py:33`) reads `state.send_count`, which is always 0, so
  the cap always passes. The real send adapter (`core/portfolio/adapters/outreach_send.py`)
  never records a send.
- **Money is `float` end-to-end.** `core/portfolio/budget.py` uses `float` for ceilings,
  amounts, and sums (`budget.py:14-15,36-59`). Financial correctness demands integer cents.
- **All persistence is JSON/JSONL with a process-local lock.** `core/portfolio/paths.py`
  (atomic file writes), `state.py` (`threading.Lock` at `state.py:14`). Correct for one
  process; **races and lost writes under >1 worker** (Railway/gunicorn multi-worker).
- **Outreach bypasses the suppression list.** `send_sequences`
  (`core/cold_outreach.py:628-673`) honors only a per-row `skipped` flag; it **never calls
  `is_suppressed`** (`cold_outreach.py:124`). The W-MOS adapter
  (`adapters/outreach_send.compose_sequences_file`) builds its own `sequences.json`
  straight from `prospects.json` with no suppression filter. A globally-unsubscribed address
  can still be emailed via W-MOS.
- **The orchestrator is never wired at boot.** `orchestrator.start_worker`
  (`orchestrator.py:90-111`) has no caller (grep: only the SiteBoost scheduler's own
  `start_worker` is wired, `narai/api/routes/siteboost_admin.py:818`). Meanwhile ~15 unrelated
  ad-hoc scheduler threads *are* started inside `core/api.py`'s `_lifespan_bg`
  (`core/api.py:324-711`: briefing, promo, blast, inbox, video, revenue, SEO, social×3,
  affiliate×4, WhatsApp, reels×3, market-intel, autopilot…). No single job queue / scheduler.

**One-line diagnosis:** W-MOS has a correct safety *shape* wired to inputs that are always
zero and a chokepoint that three of four entry paths route around. The transformation is to
make the checks *real*, make them *unbypassable*, put the money in *cents in Postgres*, and
give the CEO a cockpit that says "Unknown" instead of "$0".

---

## 1. Target architecture (the destination every phase builds toward)

### 1.1 ONE central execution gateway

Every action — a manual admin endpoint, a scheduler tick, an approved-action execution, or an
agent tool call — passes through a single `core/portfolio/gateway.execute(request, services)`.
No `/tick`, no scheduler thread, no admin endpoint, and no adapter may reach a provider except
through it. Ordered, fail-closed checks (deny on any error, never "assume OK"):

```
 1. venture_active?          — venture row status == 'active'
 2. global_kill_off?         — kill_switch(scope='portfolio') not engaged
 3. venture_kill_off?        — kill_switch(scope=venture) not engaged
 4. agent_authorized?        — role manifest: verb ∈ allowed_actions ∧ verb ∉ forbidden_actions
 5. idempotent_not_done?     — idempotency_key unseen (else return prior result, no re-charge)
 6. cost_estimate           — provider-specific estimate in integer cents (None ⇒ STOP)
 7. budget_available?        — atomic reserve ≤ remaining venture ∧ portfolio window
 8. approval_required?       — autonomy level ⇒ auto / auto-reviewed / approval / CEO-only
 9. recipient_suppressed?    — outreach targets checked against suppression list
10. within_volume_limits?    — daily email / action caps not exceeded
11. rollback_available?      — teardown/unpublish/refund handle present for reversible-required
12. → execute adapter, settle actual cost, record evidence, release unused reservation
```

The existing `actions.dispatch` provides checks 4/8/12 in embryo (RED/AMBER/AUTO_CAPPED/GREEN
+ preconditions + fail-closed execute). The gateway wraps it and prepends 1–3, 5–7, 9–11.

### 1.2 Autonomy ladder

| Level | Meaning | Maps from today | CEO's list |
|---|---|---|---|
| **GREEN** | auto, reversible, no external spend/side-effect | `ActionClass.GREEN` | auto |
| **YELLOW** | auto, but flagged for after-the-fact review | *new* | auto-but-reviewed |
| **AMBER** | approval required, or strict auto-cap | `ActionClass.AUTO_CAPPED` (cap) + `AMBER` (approval) | approval-or-strict-cap |
| **RED** | CEO-only: payments, payouts, refunds, contracts, secrets, prod deletion, access changes | `ActionClass.RED` | CEO-only |

Invariant: **an agent may never approve its own AMBER/RED action.** RED requires an
authenticated CEO identity, not an agent token. This is enforced *in the gateway*, not in UI.

### 1.3 Real cents-based ledger

`estimate cost → reserve atomically → refuse if over limit → execute → record actual provider
cost → release unused reservation`. Integer cents only (`BIGINT`). Every expense tagged
`{venture, agent, task, action_id, provider, customer_or_campaign}`. Idempotency keys prevent
double-charge on replay. **Missing/corrupt financial data = STOP, not zero.** Pilot limits:
**$2/day/venture (200¢), $10/day portfolio (1000¢), 5 emails/day/venture.**

### 1.4 PostgreSQL as the system of record

Tables (§Phase 2 DDL): `orgs, ventures, agents, agent_roles, tasks, actions, approvals,
spend_reservations, expenses, revenue, outreach_recipients, suppression, send_history,
experiments, customers, incidents, deployments, audit_events, kill_switches`. DB transactions
guard: **claiming a task, approving an action, reserving budget, recording a send, preventing
duplicate execution, and reading/writing kill-switch state.** ONE job queue + ONE scheduler
replace the ~15 scattered threads.

### 1.5 Eight accountable agent ROLES (not 143 bots)

Chief of Staff · Venture GM (1–2 active) · Engineering · QA/Release · Growth Research · Sales ·
Customer Success · Finance/Risk Controller. Each has a machine-readable manifest:
`allowed_actions / approval_required / forbidden_actions / daily_budget_cents /
daily_email_cap / working_hours / manager / venture`. Roles are measured by **verified business
outcomes**, not activity.

### 1.6 CEO cockpit — five questions, five pages

what made money · what spent money · what is blocked · what needs my decision · what could hurt
the company → **Morning Brief · Portfolio · Agent Workforce · Money Center · Approval Center**.
Unknown values render **"Unknown"**, never `$0`.

---

## 2. Cross-cutting invariants (true in every phase from Day 8)

- **I1 — Single chokepoint.** After Phase 1, the live tick path routes through the gateway;
  after Phase 2, all four entry classes do. A test greps that no module outside
  `core/portfolio/gateway.py` and its sanctioned callers imports `adapters.adapter_for` /
  calls `.run(` directly.
- **I2 — Fail closed.** Any check that cannot be *positively* computed returns deny. This is
  already the discipline in `preconditions._one` (`preconditions.py:39`) and
  `actions.dispatch` (unknown class → refuse). Extend, never relax it.
- **I3 — Cents, never float, in money code.** `core/portfolio/budget.py` and the ledger use
  `int` cents. A test asserts no `float(` in the money modules.
- **I4 — Unknown ≠ zero.** Read models return `None`/"Unknown" for unmeasured values.
- **I5 — Dormant by default.** New autonomous wiring ships disabled
  (`WMOS_ORCHESTRATOR_ENABLED` unset, `control.enabled=false`), armed only after hand
  verification — the discipline already stated in `orchestrator.py:12`.

---

# PHASE 1 — Safety Kernel (Days 8–21)

> **Theme:** make the existing checks *actually fire*, in *cents*, *fail-closed*, and make the
> gateway the *only* way to reach a billable adapter on the live path. Still single-process
> JSON persistence (multi-worker safety is Phase 2's Postgres job), but every number is real.

## 1(a) Objective

Close C2, H1, H3, the suppression bypass, and the float-money defect; land the C1 follow-ups
(kill query-param key; introduce a real admin session seam). Stand up
`core/portfolio/gateway.py` as the universal gateway skeleton and route the one live path
(`/biz/{slug}/tick`) through it. Wire the orchestrator worker at boot — **dormant**. Result: it
is *impossible* to spend money, send an email, or fire an adapter on the live path without a
venture-active + kill-off + budget + suppression + volume check, and every send/spend is
recorded in integer cents.

## 1(b) Concrete work items (files to create / modify)

- **W1.1 — Create `core/portfolio/gateway.py` (universal gateway skeleton).**
  New `execute(request: ActionRequest, services: GatewayServices) -> GatewayResult`. Runs
  ordered checks 1–11 (§1.1) as pure, default-deny predicates, then delegates the class/execute
  tail to the existing `actions.dispatch` (reuse its RED/AMBER/AUTO_CAPPED/GREEN semantics via
  injected `on_queue`/`on_audit`). `GatewayServices` is a Protocol of small callables so Phase 2
  can swap JSON→Postgres implementations without touching call sites. Feature flag
  `WMOS_GATEWAY` (default on for the live path in Phase 1).
- **W1.2 — Wire kill/dormancy into the live tick path (closes H1).**
  Modify `core/portfolio/loops.tick` (`loops.py:47-76`) to call `gateway.execute` instead of
  `actions.dispatch` directly, OR insert an explicit gate before `dispatch`. Modify
  `narai/api/routes/portfolio_cockpit_admin.tick` (`portfolio_cockpit_admin.py:73-79`) to run
  through the gateway. Gateway check 2/3 reuses `orchestrator.kill_engaged()` and check 1 reuses
  `orchestrator.is_enabled()` (`orchestrator.py:32-41`). A killed/dormant portfolio can no
  longer be ticked per-business.
- **W1.3 — Make budget real, in cents (closes C2).**
  1. Rewrite `core/portfolio/budget.py` to integer cents: `Ceilings(per_business_month_cents,
     portfolio_month_cents)`, `record_spend(..., amount_cents:int, ...)`, `spent()→int`,
     `would_exceed(..., amount_cents:int, ...)`.
  2. Add `reserve(venture, agent, action_id, estimated_cents, idempotency_key)` and
     `settle(reservation_id, actual_cents)` / `release(reservation_id)` in a new
     `core/portfolio/ledger.py` (JSON-backed, `_APPROVALS_LOCK`-style process lock for Phase 1;
     Postgres in Phase 2).
  3. **Give `record_spend` production callers:** every adapter that incurs provider cost
     (LLM in `core/portfolio/llm.py`, send in `adapters/outreach_send.py`, infra in
     `adapters/infra.py`) settles its actual cost through the ledger after execution.
  4. **Fix `preconditions.py:36`** — `under_cost_ceiling` must call
     `budget.would_exceed(business, estimated_cents, month)` with the *real* estimate, not
     `0.0`. Estimate comes from the action's `cost_estimate` (gateway check 6).
  5. **Remove the DEFERRED budget skip** (`orchestrator.py:7-11`); the sweep's per-tick call now
     goes through the gateway, which enforces the reservation.
- **W1.4 — Make the daily-send cap real (closes H3).**
  In `adapters/outreach_send.OutreachSendAdapter.run` (`outreach_send.py:71-87`), call
  `state.record_send(business, today, n_sent)` after a successful live send. Gateway check 10
  (`within_volume_limits`) enforces `state.send_count(business, today) + batch ≤ cap` *before*
  the send, so the count can never be silently exceeded. Pilot cap: 5/day (config, not the
  hard-coded `DAILY_CAP=50` at `outreach_send.py:24` / `preconditions.py:15`).
- **W1.5 — Route W-MOS outreach through suppression (closes bypass).**
  In `adapters/outreach_send.compose_sequences_file` (`outreach_send.py:27-64`), skip any
  prospect where `core.cold_outreach.is_suppressed(email)` (`cold_outreach.py:124`). Add gateway
  check 9 as a second wall. Belt-and-suspenders: patch `cold_outreach.send_sequences`
  (`cold_outreach.py:656-662`) to filter `is_suppressed` at send time too, so *no* path emails a
  suppressed address.
- **W1.6 — "Unknown ≠ $0" read path.** `core/portfolio/rollup.py` and the killswitch
  (`killswitch.py:26-51`, which already honestly returns `roi=None` when spend is 0) surface
  `None`/"Unknown" to the cockpit rather than coercing to `0`.
- **W1.7 — C1 follow-ups (admin auth).**
  1. **Remove query-param key acceptance:** delete `request.query_params.get("api_key")` at
     `core/api.py:873`; keep header-only (`X-API-Key`) in the block ending at `core/api.py:880`.
  2. **Introduce a server-side admin session seam:** a signed, HttpOnly session cookie minted by
     a `POST /admin/login` (password → `hmac.compare_digest`, already the pattern at
     `portfolio_admin.py:22-29`), gating `/admin/*` HTML and `/api/narai/portfolio/*`. This is the
     *seam* for RBAC (Phase 2 attaches roles). Keep `tests/test_wmos_containment.py` green (no key
     in HTML body).
- **W1.8 — Wire ONE scheduler, dormant.** Register `orchestrator.start_worker(adapter_for,
  ctx_for)` in `core/api._lifespan_bg` (near the other `.start()` calls, `core/api.py:324-711`),
  gated on `WMOS_ORCHESTRATOR_ENABLED`. It ships **dormant** (`run_once` early-returns while
  `is_enabled()` is false, `orchestrator.py:70-71`). Produce a written inventory of the ~15
  ad-hoc threads (§0) as the Phase 2 consolidation backlog — do **not** delete them yet.

## 1(c) Interface sketch (Phase 1 gateway, JSON-backed)

```python
# core/portfolio/gateway.py  (new)
from dataclasses import dataclass
from typing import Protocol, Callable, Optional
from core.portfolio.actions import Action, ActionClass, DispatchResult, dispatch

@dataclass
class ActionRequest:
    verb: str
    agent: str                      # agent/role id (Phase 2: resolves to a role manifest)
    venture: str                    # slug (registry.Business.slug)
    action_class: ActionClass
    preconditions: list[str]
    payload: dict
    idempotency_key: str            # e.g. f"{venture}:{verb}:{task_id}"
    recipients: list[str] = ()      # emails for outreach; [] otherwise
    estimated_cents: Optional[int] = None   # None ⇒ STOP (fail closed on unknown cost)
    reversible_required: bool = False
    rollback_handle: Optional[str] = None

class GatewayServices(Protocol):        # JSON impls in Phase 1, Postgres impls in Phase 2
    def venture_active(self, venture: str) -> bool: ...
    def kill_engaged(self, scope: str) -> bool: ...          # scope: 'portfolio' | venture
    def agent_authorized(self, agent: str, verb: str, venture: str) -> bool: ...
    def already_executed(self, idempotency_key: str) -> Optional[dict]: ...
    def reserve(self, req: ActionRequest) -> Optional[str]: ...   # None ⇒ over budget
    def settle(self, reservation_id: str, actual_cents: int) -> None: ...
    def release(self, reservation_id: str) -> None: ...
    def is_suppressed(self, email: str) -> bool: ...
    def within_volume(self, venture: str, n: int) -> bool: ...
    def record_evidence(self, record: dict) -> None: ...

@dataclass
class GatewayResult:
    status: str          # executed | queued | refused | duplicate | over_budget | killed
    detail: str
    output: Optional[dict] = None
    reservation_id: Optional[str] = None

def execute(req: ActionRequest, svc: GatewayServices,
            adapter_for: Callable, on_queue: Callable, on_audit: Callable) -> GatewayResult:
    # ordered, fail-closed — first failure short-circuits with an audited refusal
    if not svc.venture_active(req.venture):        return _refuse(req, svc, "venture_inactive")
    if svc.kill_engaged("portfolio"):              return _refuse(req, svc, "portfolio_killed")
    if svc.kill_engaged(req.venture):              return _refuse(req, svc, "venture_killed")
    if not svc.agent_authorized(req.agent, req.verb, req.venture):
                                                   return _refuse(req, svc, "agent_unauthorized")
    prior = svc.already_executed(req.idempotency_key)
    if prior is not None:                          return GatewayResult("duplicate", "replay", prior)
    if req.estimated_cents is None:                return _refuse(req, svc, "cost_unknown")  # STOP≠0
    for email in req.recipients:
        if svc.is_suppressed(email):               return _refuse(req, svc, "recipient_suppressed")
    if not svc.within_volume(req.venture, len(req.recipients) or 1):
                                                   return _refuse(req, svc, "volume_exceeded")
    if req.reversible_required and not req.rollback_handle:
                                                   return _refuse(req, svc, "no_rollback")
    reservation_id = svc.reserve(req)              # atomic; None ⇒ over budget
    if reservation_id is None:                     return _refuse(req, svc, "over_budget")

    # class/approval + execute tail — delegate to the existing fail-closed envelope
    action = Action(req.verb, req.agent, req.action_class, req.preconditions, req.venture, req.payload)
    res: DispatchResult = dispatch(action, adapter_for(req), _ctx(req, svc),
                                   on_queue=on_queue, on_audit=on_audit)
    if res.status == "executed":
        actual = (res.output or {}).get("actual_cents", req.estimated_cents)
        svc.settle(reservation_id, actual)
        svc.record_evidence({**_audit(req), "status": "executed", "reservation_id": reservation_id})
        return GatewayResult("executed", "executed", res.output, reservation_id)
    svc.release(reservation_id)                    # queued/refused ⇒ free the hold
    return GatewayResult(res.status, res.detail, res.output, reservation_id)
```

Note: `dispatch` is unchanged — it stays the pure, unit-tested inner envelope. The gateway is a
*prepend* of the physical-world checks the CEO enumerated, and a *reserve/settle wrapper* around
execution.

## 1(d) Acceptance criteria

- AC1. A `POST /biz/{slug}/tick` on a **killed** or **dormant** portfolio returns
  `refused/killed` and touches **no** adapter (H1 closed).
- AC2. After an outreach send, `spend.jsonl`/ledger contains a cents row tagged
  `{venture, agent, action_id, provider}`, and `budget.spent(month, slug) > 0` (C2 closed).
- AC3. With the venture ceiling set to 200¢/day and 150¢ already spent, a 100¢ action is
  **refused `over_budget`** and no adapter runs (C2 enforced).
- AC4. Sending 5 emails succeeds; the 6th in the same day is **refused `volume_exceeded`**; a
  live send increments `state.send_count` (H3 closed).
- AC5. A prospect whose email is in the suppression list is **not** in the composed sequence and
  is **not** sent to via `send_sequences` (bypass closed).
- AC6. All money in `budget.py`/`ledger.py` is `int` cents; a corrupt/missing ledger row raises
  → the read shows "Unknown", the write path STOPS (I3/I4).
- AC7. `GET /admin/portfolio?api_key=...` no longer authenticates (query-param removed); no
  `/admin/*` HTML contains the real key (`test_wmos_containment` stays green).
- AC8. `orchestrator.start_worker` is invoked exactly once at boot and is dormant by default.

## 1(e) Tests that must exist (`tests/`)

- `test_wmos_gateway_kill.py` — killed/dormant ⇒ `refused`, adapter mock `.run` asserted
  **not called** (H1).
- `test_wmos_gateway_budget.py` — reserve→settle in cents; over-ceiling ⇒ `over_budget`, no
  adapter call; `record_spend` written and summed (C2). Extends `tests/test_portfolio_budget.py`.
- `test_wmos_gateway_volume.py` — 5 ok / 6th refused; `record_send` called on live send (H3).
  Extends `tests/test_portfolio_flags.py`.
- `test_wmos_gateway_suppression.py` — suppressed email excluded from compose *and* send.
- `test_wmos_gateway_idempotency.py` — replaying an `idempotency_key` returns the prior result
  and **does not** re-reserve or re-charge.
- `test_wmos_gateway_cost_unknown.py` — `estimated_cents=None` ⇒ `refused/cost_unknown` (STOP≠0).
- `test_budget_is_cents.py` — asserts no `float(` in `budget.py`/`ledger.py` (I3).
- `test_admin_no_query_param_key.py` — `?api_key=` rejected; header still works.
- Regression: full existing `tests/test_portfolio_*.py` suite (31 files) stays green.

## 1(f) Definition of done

Live tick path is gated end-to-end; C2/H1/H3/suppression/float all have failing-before /
passing-after tests; C1 query-param removed and admin-session seam merged; orchestrator wired
dormant; the ~15-thread inventory is written to this doc's Phase 2 backlog; CI green;
`WMOS_GATEWAY=1` on the live path with the flag documented in `.env.example`.

---

# PHASE 2 — Company Foundation (Days 22–40)

> **Theme:** move the system of record to PostgreSQL with real transactions (fixing the
> >1-worker race), converge **all four** entry paths on the gateway, install the eight role
> manifests with enforcement, and ship the CEO cockpit.

## 2(a) Objective

Replace JSON/JSONL persistence for all *decision-critical* state (budget, sends, approvals,
kill-switch, idempotency, tasks) with PostgreSQL transactions; make budget reservation and task
claiming safe under concurrent workers; land the eight machine-readable role manifests enforced
in gateway check 4/8/10; consolidate the scheduler; ship the five cockpit pages answering the
CEO's five questions.

## 2(b) Concrete work items

- **W2.1 — Postgres data layer.** New package `core/portfolio/store/` using SQLAlchemy 2.0 async
  (already a dependency — `requirements.txt: sqlalchemy[asyncio]>=2.0.0`) + `asyncpg`. Add
  Alembic migrations under `core/portfolio/store/migrations/`. `DATABASE_URL` from env (the repo
  already uses Postgres for KAI — see backend/; W-MOS gets its own schema `wmos`). Keep the
  SQLite `core/db.py` for the *other* products; W-MOS does not share it.
- **W2.2 — Swap `GatewayServices` JSON impls for Postgres impls.** One check at a time, each its
  own PR with a concurrency test: `reserve/settle` → `spend_reservations`/`budget_windows`;
  `already_executed` → `actions.idempotency_key UNIQUE`; `within_volume` → `send_history`;
  kill-switch → `kill_switches` (replaces the `portfolio.json control` blob read in
  `orchestrator._control`, `orchestrator.py:27-48`); approvals → `approvals` table (replaces the
  JSONL in `state.py:89-160`, preserving the `compare_and_set_approval` CAS semantics as
  `SELECT … FOR UPDATE`).
- **W2.3 — Converge all entry paths on the gateway.** Point `core/portfolio/execute.py`
  (approved-action execution, `execute.py:13-52`) and every scheduler tick at `gateway.execute`.
  Delete direct `actions.dispatch` / `adapters.adapter_for(...).run` call sites outside the
  gateway. Add the grep-guard test (I1).
- **W2.4 — Role manifests + enforcement.** Eight files
  `core/portfolio/roles/{chief_of_staff,venture_gm,engineering,qa_release,growth_research,
  sales,customer_success,finance_risk}.yaml`, loaded into `agent_roles`. Gateway check 4
  (`agent_authorized`) enforces `allowed_actions` / `forbidden_actions`; check 8 enforces
  `approval_required` per verb and **"agent never approves own AMBER/RED"**; check 10 enforces
  `daily_budget_cents` / `daily_email_cap` / `working_hours` per role.
- **W2.5 — ONE job queue + ONE scheduler.** A `tasks` table is the queue; the orchestrator
  worker (`orchestrator.start_worker`) is the single scheduler, claiming tasks transactionally
  (`SELECT … FOR UPDATE SKIP LOCKED`). Migrate the Phase-1 inventory of ad-hoc threads onto it
  incrementally; each migrated job is deleted from `_lifespan_bg`.
- **W2.6 — CEO cockpit (five pages).** Extend `narai/api/routes/portfolio_admin.py` +
  `frontend/admin/`. New read endpoints back Morning Brief / Portfolio / Agent Workforce / Money
  Center / Approval Center; all behind the Phase-1 admin session + RBAC. "Unknown" everywhere a
  value is unmeasured (I4).
- **W2.7 — RBAC on the admin session.** Attach a role to the admin session from W1.7; RED
  actions require an authenticated **CEO** principal (not an agent/operator token).

## 2(c) DB schema sketch (PostgreSQL, integer cents, schema `wmos`)

```sql
-- Identity & structure
CREATE TABLE orgs        (id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE ventures    (id BIGSERIAL PRIMARY KEY, org_id BIGINT REFERENCES orgs(id),
                          slug TEXT UNIQUE NOT NULL,            -- registry.Business.slug
                          name TEXT NOT NULL, thesis TEXT,
                          status TEXT NOT NULL DEFAULT 'planning'  -- planning|active|paused|killed
                            CHECK (status IN ('planning','active','paused','killed')),
                          created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE agents      (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                          role TEXT NOT NULL, venture_id BIGINT REFERENCES ventures(id),
                          manager TEXT, active BOOLEAN DEFAULT true);
CREATE TABLE agent_roles (role TEXT PRIMARY KEY, manifest JSONB NOT NULL);  -- loaded from roles/*.yaml

-- Work
CREATE TABLE tasks       (id BIGSERIAL PRIMARY KEY, venture_id BIGINT REFERENCES ventures(id),
                          verb TEXT NOT NULL, assigned_role TEXT,
                          status TEXT NOT NULL DEFAULT 'queued'   -- queued|claimed|done|failed
                            CHECK (status IN ('queued','claimed','done','failed')),
                          claimed_by TEXT, claimed_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE actions     (id BIGSERIAL PRIMARY KEY, task_id BIGINT REFERENCES tasks(id),
                          venture_id BIGINT REFERENCES ventures(id), agent TEXT NOT NULL,
                          verb TEXT NOT NULL, action_class TEXT NOT NULL,   -- green|yellow|amber|red
                          idempotency_key TEXT UNIQUE NOT NULL,            -- dedupe wall (check 5)
                          status TEXT NOT NULL, estimated_cents BIGINT, actual_cents BIGINT,
                          rollback_handle TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE approvals   (id BIGSERIAL PRIMARY KEY, action_id BIGINT REFERENCES actions(id),
                          status TEXT NOT NULL DEFAULT 'pending'   -- pending|approved|executing|executed|rejected|failed
                            CHECK (status IN ('pending','approved','executing','executed','rejected','failed')),
                          requested_by TEXT, decided_by TEXT,      -- CAS: approver ≠ requester (AMBER/RED)
                          decided_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now());

-- Money (integer cents only)
CREATE TABLE budget_windows (venture_id BIGINT REFERENCES ventures(id), window_date DATE NOT NULL,
                          reserved_cents BIGINT NOT NULL DEFAULT 0, spent_cents BIGINT NOT NULL DEFAULT 0,
                          limit_cents BIGINT NOT NULL, PRIMARY KEY (venture_id, window_date));
CREATE TABLE portfolio_windows (window_date DATE PRIMARY KEY,
                          reserved_cents BIGINT NOT NULL DEFAULT 0, spent_cents BIGINT NOT NULL DEFAULT 0,
                          limit_cents BIGINT NOT NULL);
CREATE TABLE spend_reservations (id BIGSERIAL PRIMARY KEY, action_id BIGINT REFERENCES actions(id),
                          venture_id BIGINT REFERENCES ventures(id), provider TEXT NOT NULL,
                          estimated_cents BIGINT NOT NULL,
                          status TEXT NOT NULL DEFAULT 'reserved'  -- reserved|settled|released
                            CHECK (status IN ('reserved','settled','released')),
                          created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE expenses    (id BIGSERIAL PRIMARY KEY, action_id BIGINT REFERENCES actions(id),
                          venture_id BIGINT NOT NULL REFERENCES ventures(id),
                          agent TEXT NOT NULL, provider TEXT NOT NULL, actual_cents BIGINT NOT NULL,
                          customer_or_campaign TEXT,               -- required tag (check below)
                          tags JSONB NOT NULL,                     -- {venture,agent,task,action_id,provider,customer/campaign}
                          created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE revenue     (id BIGSERIAL PRIMARY KEY, venture_id BIGINT REFERENCES ventures(id),
                          amount_cents BIGINT NOT NULL, source TEXT NOT NULL, customer_id BIGINT,
                          occurred_at TIMESTAMPTZ NOT NULL);

-- Outreach, growth, ops
CREATE TABLE outreach_recipients (id BIGSERIAL PRIMARY KEY, venture_id BIGINT REFERENCES ventures(id),
                          email CITEXT NOT NULL, name TEXT, enriched BOOLEAN DEFAULT false,
                          UNIQUE (venture_id, email));
CREATE TABLE suppression (email CITEXT PRIMARY KEY, reason TEXT, via TEXT, suppressed_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE send_history (id BIGSERIAL PRIMARY KEY, venture_id BIGINT REFERENCES ventures(id),
                          recipient CITEXT NOT NULL, action_id BIGINT REFERENCES actions(id),
                          sent_on DATE NOT NULL, provider TEXT, sent_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE experiments  (id BIGSERIAL PRIMARY KEY, venture_id BIGINT REFERENCES ventures(id),
                          hypothesis TEXT, status TEXT, metric TEXT, result JSONB, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE customers    (id BIGSERIAL PRIMARY KEY, venture_id BIGINT REFERENCES ventures(id),
                          email CITEXT, status TEXT, mrr_cents BIGINT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE incidents    (id BIGSERIAL PRIMARY KEY, venture_id BIGINT, severity TEXT, summary TEXT,
                          status TEXT, opened_at TIMESTAMPTZ DEFAULT now(), closed_at TIMESTAMPTZ);
CREATE TABLE deployments  (id BIGSERIAL PRIMARY KEY, venture_id BIGINT, ref TEXT, status TEXT,
                          deployed_by TEXT, deployed_at TIMESTAMPTZ DEFAULT now());

-- Safety & evidence
CREATE TABLE kill_switches (scope TEXT PRIMARY KEY, engaged BOOLEAN NOT NULL DEFAULT false,
                          engaged_by TEXT, engaged_at TIMESTAMPTZ);   -- scope='portfolio' or venture slug
CREATE TABLE audit_events  (id BIGSERIAL PRIMARY KEY, venture_id BIGINT, action_id BIGINT, agent TEXT,
                          verb TEXT, status TEXT, detail JSONB, at TIMESTAMPTZ DEFAULT now());

-- The atomic budget reserve is a single statement (no read-modify-write race):
--   UPDATE budget_windows SET reserved_cents = reserved_cents + :est
--    WHERE venture_id = :v AND window_date = :d
--      AND reserved_cents + spent_cents + :est <= limit_cents
--   RETURNING id;              -- 0 rows ⇒ over budget ⇒ gateway returns over_budget
-- Wrapped in one tx with the equivalent portfolio_windows update; both must succeed.
-- Task claim: SELECT ... FROM tasks WHERE status='queued' FOR UPDATE SKIP LOCKED LIMIT 1;
-- Approval CAS: UPDATE approvals SET status='executing' WHERE id=:id AND status='approved'
--               AND decided_by <> :requester RETURNING id;   -- enforces "no self-approval"
```

## 2(c-ii) Role manifest sketch (`core/portfolio/roles/sales.yaml`)

```yaml
role: sales
manager: venture_gm
venture: n8n
allowed_actions:   [draft_outreach, run_outreach_campaign, draft_proposal]
approval_required: [run_outreach_campaign]         # AMBER — GM/CEO approves, sales cannot self-approve
forbidden_actions: [deploy_demo_instance, issue_refund, rotate_secret, delete_prod_data]
daily_budget_cents: 200          # $2/venture/day pilot ceiling
daily_email_cap:    5            # pilot send cap
working_hours:      "09:00-18:00 America/New_York"
```

## 2(d) Acceptance criteria

- AC1. Two concurrent workers each reserving 150¢ against a 200¢/day venture ceiling: exactly
  one succeeds, one gets `over_budget`; `reserved_cents` never exceeds `limit_cents` (the
  >1-worker race is closed).
- AC2. All four entry paths (manual `/tick`, scheduler, approved-execute, agent tool) reach an
  adapter only via `gateway.execute`; the grep-guard test passes (I1).
- AC3. A Sales-role agent attempting `deploy_demo_instance` is refused `agent_unauthorized`; a
  Sales agent approving its *own* `run_outreach_campaign` is refused (self-approval blocked).
- AC4. A RED action attempted without a CEO principal is refused.
- AC5. Every `expenses` row has non-null `venture_id, agent, provider` and a complete `tags`
  object; a write missing a tag fails.
- AC6. Cockpit renders all five pages; any unmeasured value shows "Unknown", never `$0`.
- AC7. Killing a venture (`kill_switches`) transactionally pauses its tasks and releases its
  open `spend_reservations`.

## 2(e) Tests that must exist

- `test_budget_reserve_concurrency.py` — N threads/async tasks, asserts no over-commit
  (the headline Postgres test).
- `test_task_claim_skip_locked.py` — two claimers never claim the same task.
- `test_approval_no_self_approve.py` — `decided_by == requested_by` on AMBER/RED ⇒ rejected.
- `test_role_manifest_enforcement.py` — allowed/forbidden/cap enforcement per role.
- `test_gateway_single_chokepoint.py` — static grep guard: no `adapter_for(`/`.run(` outside
  the gateway.
- `test_kill_releases_reservations.py` — venture kill pauses tasks, releases reservations.
- `test_cockpit_unknown_not_zero.py` — unmeasured metric renders "Unknown".
- Migration test: Alembic upgrade+downgrade round-trips on a throwaway DB.

## 2(f) Definition of done

W-MOS decision state is in Postgres; the concurrency test proves reservations are race-free;
all four entry paths converge on the gateway (guard test green); eight role manifests enforced;
one scheduler/queue with ≥half the ad-hoc threads migrated; five cockpit pages live behind
session+RBAC; Alembic migrations reversible; CI green including a Postgres service.

---

# PHASE 3 — Shadow Operation (lighter outline)

- **Objective:** run the whole gateway + roles + ledger **live but non-firing** — real
  estimates, real reservations, real evidence — with adapters in dry-run, to prove the control
  plane behaves before any money moves or any email sends.
- **Work items:** flip `orchestrator.set_enabled(True)` with adapters forced dry-run
  (`outreach_send` armed=false/live=false, `outreach_send.py:80-83`); shadow-record what *would*
  have been spent/sent into `spend_reservations`(settled to 0)/`send_history`(provider='shadow');
  daily Morning Brief diff of intended vs. guarded actions; alert on any check that fires
  unexpectedly (reuse the KAI ops alert path from the recent reliability work).
- **DB/interface:** add `mode` ('shadow'|'live') to `ventures`; gateway settles shadow actions at
  0¢ and tags evidence `shadow=true`.
- **Acceptance:** ≥7 consecutive days with zero uncontrolled actions, zero fail-open events, and
  a reconciled ledger (reserved == released for all shadow actions).
- **Tests:** `test_shadow_mode_never_fires.py` (adapter `.run` side-effects mocked & asserted
  inert); `test_shadow_ledger_reconciles.py`.
- **DoD:** a full week of green shadow runs with an operator-signed reconciliation; go/no-go
  written into the Morning Brief.

# PHASE 4 — Pilot (lighter outline)

- **Objective:** one venture (n8n — the only seeded loop, `core/portfolio/seed.py`) goes **live**
  under the pilot limits: $2/day/venture, $10/day portfolio, 5 emails/day.
- **Work items:** arm n8n only (`ventures.status='active'`, `mode='live'`); enrich real leads
  into `outreach_recipients`; arm outreach flags; Finance/Risk Controller role watches the Money
  Center; RED actions (any real payment/contract) remain CEO-only.
- **DB/interface:** real `expenses`/`revenue`/`customers` rows begin accumulating; killswitch
  ROI (`core/portfolio/killswitch.py`) now has real per-venture revenue to divide by.
- **Acceptance:** a real send happens only to a non-suppressed, enriched recipient, within caps;
  daily spend never exceeds ceilings; every dollar is tagged and reconciles; one-click kill
  halts n8n within one scheduler interval.
- **Tests:** end-to-end `test_pilot_n8n_live_path.py` against a staging DB + mocked Instantly;
  `test_pilot_caps_enforced_live.py`.
- **DoD:** two weeks live within limits, zero cap breaches, zero suppression breaches, clean
  daily reconciliation, CEO able to answer all five cockpit questions from real data.

# PHASE 5 — Productize (lighter outline)

- **Objective:** generalize from one piloted venture to the 1–2 active-GM model and harden for
  scale.
- **Work items:** onboard a 2nd venture GM; per-venture budget/role tuning from manifests;
  incident + deployment tracking wired (`incidents`/`deployments`); experiments framework
  (`experiments`) drives Growth Research; consolidate the *remaining* ad-hoc `core/api.py`
  threads onto the one scheduler; SLOs + alerting on the gateway.
- **Acceptance:** two ventures run concurrently within a combined portfolio ceiling; adding a
  venture is a data change (rows + manifest), not a code change.
- **Tests:** multi-venture budget isolation; portfolio-ceiling contention; role/venture
  authorization matrix.
- **DoD:** a documented runbook, the Production-Readiness Gate (below) fully green, and a repeatable
  "add a venture" procedure.

---

## 3. Production-Readiness Gate — 14 conditions (all must be green to run unattended)

1. **Single chokepoint proven.** Every billable action reaches a provider only via
   `core/portfolio/gateway.execute`; the grep-guard test passes; `/tick`, schedulers, and
   approved-execute all route through it. *(I1, AC-2.2)*
2. **Kill works, fast.** Global kill halts all execution within one scheduler interval; venture
   kill halts one venture; both enforced inside the gateway (not UI). *(H1 closed)*
3. **Money is integer cents end-to-end.** No `float(` in `budget.py`/`ledger.py`/store; a test
   forbids it. *(I3)*
4. **Reservations are race-free.** Concurrent reserve cannot exceed a limit; proven by the
   N-worker Postgres test. *(AC-2.1)*
5. **Missing money data STOPS.** `estimated_cents=None` or a corrupt ledger row refuses the
   action and renders "Unknown"; never coerced to $0. *(I4, AC-1.6)*
6. **Idempotent.** Replaying an `action_id`/`idempotency_key` never double-charges or
   double-sends. *(AC-1.idempotency)*
7. **Every expense is fully tagged.** `{venture, agent, task, action_id, provider,
   customer/campaign}`; an untagged expense write fails (NOT NULL + test). *(AC-2.5)*
8. **Daily caps enforced server-side.** $2/venture, $10/portfolio, 5 emails/venture/day; the
   over-limit action is refused, not clamped-silently. *(C2/H3 closed)*
9. **Suppression is honored on every path.** A suppressed recipient is never emailed via the
   W-MOS adapter or `send_sequences`. *(bypass closed)*
10. **No self-approval; RED is CEO-only.** Agents never approve their own AMBER/RED; RED requires
    an authenticated CEO principal. *(AC-2.3/2.4)*
11. **Real admin auth.** Server-side sessions + RBAC replace the injected `API_KEY`; query-param
    key acceptance removed (`core/api.py:873`); no secret in any HTML body
    (`test_wmos_containment` extended). *(C1 follow-ups)*
12. **One queue, one scheduler.** The W-MOS orchestrator is wired at boot, dormant-by-default;
    the ~15 ad-hoc `core/api.py` threads are inventoried and being consolidated onto it. *(W1.8/W2.5)*
13. **Immutable evidence per action.** Every executed action writes an `audit_events` row (and
    ledger row where money moves) with status + detail + rollback handle. *(W1/W2 evidence)*
14. **Rollback exists.** Each auto/yellow action class has a documented rollback; a killed
    venture pauses in-flight tasks and releases open reservations. *(AC-2.7)*

---

## 4. Migration note — growing `actions.dispatch` into the universal gateway (no big-bang)

The gateway is not a rewrite; it is a **prepend + wrap** around the already-correct envelope.

- **Step 0 (done).** `actions.dispatch` (`actions.py:65-114`) is the seed: fail-closed,
  side-effect-pure, RED/AMBER/AUTO_CAPPED/GREEN. Keep its signature and unit tests untouched.
- **Step 1 — introduce `gateway.execute` (Phase 1, W1.1).** Runs physical-world checks 1–11 as
  default-deny predicates, then calls `dispatch` for the class/approval/execute tail. Services
  are JSON-backed (behavior-preserving) and hidden behind the `GatewayServices` Protocol so the
  backend can change without touching call sites. Ship behind `WMOS_GATEWAY`.
- **Step 2 — route the one live path (W1.2).** Make `loops.tick` (`loops.py:47-76`) call
  `gateway.execute` instead of `dispatch`, and point
  `portfolio_cockpit_admin.tick` (`portfolio_cockpit_admin.py:73-79`) at it. This closes H1 with
  a ~10-line change and no schema work.
- **Step 3 — move checks JSON→Postgres one at a time (Phase 2, W2.2).** Each `GatewayServices`
  method swaps its implementation independently (budget, then idempotency, then volume, then
  kill-switch, then approvals), each in its own PR with a concurrency test. The gateway code and
  `dispatch` never change during these swaps.
- **Step 4 — converge the other three entry paths (W2.3).** Point `execute.py` (approved-action)
  and the schedulers at `gateway.execute`; delete their direct `dispatch`/`adapter_for(...).run`
  calls.
- **Step 5 — make bypass impossible.** Flip `WMOS_GATEWAY` default on everywhere; `dispatch`
  becomes an *internal* helper the gateway calls (still unit-tested in isolation) and is no
  longer imported by any route/scheduler. The `test_gateway_single_chokepoint.py` grep-guard
  makes a regression fail CI.

At every step the system is shippable: Step 2 alone closes the highest-severity live defect
(H1) and the budget/send/suppression fixes (W1.3–1.5) ride the same gateway seam; Postgres
(Steps 3–4) hardens correctness under concurrency without reopening the safety logic.

---

## Appendix A — File-reference index (verified against the tree on branch `fix/kai-critical-reliability`)

| Concern | Path:line |
|---|---|
| Action envelope (seed of gateway) | `core/portfolio/actions.py:65-114` |
| Approval CAS (no double-fire) | `core/portfolio/state.py:143-160` |
| Daily-send cap (dead — no callers) | `core/portfolio/state.py:50` |
| Budget ledger (float; no callers) | `core/portfolio/budget.py:36-59` |
| Cost precond passes 0.0 | `core/portfolio/preconditions.py:36` |
| Orchestrator budget DEFERRED | `core/portfolio/orchestrator.py:7-11` |
| Orchestrator sweep (no per-tick budget) | `core/portfolio/orchestrator.py:67-83` |
| Orchestrator worker (never wired) | `core/portfolio/orchestrator.py:90-111` |
| Live tick, no kill/dormancy check (H1) | `narai/api/routes/portfolio_cockpit_admin.py:73-79` |
| Outreach adapter (builds own sequences) | `core/portfolio/adapters/outreach_send.py:27-87` |
| Send path (no suppression) | `core/cold_outreach.py:628-673` |
| Suppression predicate (unused by W-MOS) | `core/cold_outreach.py:124-128` |
| API_KEY injected into admin HTML (C1) | `core/api.py:1697-1700` (+1710-1713,1746-1749,1773-1776) |
| Placeholder in admin HTML (C1) | `frontend/admin/portfolio.html:82` |
| Query-param key acceptance (C1 f/up) | `core/api.py:873` (block ends `:880`) |
| ~15 ad-hoc scheduler threads | `core/api.py:324-711` (`_lifespan_bg`) |
| JSON persistence + process lock | `core/portfolio/paths.py`, `core/portfolio/state.py:14` |
| Adapter registry | `core/portfolio/adapters/__init__.py` |
| n8n pilot loop seed | `core/portfolio/seed.py` |
| Existing W-MOS tests (31 files) | `tests/test_portfolio_*.py`, `tests/test_wmos_containment.py`, `tests/test_killswitch.py` |
| DB dep already present | `requirements.txt` (`sqlalchemy[asyncio]>=2.0.0`) |
