# KAI Autonomous CEO — Design Spec

- **Date:** 2026-06-19
- **Status:** Approved (design) — pending implementation plan
- **Repo:** `~/wheellsverse_bots` (daemon `com.wheellsverse.nai`), branch `nexora/phase1-auth`
- **Inspired by:** [paperclipai/paperclip](https://github.com/paperclipai/paperclip) — open-source control plane for "zero-human companies" (MIT). We build the *bounded* CEO paperclip's own reviewers say it lacks.

---

## 1. Summary

Give KAI a **CEO layer**: a thin "executive cortex" that sits *above* KAI's existing subsystems. It owns one company goal, wakes on a schedule, reads company KPIs and subordinate status, and **autonomously reprioritizes work, assigns initiatives, allocates budget, and commands the existing agent workforce** — including authoring and staging changes to KAI's own codebase. It does this through KAI's existing organs (Planning, Digest/Audit, Governance, Learning) rather than re-implementing them.

This is the **maximum-power** configuration, held inside a non-negotiable safety floor.

### Operator decisions (locked)

| Decision | Choice |
|---|---|
| Autonomy mode | **Full autonomous** — no per-step approval for in-policy actions |
| Safety floor | **Standard** — hard budget ceiling + global kill switch + immutable audit + catastrophic-action confirm |
| North-star goal | **Net revenue growth** across all WheellsVerse product surfaces |
| Command scope | **Full empire ops + self-modify code** (production deploy & secret rotation remain on the catastrophic floor) |

---

## 2. Goals / Non-goals

**Goals**
- A persistent company goal that every initiative traces back to (paperclip's core invariant).
- A scheduled **executive heartbeat** that senses KPIs, decides, and acts autonomously.
- Real authority over digital business surfaces and KAI's own subsystems/code.
- An irreducible safety floor that cannot be bypassed by the CEO's own reasoning.
- An operator board answering: *what is the company doing, who's doing it, why, what did it cost, what needs my approval.*

**Non-goals (v1)**
- Spawning brand-new agent role *types* at runtime (v1 commands existing executors + domain presets; new-role creation is a v1.1 stretch).
- Multi-company support (single company singleton).
- Removing the catastrophic floor or budget ceiling (explicitly out of scope — that is not "more autonomy," it is a defect).
- Autonomous production deploy / secret rotation without confirm (these sit on the floor).

---

## 3. Architecture

New scoped subsystem `backend/app/services/ceo/`, master flag `KAI_SCOPE_CEO`, following KAI's established subsystem skeleton: **store + query tool + system-prompt injection + admin router/tab + scheduler**, all flowing through the `@audited` governance decorator.

```text
                ┌─────────────────────────────────────────────┐
                │              CEO LAYER (new)                  │
                │  company goal · executive heartbeat · board   │
                └───────────────┬───────────────────────────────┘
        senses KPIs ◄───────────┤────────────► acts via existing organs
   ┌────────────┬───────────────┼───────────────┬──────────────┐
   ▼            ▼               ▼               ▼              ▼
 Digest/      Audit/        Planning        Governance      Learning/
 revenue      Supreme     (initiatives =    (floor: budget,  Failure
 sources      (health)     plans/tasks)     approval, kill)  (outcomes)
```

The CEO **reuses, does not rebuild**:
- **Initiatives → Planning plans** (`planning.db`, existing goals→steps + executor state machine).
- **KPI feed → Digest + Audit + Supreme** (revenue sources, subsystem health).
- **Floor → Governance** (`@audited`, scope gating, approval gating) + new budget ledger/kill switch.
- **Outcomes → Continuous Learning + Failure memory**.

---

## 4. Components (units with clear interfaces)

### 4.1 `ceo/store.py` — persistence (`data/ceo/ceo.db`, SQLite)
Tables:
- **`company`** (singleton row): `goal_text`, `metric` (`net_revenue`), `target_value`, `target_deadline`, `autonomy_tier`, `status` (`active|paused|killed`).
- **`kpi_snapshot`**: `ts`, `revenue_by_surface` (JSON: stripe/ds24/dwolla/bigcommerce/shopify), `spend_period`, `spend_ceiling`, `system_health`, `audience`, `open_initiatives`, `recent_failures`.
- **`decision`**: `ts`, `kind` (`reprioritize|new_initiative|assignment|spend|escalation`), `rationale`, `linked_plan_id`, `autonomy_tier`, `is_catastrophic`, `approved`, `outcome`.
- **`org_member`**: `role`, `capabilities`, `reports_to`, `budget`, `status` — v1 seeded from existing executors + domain presets.
- **`budget_ledger`**: append-only `ts`, `amount`, `category`, `linked_decision_id`, `running_total_period`.

Interface: plain functions (`get_company()`, `upsert_company()`, `record_snapshot()`, `record_decision()`, `period_spend()`, `list_org()`), no business logic.

### 4.2 `ceo/kpis.py` — sensing
`build_snapshot() -> KpiSnapshot`. Pulls revenue from existing surface clients (Stripe/DS24/Dwolla/BigCommerce), health from Audit/Supreme, plan status from Planning. Fail-soft per source (missing source → 0/None, never crash). Persists via store.

### 4.3 `ceo/brain.py` — executive cognition
`decide(company, snapshot, org_status) -> DecisionSet`. One LLM call (KAI's brain/failover ladder) with a structured executive prompt: *given the company goal, current KPIs, and subordinate/plan status — reprioritize, propose initiatives, assign owners, request spend, flag escalations.* Returns a **validated structured object** (schema-checked; reject + retry on malformed). Pure decision-making; executes nothing itself.

### 4.4 `ceo/floor.py` — the safety floor (most-tested unit)
- `classify(action) -> {in_policy | catastrophic | over_ceiling}`.
- `is_catastrophic(action)`: large money transfer (> `KAI_CEO_CATASTROPHIC_USD`), data deletion, **prod deploy**, secret rotation, mass external send (> `KAI_CEO_MASS_SEND_N` recipients), new external account/funding.
- `within_ceiling(amount)`: checks `budget_ledger` period spend vs `KAI_CEO_BUDGET_CEILING`.
- `is_killed()`: reads kill flag (DB + `KAI_SCOPE_CEO`).
- Enforcement is **independent of the Brain** — the Brain cannot mark its own action "in-policy"; `floor.py` re-derives classification from the action shape.

### 4.5 `ceo/executor.py` — acting
`apply(decision_set)`:
- in-policy → execute now (create/prioritize Planning plans, assign to executors, write `budget_ledger`).
- catastrophic / over-ceiling → create pending-approval item, notify operator, do **not** execute.
- every path → `@audited` + `decision` record.

### 4.6 `ceo/heartbeat.py` — the autonomy engine
Scheduler (mirrors digest scheduler), gated by `KAI_CEO_HEARTBEAT_ENABLED` + scope re-check, default cadence **daily**. Loop: `sense (kpis) → think (brain) → govern (floor) → act (executor) → record + learn`. Supports **dry-run mode** (`KAI_CEO_DRY_RUN=1`): full decide+classify, log everything, execute nothing. No startup beat (explicit enable only).

### 4.7 Self-modifying-code path
A "engineering initiative" → existing executor writes code in an **isolated git worktree**, runs the test suite, produces a **deploy request**. Authoring/testing is autonomous; **prod deploy + secret rotation = catastrophic confirm**. Reuses KAI's worktree + adapter-codegen patterns.

### 4.8 Operator surface
- `routers/admin_ceo.py`: `GET /admin/ceo` (board state), `POST /admin/ceo/run` (manual beat, audited), `POST /admin/ceo/approve/{id}`, `POST /admin/ceo/kill`, `GET /admin/ceo/decisions`.
- **Board tab #17 "CEO"** in `admin.html` — five-question view + pending approvals + spend-vs-ceiling gauge + decision log + kill button.
- **Telegram**: catastrophic confirm requests + daily CEO report (via existing digest channel).
- `CEOQueryTool` (read-only) so KAI-in-chat can introspect the board.
- System-prompt injection (gated by scope): brief "you operate as CEO toward goal X; current KPIs Y" so chat answers are CEO-aware.

---

## 5. The safety floor (always enforced)

1. **Budget ledger + ceiling** — `KAI_CEO_BUDGET_CEILING` per `KAI_CEO_PERIOD`; over-ceiling actions are queued, never executed.
2. **Catastrophic gate** — one-tap confirm for: money transfer > `KAI_CEO_CATASTROPHIC_USD`, data deletion, prod deploy, secret rotation, mass external send, new external account/funding.
3. **Global kill switch** — `POST /admin/ceo/kill` halts heartbeat + freezes in-flight initiatives; `KAI_SCOPE_CEO=0` disables entirely.
4. **Immutable audit** — every decision through `@audited` → `data/governance/audit.jsonl`.
5. **Floor independence** — classification re-derived from action shape in `floor.py`; the Brain's self-assessment is never trusted for gating.

---

## 6. Configuration (operator sets every value)

| Flag | Purpose | Default |
|---|---|---|
| `KAI_SCOPE_CEO` | master enable | `0` (dormant) |
| `KAI_CEO_HEARTBEAT_ENABLED` | arm the scheduler | `0` |
| `KAI_CEO_DRY_RUN` | decide+log, execute nothing | `1` (first runs) |
| `KAI_CEO_CADENCE` | beat frequency | `daily` |
| `KAI_CEO_BUDGET_CEILING` | autonomous spend cap | operator-set |
| `KAI_CEO_PERIOD` | ceiling window | `weekly` |
| `KAI_CEO_CATASTROPHIC_USD` | money-transfer confirm threshold | operator-set |

---

## 7. Testing (TDD, KAI convention)

Order — floor first (highest risk):
1. `floor.py`: ceiling block, catastrophic classification (each category), kill-switch halt, floor-independence (Brain cannot bypass).
2. `store.py`: schema, singleton invariant, append-only ledger.
3. `kpis.py`: fail-soft per missing source.
4. `brain.py`: malformed decision rejection/retry; goal-chaining invariant (every initiative links to company goal).
5. `executor.py`: in-policy executes, catastrophic/over-ceiling queue (don't execute), audit on every path.
6. `heartbeat.py`: dry-run executes nothing; no startup beat; scope re-check.
7. Surface: board read, approve flow, kill endpoint.

---

## 8. Rollout

Ships **dormant** (`KAI_SCOPE_CEO=0`), like Security Center. Activation:
1. Daemon restart with flags.
2. Set company goal + budget ceiling + catastrophic threshold via board.
3. Run **dry-run** for ≥1 cycle; review the decision log.
4. Flip `KAI_CEO_DRY_RUN=0` to arm autonomous execution.
5. Kill switch + scope flag remain the instant off-ramps.

---

## 9. Open items / future (v1.1+)

- Runtime creation of new agent role *types* (v1 commands existing workforce only).
- Autonomy *tiers* per surface (e.g., higher ceiling for low-risk surfaces).
- Persistent strategic memory beyond decision log (quarterly strategy doc the CEO maintains).
- Multi-company / portfolio view.
