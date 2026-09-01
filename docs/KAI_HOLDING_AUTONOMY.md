# KAI Holding Autonomy — Plan + Work Engine + Continuous Cycle (§11-24, §33, §55)

How KAI turns observed state into safe autonomous work. Dormant on `feat/kai-exec-appb-integration`
(no cron/route wired yet — Wave 7/8). Every gate reuses the certified Capability Fabric.

## Modules
| File | Role |
|---|---|
| `holding/plan.py` | `CurrentPlan`/`PlanTask`, `AutonomyClass` A0–A5, generation from material changes, reconciliation |
| `holding/autonomous_work.py` | `HoldingAutonomousWorkEngine` + `run_cycle` (the OBSERVE→…→UPDATE loop) |
| tests | `test_plan.py` (7/7), `test_autonomous_work.py` (10/10) |

## The loop (§16) — one bounded cycle, one `cycle_id`, no hidden background thread
```
OBSERVE (twin.snapshot)
  → RECONCILE (state_reconciler → MaterialChange[])
  → PLAN (tasks_from_changes → source-cited candidates; reconcile_plan → dispositions)
  → CLASSIFY (AutonomyClass → ActionClass)
  → EXECUTE eligible A0/A1 KAI work via CapabilityExecutionService
  → VERIFY (real evidence required)
  → RECORD + UPDATE twin + owner queue
```
`run_cycle(prev, cur, engine, prior_tasks)` returns `{cycle_id, verdict, material_changes,
plan_dispositions, auto_executed, owner_queued, blocked, failed, autonomy_off, results[]}`.

## Non-negotiable guarantees (all test-backed)
- **No busy-work (§17).** A materially-unchanged cycle derives 0 tasks and executes 0 actions →
  `NO_MATERIAL_CHANGE`. A polling tick alone never creates work.
- **One policy system (§18).** `AutonomyClass` A0–A5 is only a routing label; it maps to the certified
  `ActionClass`, which stays the authoritative gate (`risk.evaluate_policy`). Only A0 (always) and A1
  (after deterministic policy) are auto-eligible; A2 needs a per-grant cert (Wave 3); A3+ are owner-only.
- **Execution truth (§22).** A task COMPLETEs **only** when the service returns `OK` **and** real
  evidence. Status-OK-with-empty-evidence fails — an agent's word is never evidence.
- **Never touch adapters directly (§19).** All execution flows through `CapabilityExecutionService`
  (SSRF guard, operation allowlist, V1 read-only envelope, idempotency, rate limit, audit).
- **Owner boundary (§24).** Owner-required work (A3+/OWNER-assigned) is routed to the owner queue,
  never auto-executed. KAI-doable work is done by KAI and does not reach the owner.
- **Kill switches (§33).** Global autonomy off → 0 autonomous execution; per-company off → that
  company skipped. Maps to the existing `KAI_HOLDING_ENABLED` / per-capability activation.
- **Bounded failure (§55).** Failures are classified (TRANSIENT / CAPABILITY_DOWN / POLICY / LOGIC);
  no infinite retry; `BLOCKED_CAPABILITY` / `BLOCKED_WORKER` when genuinely stuck.
- **Zero fabrication (§58).** MONEY_MODE=MOCK; no financial/destructive path is auto-eligible;
  un-sourced facts stay `UNAVAILABLE` end-to-end.

## Not yet built (next waves)
- Cycle persistence + wiring into a cron/route (the pure `run_cycle` is DB-free today) — Wave 7/8.
- A real per-task **capability resolver** (task → capability/operation/input); today it is injected,
  defaulting to "no path → BLOCKED_CAPABILITY" so nothing runs without an explicit certified mapping.
- Worker-dispatch path for heavy A1 (via `worker_jobs`/`CodingWorkerRouter`) — §23.
- A2 internal-write framework (§34-36) and the Self-Improvement Engine (§37-40) — Waves 3-4.
- `OperationalSelfModel` live-state wiring to the twin/cycle (current mission, last cycle) — §63.
