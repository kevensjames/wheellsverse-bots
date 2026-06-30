# KAI Startup Factory — Engine Design

**Status:** Draft for operator review
**Date:** 2026-06-30
**Author:** KAI / Claude (brainstormed with operator)
**Related:** `2026-06-23-wmos-portfolio-os-design.md` (the GTM portfolio engine this builds beside)

---

## 1. Summary

The **Startup Factory** is a persistent, autonomous *software-engineering* daemon. Each night it runs one engineering cycle per active project — pick the highest-priority task, architect it, implement it in an isolated git worktree, review it (independently), test it, security-audit it, then **commit to a feature branch and open a PR** with a morning report. Merge-to-main, all deploys, and anything irreversible stay gated to the operator.

It is **not greenfield.** It reuses the safety machinery from **W-MOS** (`core/portfolio/`) and the planning/governance machinery from **KAI** (`backend/app/services/`). The only genuinely new parts are: an engineering pipeline, a per-project engineering state model, role-agent definitions, an isolated-worktree manager, and a runner that drives **Claude Code in headless (`claude -p`) mode**.

### Decisions locked during brainstorming
1. **Scope sequencing:** build the Factory engine first; the AI Medical Documentation Assistant becomes its first real *tenant* under a separate spec.
2. **Execution model:** persistent autonomous daemon ("repeat forever"), not operator-triggered.
3. **Autonomy ceiling:** the daemon may edit/test/commit to feature branches + open PRs unattended. Merge-to-main = AMBER (one-click approve). All deploys = AMBER. Production deploy of any PHI-touching service = **RED** (operator-only, never autonomous).
4. **Cadence:** nightly batch (one deep cycle per active project, ~02:00 local), operator reviews PRs + report in the morning.
5. **Runner substrate:** headless `claude -p` CLI (reuses the full OMC agent + skill stack), `--output-format json` for structured results and cost.

---

## 2. Goals / Non-goals

### Goals
- A daemon that makes **real, reviewable engineering progress** on one or more software products every night, with zero operator action required to *produce* a PR.
- **Fail-closed safety**: nothing irreversible (merge, deploy, money, infra teardown, secret rotation) happens without operator approval; the daemon is dormant-by-default and kill-switchable.
- **Resumable & idempotent**: a crashed or interrupted cycle never double-commits or loses task state.
- **Bounded, predictable cost** with a hard budget ceiling that halts spend rather than overrunning.
- **Persistent per-project state** (roadmap, backlog, ADRs, metrics, deploy status, known issues) so the daemon resumes instead of re-analyzing from scratch.
- Maximal reuse of W-MOS + KAI primitives; minimal new surface area.

### Non-goals (this spec)
- Building the medical product (separate spec; this engine builds it later).
- Auto-merge to main or any auto-deploy (above the chosen ceiling; explicitly out).
- Touching real PHI or any production customer data (hard invariant, see §8).
- A multi-tenant SaaS UI for external users. This is the operator's internal tool.
- Replacing W-MOS's GTM loop. The Factory builds *software*; W-MOS runs *go-to-market*. They are siblings.

---

## 3. Existing substrate (reuse map)

| Concern | Source file | Disposition |
|---|---|---|
| Daemon worker thread, kill-switch, dormancy gate | `core/portfolio/orchestrator.py` | **Reuse** — new nightly scheduler wraps the same gate logic |
| Action envelope `ActionClass` + fail-closed `dispatch()` | `core/portfolio/actions.py` | **Reuse as-is** |
| Atomic state writes, JSONL audit, approval queue, `compare_and_set` | `core/portfolio/state.py` | **Reuse patterns** (new project state mirrors it) |
| Budget ledger + monthly ceilings | `core/portfolio/budget.py` | **Reuse** (add per-step `cost_usd` ingestion) |
| Precondition evaluation, fail-safe-on-unknown | `core/portfolio/preconditions.py` | **Reuse pattern** |
| Roadmap-item → task steps, `goto/stop/revise` branches | `backend/app/services/planning/{planner,executor}.py` | **Reuse** for task decomposition |
| "Create next tasks from detected issues" | `backend/app/services/planning/remediation.py` | **Reuse pattern** for step 15 |
| Scope + approval gate + audit decorator | `backend/app/services/governance/actions.py` (`@audited`) | **Reuse** for all daemon actions |
| Append-only audit log (redacted) | `backend/app/services/governance/audit_log.py` | **Reuse** |
| Daemon-thread scheduler pattern (minute-poll, env-gated, fail-soft) | `services/{research,digest}/scheduler.py` | **Reuse pattern** for nightly tick |
| Admin tab + router conventions | `backend/app/.../admin_*.py` + `/kai-ui/` | **Reuse pattern** for the Factory dashboard |

