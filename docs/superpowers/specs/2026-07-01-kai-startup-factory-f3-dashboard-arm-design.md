# KAI Startup Factory — F3 (Factory HQ + Arm/Observe) Design

**Status:** Draft for operator review — QUEUED (do not build until F2d smoke is green + R1 confirmed live)
**Date:** 2026-07-01
**Builds on:** F1 loop-core, F2a runner, F2b worktree/gates/PR, F2c carry-overs + opt-in real-cycle wrapper (`factory/cycle.py`). Engine spec: `2026-06-30-kai-startup-factory-design.md`. F2d runbook: `2026-07-01-...-f2d-real-smoke-runbook.md`.

---

## 1. Summary

F3 turns the opt-in real cycle into an **observable, armable nightly daemon** with a **standalone Factory HQ** web page. When armed, the nightly worker runs a REAL cycle (real `claude -p` + worktree + daemon-verified gates) for **every active project** and opens **real PRs**. Everything above the commit/PR ceiling stays gated: merge-to-main and all deploys are AMBER (one-click approve in Factory HQ); PHI-prod is RED.

### Decisions locked (brainstormed 2026-07-01)
1. **Dashboard = standalone Factory HQ** (own FastAPI router + static page, like the W-MOS Portfolio HQ), not a KAI-admin tab.
2. **Arming = all active projects, real PRs** — when armed, the nightly worker ticks every active project with the real runner and opens real PRs immediately (no shadow phase in the design; see §7 for the recommended *operational* rollout).

### Non-negotiable rails (unchanged from the engine spec — hold at any arming width)
- **Dormant by default** (`FACTORY_ENABLED`), **kill-switch** (`FACTORY_KILL`) halts instantly.
- **Merge-to-main + all deploys = AMBER** (operator approves in Factory HQ). **PHI-prod = RED.**
- **Budget ceilings** ($100/project, $500/portfolio per month) pre-empt spend.
- **Kill-criteria:** 3 consecutive blocked cycles → `blocked_red` → excluded from ticking.
- **Synthetic-data only**; branch-limited push; scoped-Bash + `DENY_TOOLS`; fail-closed gates. All carried from F2a/F2b, verified live in F2d.

---

## 2. Goals / Non-goals

### Goals
- A **read-only observability surface** (Factory HQ): per-project status, last/recent cycles, open PRs, budget burn, audit trail, kill-switch state.
- **Arm/disarm/kill controls** that flip the nightly worker between dormant, armed-real, and killed.
- Wire the **real runner + worktree lifecycle** (F2c `cycle.run_with_worktree`) into `scheduler.start_worker` so the nightly sweep runs real cycles for all active projects when armed.
- An **AMBER approval queue UI** — one-click approve/reject for merge-to-main and staging deploys.
- **Morning report** to Telegram (reuse KAI digest channel) + on the dashboard.

### Non-goals (F3)
- No auto-merge or auto-deploy (permanently gated).
- No PHI / real customer data (F4 tenant boundary).
- No change to the engine's safety envelope, gates, or push boundary — F3 only *observes* and *arms*.
- No multi-user dashboard/auth beyond the operator admin-token.

---

## 3. Architecture

New pieces (F3 adds a thin API + UI + the arm-wiring; the engine is unchanged):
```
factory/
  hq/
    __init__.py
    api.py        # FastAPI router: read endpoints (status/cycles/prs/budget/audit) + arm/kill + approve
    rollup.py     # read-side aggregation across active projects (status, cycles, spend, open approvals)
    report.py     # (reuse factory/report.py + a Telegram sender via KAI digest)
  scheduler.py    # MODIFIED: start_worker, when armed, runs cycle.run_with_worktree per active project
frontend/factory-hq.html   # standalone single-file page (vanilla JS; polls the API; admin-token gated)
```
- **Mount:** a FastAPI router `factory.hq.api` mounted at `/factory-hq/*` on the KAI backend app (same app that hosts the other admin routers), + the static page served at `/factory-hq`. Auth = the existing admin-token dependency (constant-time compare), reused, not reinvented.
- **State source:** all reads come from the existing on-disk state (`data/factory/**`: `projects.json`, `<slug>/cycles.jsonl`, `<slug>/known_issues.jsonl`, `spend.jsonl`, `approvals.jsonl`, `audit.jsonl`). `rollup.py` aggregates; no new datastore.
- **Arm wiring:** `scheduler.start_worker(make_runner, *, real=False)` — when `real=True` and armed, the nightly `_loop` calls `cycle.run_with_worktree(slug, now_iso=..., make_runner=make_runner)` for each `project.list_active()` instead of `run_once(mock)`. Dormant/kill gates unchanged. The production entrypoint constructs `make_runner=lambda wt: ClaudeCliRunner(wt)`.

---

## 4. Factory HQ — surface

Read endpoints (all admin-token gated):
- `GET /factory-hq/overview` → per-project: slug, phase (active/done/dormant/blocked_red), last cycle (status, task, pr_url, cost, at), consecutive_failures, month-to-date spend vs ceiling.
- `GET /factory-hq/project/{slug}` → recent cycles, open PRs, known_issues, backlog counts, roadmap %.
- `GET /factory-hq/approvals?status=pending` → the AMBER queue (merge/deploy items).
- `GET /factory-hq/audit?limit=50` → recent audit records (bounded).
- `GET /factory-hq/control` → `{enabled, kill, armed_real}`.

