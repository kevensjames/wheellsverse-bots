# KAI Autonomous CEO — Setup & Safety Runbook

The CEO layer ships **dormant**. Nothing autonomous happens until you opt in.
Build status: engine + tool + system-prompt injection + REST API are live and
tested; the dashboard tab and the autonomous scheduler's `router_factory` are
the remaining wiring (see "Follow-ups").

## What it is
A thin executive cortex above KAI's existing organs: one company goal, a
heartbeat that reads KPIs and turns them into **initiatives** (created as *draft*
Planning plans you still approve), held inside a hard safety floor.

## Safety floor (always enforced — `floor.py`)
- **Budget ceiling** — `KAI_CEO_BUDGET_CEILING` per `KAI_CEO_PERIOD`; anything that
  would exceed it is queued, never executed.
- **Catastrophic gate** — large money transfers (> `KAI_CEO_CATASTROPHIC_USD`),
  data deletion, prod deploy, secret rotation, mass sends (> `KAI_CEO_MASS_SEND_N`),
  new external accounts → escalated, never auto-executed.
- **Kill switch** — `POST /admin/ceo/kill` or `KAI_CEO_KILLED=1` halts everything.
- **Master scope** — `KAI_SCOPE_CEO=0` (default) disables the whole subsystem.
- The floor re-derives every verdict from the action shape; it never trusts the
  brain's self-assessment.

## Activation order (do these in sequence)
1. Set the company goal + floor limits, e.g. in `.env`:
   ```
   KAI_SCOPE_CEO=1
   KAI_CEO_BUDGET_CEILING=50
   KAI_CEO_PERIOD=weekly
   KAI_CEO_CATASTROPHIC_USD=50
   KAI_CEO_MASS_SEND_N=25
   KAI_CEO_DRY_RUN=1          # decide + log, execute nothing
   ```
2. Restart the daemon. Set the goal:
   `POST /admin/ceo/company {"goal":"Grow WheellsVerse net revenue to $X by <date>","approved":true}`
3. Run a **dry-run** cycle and review:
   `POST /admin/ceo/run {"dry_run":true,"approved":true}` → check `GET /admin/ceo/decisions`
   and `data/governance/audit.jsonl` (action `ceo.run`).
4. When satisfied, arm execution: set `KAI_CEO_DRY_RUN=0`, restart, run again.
   In-policy initiatives now become **draft** Planning plans (you still approve the steps).
5. (Optional) Autonomous schedule: set `KAI_CEO_HEARTBEAT_ENABLED=1` and
   `KAI_CEO_HEARTBEAT_HOUR_UTC` — see Follow-up (b).

## Off-ramps
- `POST /admin/ceo/kill` — instant stop.
- `KAI_SCOPE_CEO=0` + restart — full disable.

## Follow-ups (not yet wired)
- **(a) Real KPI sources** — `kpis._revenue/_security_score/_alerts` currently
  fail-soft to 0/None. Wire them to the real billing / Security Center / Supreme
  accessors for live revenue/security/alert signals.
- **(b) Scheduler router_factory** — `heartbeat.start()` is called at startup but
  stays idle until a `router_factory` (returns `(router, operator_user_id)`) is
  passed. Until then, drive cycles via `POST /admin/ceo/run`. Wire the factory in
  `main.py`'s `_start_ceo_scheduler` using `build_default_router` +
  `_resolve_operator_profile` (mirror `admin_ceo.run_cycle`).
- **(c) Dashboard tab** — a 👔 CEO board tab (goal form, KPIs, decisions, run +
  kill buttons) over these endpoints. Plan Task 10.
- **(d) Self-modify-code path** — engineering initiatives author code in a
  worktree; prod deploy already lands on the catastrophic gate (`prod_deploy` ∈
  `CATASTROPHIC_KINDS`). Build the runner as a follow-on.

## Tests
`cd backend && ../.venv/bin/python -m pytest tests/test_ceo_*.py -q --noconftest`
(28 tests; `--noconftest` skips the Postgres-bound global conftest — the CEO
suite uses isolated sqlite. The router test additionally needs the Postgres test
DB / a live app, so it's covered by the import + route-registration smoke check.)