**New code (the `factory/` package):**
```
factory/
  __init__.py
  project.py        # Project model + registry (slug, repo path, phase, autonomy overrides)
  state.py          # Per-project engineering state (roadmap/backlog/adr/issues/cycles) — mirrors core/portfolio/state.py
  pipeline.py       # The engineering loop: ordered stages, each with an ActionClass + role
  roles.py          # Role-agent definitions: system prompt + allowedTools + model tier
  runner.py         # AgentRunner: headless `claude -p` invocation, JSON parse, cost, timeout
  worktree.py       # Isolated git worktree create/cleanup per project per cycle
  scheduler.py      # Nightly daemon thread (env-gated, kill-switch, dormancy) — wraps orchestrator gates
  report.py         # Morning report generator (markdown)
  budget.py         # Thin wrapper over core/portfolio/budget for factory ceilings
  cli.py            # Manual `python -m factory tick <slug>` for dev/testing (not the prod path)
```

---

## 4. Architecture & data flow

```
                 ┌─────────────────────────────────────────────┐
   nightly       │  factory.scheduler  (daemon thread)          │
   ~02:00 ──────▶│  - check FACTORY_KILL / FACTORY_ENABLED      │
                 │  - for each ACTIVE project: run_cycle(slug)   │
                 └───────────────┬─────────────────────────────┘
                                 │
                                 ▼
                 ┌─────────────────────────────────────────────┐
                 │  factory.pipeline.run_cycle(slug)            │
                 │  1. claim ONE task (compare_and_set)         │
                 │  2. for stage in PIPELINE:                   │
                 │       action = build_action(stage, task)     │
                 │       dispatch(action, runner, ctx,          │ ◀── core/portfolio/actions.dispatch (fail-closed)
                 │                on_queue=approvals,           │
                 │                on_audit=audit_log)           │
                 │  3. commit + open PR (if all green)          │
                 │  4. write report, update backlog/roadmap     │
                 └───────────────┬─────────────────────────────┘
                                 │ (GREEN / AUTO_CAPPED steps only)
                                 ▼
                 ┌─────────────────────────────────────────────┐
                 │  factory.runner.run(role, task, worktree)    │
                 │  subprocess: claude -p "<role+task>"         │
                 │    --output-format json                      │
                 │    --allowedTools <role allowlist>           │
                 │    --permission-mode acceptEdits             │
                 │    --model <tier>  --cwd <worktree>          │
                 │  → {result, cost_usd, is_error, session_id}  │
                 └─────────────────────────────────────────────┘
```

**Data flow per stage:** the daemon never edits files itself. It builds an `Action`, asks the envelope to dispatch it, and (for allowed classes) the `AgentRunner` invokes `claude -p` against the worktree. The agent edits files / runs tools; the runner captures the JSON result + cost; the daemon records to the audit log and the project's `cycles.jsonl`, then advances.

---

## 5. The engineering pipeline (the nightly cycle)

One `run_cycle(slug)` = one task taken through the pipeline. Stages, their role-agent, and their autonomy class (given the **commit+PR** ceiling):

| # | Stage | Role-agent | Class | Behavior |
|---|---|---|---|---|
| 1 | Load state | *(daemon)* | GREEN | Read roadmap, backlog, known_issues |
| 2 | Select task | Tech Lead | GREEN | Rank backlog (priority + deps); pick one. Skip cycle if none ready |
| 3 | Architect review | Senior Systems Architect | GREEN | Produce/refresh design + ADR for the task |
| 4 | Implement | Production MVP Engineer | GREEN | Edit files in worktree to satisfy the task |
| 5 | Code review | Reviewer (reverse-engineer/refactor) | GREEN | **Separate invocation** — critique, list defects |
| 6 | Refactor | Clean-Architecture Refactorer | AUTO_CAPPED | Behavior-preserving cleanup; skip if review clean |
| 7 | Debug | Debugging Engineer | AUTO_CAPPED | Only runs if tests are red after step 4/6 |
| 8 | Optimize | Performance Engineer | AUTO_CAPPED | Skip unless a measured hotspot exists |
| 9 | Security audit | Security Engineer | GREEN | **Blocks PR on any CRITICAL/HIGH finding** |
| 10 | Generate tests | QA/Test Engineer | GREEN | Add/extend tests; coverage gate |
| 11 | Build & verify | *(daemon)* | GREEN | Run real build + `pytest` in worktree; capture result |
| 12 | Deploy → staging | DevOps Engineer | **AMBER** | Queue for approval (above ceiling) |
| 13 | Monitor | *(daemon)* | GREEN | Only after an approved staging deploy |
| 14 | Report | Writer | GREEN | Append morning report entry |
| 15 | Create next tasks | Tech Lead + remediation | GREEN | Derive follow-ups (incl. from known_issues) → backlog |
| 16 | Commit + open PR | git-master | GREEN | Commit worktree to `factory/<slug>/<task-id>` branch, push, open PR |
| — | Merge to main | — | **AMBER** | One-click approve only |
| — | Deploy to production | — | **RED** (PHI) / AMBER (non-PHI) | Never autonomous for PHI services |