Write endpoints (admin-token + audited):
- `POST /factory-hq/arm` / `POST /factory-hq/disarm` → set `FACTORY_ENABLED` control flag.
- `POST /factory-hq/kill` / `POST /factory-hq/unkill` → set `FACTORY_KILL`.
- `POST /factory-hq/approvals/{id}/approve` / `/reject` → resolve an AMBER item (compare-and-set; approving a *merge* enqueues the actual `gh pr merge`, a *deploy* enqueues the deploy — both still operator-initiated, never autonomous).

The page (`frontend/factory-hq.html`): a scoreboard of projects (phase, last-cycle badge, spend bar, PR link), a prominent **KILL** button + **ARM/DISARM** toggle (with a typed confirm to arm), the **approval queue** with one-click approve/reject, and a budget/audit panel. Vanilla JS polling; admin-token entered once and kept in-memory (never in the DOM), mirroring the W-MOS HQ + KAI admin conventions.

---

## 5. Arming semantics (the aggressive path, safely bounded)

When **armed** (`FACTORY_ENABLED=1`, `FACTORY_KILL=0`) the nightly worker (at `FACTORY_TICK_HOUR`, default 02:00 local) runs, for **each `list_active()` project**:
`cycle.run_with_worktree(slug, now_iso, make_runner=real)` → real cycle → real PR on `factory/<slug>/<task>`.

Bounded by the rails: budget pre-emption can `budget_queued` a project mid-sweep; a project hitting 3 consecutive blocks flips `blocked_red` and drops out; merge/deploy never fire (AMBER → approval queue); kill-switch halts the whole sweep immediately. The morning report (Telegram + HQ) summarizes: per project — PR opened / blocked / budget-queued, cost, and anything in the approval queue.

**Cost note:** arm-all means N projects × one real cycle/night. With model-tier routing + budget ceilings this is bounded, but it is real spend every night — the HQ budget panel and the per-project ceilings are the control. The daemon stays dormant until you explicitly arm.

---

## 6. Build phases (queued; each independently shippable)

- **F3a — Factory HQ (read-only observe):** `hq/rollup.py` + `hq/api.py` read endpoints + `factory-hq.html` scoreboard/budget/audit. No arming, no writes. Fully testable against fixture `data/factory/**`. This is the safe first slice — pure observability.
- **F3b — Arm/kill + real-runner wiring:** `scheduler.start_worker(..., real=True)` runs `run_with_worktree` per active project when armed; HQ arm/disarm/kill controls (audited, typed-confirm to arm). Tested with a mock `make_runner` + the dormant/kill/armed gate logic (no real claude in tests).
- **F3c — AMBER approval queue UI + Telegram report:** the approval queue endpoints + one-click UI (compare-and-set), and the morning report to the KAI digest/Telegram channel. Tested against fixture approvals.

Each phase gets its own TDD plan when F3 is actually built (post-F2d).

---

## 7. Recommended operational rollout (design supports arm-all; roll out gradually)
Even though the design arms all active projects with real PRs, the safe sequence to *reach* that is:
1. **F2d green** — the real smoke passes; R1 denial confirmed live.
2. Build **F3a** (observe) — watch real cycles you trigger manually via `cli --real` show up in HQ.
3. Build **F3b** but first arm with **one** project for a few nights (there's nothing stopping you registering a single active project); review the morning PRs.
4. Once trusted, register the rest as active → the same armed daemon now sweeps all of them. No code change needed to widen — it's just which projects are `active`.

This keeps the aggressive design while letting you dial blast radius via the active-project set, not a code change.

---

## 8. Risks
- **R1 — nightly cost:** arm-all × real cycles = real nightly spend. *Mitigation:* budget ceilings pre-empt; HQ budget panel; start with a small active set (§7).
- **R2 — a bad autonomous PR merged:** the reviewer is an LLM. *Mitigation:* merge is AMBER — a human approves every PR in HQ; security+build are hard gates blocking the PR.
- **R3 — HQ is a new authenticated surface:** *Mitigation:* reuse the existing admin-token dependency (constant-time), no new auth; token header-only (never DOM); all writes audited; bounded list endpoints.
- **R4 — arm/kill race with the running worker:** *Mitigation:* the worker re-checks `kill_engaged()`/`is_enabled()` each sweep and each project; kill takes effect at the next project boundary at worst.

---

## 9. Definition of done (F3)
- Factory HQ page shows live per-project status, cycles, open PRs, budget, audit; kill-switch + arm toggle work.
- When armed, the nightly worker runs real cycles for all active projects and opens real PRs; dormant-by-default holds; kill halts instantly.
- Merge/deploy remain AMBER with a working one-click approval queue; nothing merges/deploys autonomously.
- Morning report to Telegram + HQ.
- Full deterministic test suite green (mock runner + fixture state; no real claude/network in tests); no W-MOS/factory regressions.