### Stage gating rules
- A stage that **fails** sets the task to `blocked` and stops the cycle for that project (records reason). The next night it can `revise` (reuse `planning.revision`) or wait for the operator.
- Steps 9 (security) and 11 (build) are **hard gates**: a critical security finding or a red build prevents step 16 (PR). The work stays on the branch; the report says why.
- Step 5 reviewer and step 9 security agent are **always separate `claude -p` invocations** from step 4 implementer — enforces "never self-approve in the same context."

### Idempotency, resume, stopping
- **Task claim:** step 1 claims exactly one backlog task via `compare_and_set` (pending→in_progress). A crash mid-cycle leaves it `in_progress` with a `cycle_id`; on resume the daemon detects the orphaned claim, inspects the worktree/branch, and either continues or resets to `pending`.
- **One branch per task:** branch name is deterministic (`factory/<slug>/<task-id>`), so re-runs are idempotent (reuse the branch, don't duplicate PRs — check for an existing open PR first).
- **Stopping condition:** a project is `done` when every roadmap milestone is `done` AND backlog is empty. The daemon then marks it dormant and stops ticking it — no infinite spin on a finished product.
- **Kill criteria:** N consecutive cycles where build never goes green (default N=3) → project auto-flagged RED and skipped until the operator intervenes.

---

## 6. Role-agents

Each role = a `claude -p` system prompt (the operator's pasted role templates), a tool allowlist, and a model tier. Defined in `factory/roles.py`.

| Role | System prompt (source) | `--allowedTools` (illustrative) | Model |
|---|---|---|---|
| Tech Lead | "senior technical lead managing a real engineering team" | Read, Grep, Glob | sonnet |
| Senior Systems Architect | "senior systems architect designing infrastructure for a high-growth startup" | Read, Grep, Glob, Write(adr/**) | opus |
| Production MVP Engineer | "senior full-stack engineer building a production-ready startup MVP" | Read, Edit, Write, Bash(test/build), Grep, Glob | sonnet |
| Reviewer | "senior engineer who just joined a massive unfamiliar codebase … reverse-engineer … do not change functionality" | Read, Grep, Glob | opus |
| Refactorer | "senior software architect rebuilding a messy codebase … do NOT change product behavior" | Read, Edit, Write, Grep, Glob | sonnet |
| Debugging Engineer | "senior debugging engineer investigating a live production issue" | Read, Edit, Bash(test), Grep, Glob | sonnet |
| Performance Engineer | "senior performance engineer optimizing a production application" | Read, Edit, Bash(bench/test), Grep, Glob | sonnet |
| Security Engineer | "senior security engineer auditing a production application" | Read, Grep, Glob, Bash(scanners) | opus |
| QA/Test Engineer | "test strategy … integration/e2e coverage" | Read, Edit, Write(tests/**), Bash(test) | haiku/sonnet |
| DevOps Engineer | "senior DevOps engineer preparing this application for real production deployment" | Read, Write(infra/**) — *staging only, AMBER* | sonnet |
| Writer | "technical documentation writer" | Read, Write(reports/**) | haiku |
| git-master | commit/PR only | Bash(git add/commit/push), Bash(gh pr create) | haiku |

**Tool-allowlist as safety boundary:** no role's allowlist contains push-to-main, prod-deploy, money, or secret-rotation tools. Even a compromised/confused agent physically cannot perform them. `git-master` can push only to `factory/<slug>/*` branches (enforced by a pre-push wrapper script, not raw `git push`).

`--permission-mode acceptEdits` is used because the **worktree is the blast radius** — edits are confined to a throwaway checkout, and the dangerous capabilities are absent from the allowlist regardless of permission mode.

---

## 7. AgentRunner (headless `claude -p`) contract

```python
@dataclass
class RunResult:
    success: bool
    output: str          # the agent's final text result
    cost_usd: float      # from the JSON envelope
    session_id: str | None
    duration_ms: int
    error: str | None = None

def run(role: Role, task: Task, worktree: Path, *, timeout_s: int = 1800) -> RunResult:
    """Invoke `claude -p` for one pipeline stage. Fail-soft: timeout/non-zero/parse-error → success=False."""
```

Invocation shape:
```
claude -p "<role.system_prompt>\n\n<task brief + acceptance criteria>" \
  --output-format json \
  --allowedTools "<role allowlist>" \
  --permission-mode acceptEdits \
  --model <role.model> \
  --cwd <worktree>
```
- **JSON parse** yields `result`, `total_cost_usd`, `session_id`, `is_error`, `num_turns`. The runner records `cost_usd` to the budget ledger and audit.
- **Timeout** (default 30 min/step) kills a hung subprocess → step fails → task blocked.
- **No stdin / non-interactive**: headless mode cannot prompt; any tool outside the allowlist is denied automatically (fail-closed), which the daemon treats as a step failure rather than a hang.
- **Cost gate**: before each step, check `budget.would_exceed(project, portfolio)`; if so, the cycle is queued (not run) and the report flags the budget stop.

---

## 8. Safety envelope, cost, and HIPAA invariants

### Envelope (reused from W-MOS)
- **Dormant by default:** `FACTORY_ENABLED=1` (or `portfolio.json`-style control) arms it; unset → `run_cycle` is a no-op.
- **Kill-switch:** `FACTORY_KILL=1` halts immediately; cannot re-arm until cleared.
- **Classes:** GREEN (run every eligible cycle), AUTO_CAPPED (run only if preconditions hold), AMBER (queue for one-click approval), RED (never autonomous). Unknown/error → refuse (fail-closed).

### Hard invariants (NOT configurable)
1. **Synthetic data only.** The daemon builds and tests against synthetic/fixture data. It never reads, writes, or transmits real PHI or real customer data.
2. **Production deploy of any PHI-touching service is RED.** No override. Gated on a real compliance/BAA checklist the operator clears manually.
3. **No autonomous money movement, secret rotation, or infra teardown.** Not in any allowlist; RED in the envelope.
4. **Every action is audited** to the governance append-only log (redacted inputs, truncated outputs).
5. **Independent review.** Implementer ≠ reviewer ≠ security auditor (separate invocations). A PR cannot open with an unaddressed CRITICAL/HIGH security finding or a red build.

### Cost model (corrected for the CLI substrate)
- The CLI runs **Claude models**, so cost control is **model-tier routing** (haiku for mechanical stages, sonnet standard, opus only for architect/review/security), not Ollama.
- Hard ceilings (defaults, reuse W-MOS values): **$100/project/month**, **$500/portfolio/month**. Exceeding queues the cycle instead of spending.
- Per-step `cost_usd` from the JSON envelope feeds the ledger; the morning report includes spend.
- Nightly cadence (vs. 15-min) keeps spend bounded and reviewable.

---

## 9. Per-project state model

Per §13-Q2's default, each project's **canonical repo is a separate GitHub repo**. The Factory keeps a local clone and creates a throwaway **git worktree per cycle** for isolation. Local layout:

```
data/factory/workspaces/<slug>/   # local clone of the project's separate repo
data/factory/worktrees/<slug>/<cycle_id>/   # ephemeral per-cycle worktree (cleaned up after)
data/factory/<slug>/              # engineering state (below)
  project.json        # {slug, repo_path, phase, autonomy_overrides, deploy_status, metrics, consecutive_failures}
  roadmap.json        # ordered milestones → features; "100% complete" target; each {id, title, status, features[]}
  backlog.json        # tasks: [{id, title, priority, status, depends_on[], source, cycle_id}]
  adr/<n>-<slug>.md   # architecture decision records (append-only)
  known_issues.jsonl  # {kind: security|test|debt, severity, detail, found_at, status}
  cycles.jsonl        # one per nightly tick: {cycle_id, slug, task_id, stages[], pr_url, cost_usd, status, at}
  reports/<date>.md   # morning report
data/factory/
  portfolio.json      # control {enabled, kill}, ceilings {per_project_month, portfolio_month}
  approvals.jsonl     # AMBER queue (merge-to-main, staging deploys) — reuses W-MOS approval schema
  audit.jsonl         # (or shared governance audit log)
  spend.jsonl         # ledger
```
All writes atomic + audited (mirrors `core/portfolio/state.py`). `roadmap.json` is the source of truth for completion; step 15 writes back to `backlog.json`; step 9 appends to `known_issues.jsonl`.

---

## 10. Governance & observability

- All daemon actions wrapped in `@audited(scope="factory.<action>", destructive=...)` (reuse KAI governance). Scopes: `factory.cycle`, `factory.commit`, `factory.pr`, `factory.merge` (destructive), `factory.deploy` (destructive).
- **Dashboard tab** (reuse KAI admin UI pattern): per-project status, last cycle, open PRs, AMBER queue (one-click approve merge/deploy), budget burn, kill-switch toggle, recent audit.
- **Morning report** (markdown + optional Telegram via existing digest channel): per project — task done, PR link, test/coverage result, security findings, cost, next tasks, anything blocked/queued.

---

## 11. Build phases (each independently shippable & tested)

### F1 — Loop core (no real agents; zero API spend)
- `project.py`, `state.py`, `pipeline.py`, envelope reuse, `scheduler.py` (nightly), `report.py`.
- **Mock runner** returns scripted results. Prove the full state machine on a throwaway `hello-service` project.
- Acceptance: unit tests for every stage transition, idempotent task claim, crash-resume, stopping condition, budget queueing, kill-switch, dormancy. All green. No network.

### F2 — Real AgentRunner (headless `claude -p`)
- `runner.py`, `roles.py`, `worktree.py`, `git-master` push-wrapper, PR opener (`gh`).
- Prove end-to-end: one real nightly cycle on `hello-service` produces a real feature branch + PR with a passing test, within budget.
- Acceptance: one real PR opened autonomously; security + build gates demonstrably block a bad PR; cost recorded; worktree cleaned up.

### F3 — Arm + observe
- Dashboard tab, AMBER approval UI, kill-switch UI, Telegram morning report.
- Run dormant→armed on `hello-service` for several nights; operator reviews each PR.
- Acceptance: operator can arm/disarm/kill from UI; approve a queued merge; read morning reports; full audit trail present.

### F4 — Medical product as first real tenant (**separate spec**)
- The AI Medical Documentation Assistant gets its own spec → plan → roadmap.json, then becomes an active Factory project. Subject to all §8 invariants (synthetic data, prod=RED).

This spec covers **F1–F3** (the engine). F4 is out of scope here.

---

## 12. Testing strategy
- **F1:** pure unit tests, deterministic, no network (mock runner). Cover every class transition + every fail-closed branch.
- **F2:** one integration test that runs a real (cheap, haiku) cycle against a fixture repo in CI-safe mode; gate-blocking tests use a deliberately-vulnerable fixture.
- **Property checks:** no role allowlist contains a forbidden tool; no AMBER/RED action ever reaches `runner.run`; budget overrun always queues.
- Reuse the repo's `truth_verification` skill discipline: a step is "done" only when an assertion proves the artifact exists (PR really opened, branch really pushed) — never trust a return string.

---

## 13. Risks & open questions
- **R1 — Headless permission model:** `--permission-mode acceptEdits` + allowlist must be verified to actually deny out-of-allowlist tools non-interactively in this Claude Code version. *Mitigation:* F2 starts with a read-only role to confirm denial behavior before granting Edit.
- **R2 — Cost surprise:** a runaway multi-turn agent could burn budget fast. *Mitigation:* per-step timeout + `--max-turns` cap + pre-step budget check + nightly cadence.
- **R3 — Bad autonomous code merged via a too-eager reviewer:** reviewer is also an LLM. *Mitigation:* merge is AMBER (operator always reviews the PR); security + build are hard gates; reviewer is a *separate* opus invocation.
- **R4 — Worktree/branch sprawl.** *Mitigation:* deterministic branch names, cleanup of merged/abandoned worktrees, one open PR per task.
- **Q1:** Should the morning report go to Telegram (reuse digest) or just the dashboard? (Default: both.)
- **Q2:** Where do project repos live — under `factory/projects/` in this monorepo, or separate GitHub repos? (Default: separate repos, cleaner blast radius; cloned/worktreed locally.)
- **Q3:** `gh` auth for autonomous PR creation — reuse existing token or a scoped factory token? (Default: scoped token, branch-limited.)

---

## 14. Definition of done (engine, F1–F3)
- Daemon arms/disarms/kills; dormant by default.
- Runs nightly; produces real PRs on a test project; never merges/deploys autonomously.
- All §8 invariants enforced and tested.
- Budget ceiling halts spend; cost visible per cycle.
- Full audit trail + morning report + dashboard.
- Resumable across crashes; stops cleanly on a finished project.
