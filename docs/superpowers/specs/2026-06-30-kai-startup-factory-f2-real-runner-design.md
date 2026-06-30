# KAI Startup Factory — F2 (Real Runner) Design

**Status:** Draft for operator review
**Date:** 2026-06-30
**Author:** KAI / Claude (brainstormed with operator)
**Builds on:** F1 loop-core (`factory/` package, commits 9ac5800..0d6a07b on `_apexdeploy`; 49/49 tests). See `2026-06-30-kai-startup-factory-design.md` (engine spec) and `2026-06-30-kai-startup-factory-f1-loop-core.md` (F1 plan).

---

## 1. Summary

F2 replaces F1's **mock runner** with a **real `ClaudeCliRunner`** that drives Claude Code in headless (`claude -p`) mode, runs each pipeline stage's role-agent against an **isolated git worktree**, enforces **daemon-verified** build/security gates, and opens a **real PR** via `gh`. It also lands the carry-over fixes the F1 whole-branch review flagged.

After F2, one nightly cycle on a registered project produces a **real feature branch + PR** with passing tests and a clean security scan — still fully gated (the daemon never merges, deploys, or touches main; the real runner is opt-in and the engine stays dormant-by-default until F3 arming).

### Locked decisions (brainstormed 2026-06-30)
1. **Gate source = daemon-verified.** Build and security hard gates are decided by the daemon running the objective check itself (pytest for build; gitleaks + any present scanners for security). The role-agent does the work but never self-certifies its own gate.
2. **Testing = fake `claude` stub binary + one operator-gated real smoke.** Tests exercise the real subprocess/arg/JSON/worktree/git seam against a fake `claude` and a local throwaway repo (no network, $0, deterministic). One manual real-`claude -p` end-to-end smoke proves it actually builds.
3. **Kill-criteria = retry-blocked-nightly.** A blocked task is re-attempted each cycle; each failed retry bumps `consecutive_failures`; at N=3 the project flips to `blocked_red` (excluded from `list_active`).

### Host facts (probed 2026-06-30)
- `claude` CLI v2.1.186 at the mise node path; `gh` v2.92.0 authed as `kevensjames`; `gitleaks` present; `trivy` absent; KAI Security Center is NOT on `_apexdeploy` (lives on a nexora branch) → the security gate uses locally-present scanners and degrades gracefully.

---

## 2. Goals / Non-goals

### Goals
- A real runner that turns one pipeline cycle into real, reviewable engineering work (edits in a worktree, tests run, commit, PR) with `cost_usd` tracked from the CLI's JSON output.
- **Fail-closed, daemon-verified gates** — an LLM cannot wave its own PR through.
- **Tool-allowlist as the physical safety boundary** — dangerous capabilities (push-to-main, deploy, money, secrets) are absent from every role's allowlist; branch pushes are restricted to `factory/<slug>/*` by a wrapper.
- **Deterministic, $0 test suite** (fake stub + local repo) + one operator-gated real smoke.
- Land the F1 carry-overs: retry-blocked kill-criteria, budget pre-emption, synthetic-data enforcement, `runner: AgentAdapter` annotations.
- The real runner is **opt-in**; the mock stays default; the engine stays dormant-by-default (F1's `FACTORY_ENABLED`/`FACTORY_KILL`). No autonomous arming in F2 (that's F3).

### Non-goals (F2)
- No dashboard / admin UI / Telegram report wiring (F3).
- No autonomous nightly arming of the real runner against real projects (F3).
- No production deploy, no merge-to-main, no money, no secret rotation (permanently gated; not in any allowlist).
- No real PHI (hard invariant; medical product is F4).
- No multi-project parallelism in a single cycle (F1's sequential sweep stands).

---

## 3. Architecture — verb-aware runner

F1's `pipeline.run_cycle` already calls `runner.run(action) -> dict` and is agnostic to the runner. F2's `ClaudeCliRunner.run(action)` routes by `action.verb`:

| Class | Verbs | Handling | `ok` source |
|---|---|---|---|
| Agent work | architect, implement, review, refactor, debug, optimize, test, next_tasks | `claude -p` in worktree (role prompt + task, per-role allowlist, model tier, JSON out) | subprocess success (exit 0, not `is_error`, not timeout) |
| Daemon gate | build | runner runs project tests/build in worktree | exit 0 |
| Daemon gate | security | runner runs gitleaks (+present scanners) on worktree | no findings |
| Real git | commit_pr | commit → branch-limited push → `gh pr create` | push + PR succeeded |
| Daemon | report | `report.py` writes the morning report (already exists) | always ok |

**New files:**
```
factory/
  roles.py      # Role: key, system_prompt (operator's templates), allowed_tools, model_tier; ROLES registry
  runner.py     # ClaudeCliRunner(AgentAdapter): verb routing, claude -p subprocess, JSON parse, timeout
  worktree.py   # clone/worktree lifecycle + branch-limited push wrapper
  gates.py      # run_build(worktree), run_security(worktree) — daemon-verified objective checks
  pr.py         # commit + push (branch-limited) + gh pr create
```
**Modified F1 files (modest):** `pipeline.py` (kill-criteria retry + budget pre-emption + `runner: AgentAdapter`), `state.py` (retry-blocked helper), `scheduler.py` (`runner: AgentAdapter`), `cli.py` (real-runner opt-in flag). The mock runner remains the default everywhere.

---

## 4. Roles + the `claude -p` invocation

`factory/roles.py`:
```python
@dataclass(frozen=True)
class Role:
    key: str
    system_prompt: str          # operator's role template
    allowed_tools: tuple[str, ...]
    model: str                  # "haiku" | "sonnet" | "opus"

ROLES: dict[str, Role]          # keyed by the pipeline stage's role string
```
Invocation (built by `runner.py`):
```
claude -p "<task brief + acceptance criteria>" \
  --append-system-prompt "<role.system_prompt>" \
  --output-format json \
  --allowedTools "<comma/space-joined role.allowed_tools>" \
  --permission-mode acceptEdits \
  --model <role.model>
# The subprocess is launched with cwd=<worktree> (Python: subprocess.run(..., cwd=worktree)).
# That cwd IS the agent's working/project directory — no separate path flag is needed.
```
- **Allowlists** (illustrative, per §6 of the engine spec): architect = Read/Grep/Glob/Write(adr); implement = Read/Edit/Write/Bash(test); reviewer = Read/Grep/Glob; refactorer = Read/Edit/Write; etc. **No role** has push-to-main / deploy / money / secret tools.
- **Model tiers:** haiku (refactor, test, report, next_tasks), sonnet (implement, debug, optimize, tech-lead), opus (architect, review).
- **JSON parsing:** read `total_cost_usd`, `is_error`, `session_id`, `num_turns` from the `--output-format json` envelope. Record `cost_usd` to the budget ledger.
- **Timeout:** per-stage wall-clock cap (default 1800s); a hung subprocess is killed → stage fails → task blocks (fail-closed).
- **Non-interactive denial (Risk R1):** headless mode cannot prompt; a tool outside the allowlist must be auto-denied, surfaced as a failed step — NOT a hang. F2a verifies this with a read-only role before any Edit-capable role is granted.

---

## 5. Worktree, gates, PR

### `worktree.py`
- `ensure_clone(slug) -> Path`: if `data/factory/workspaces/<slug>/` is absent, `git clone <project.repo_url>` (ambient `gh`/git creds); else reuse. Returns clone path.
- `prepare(slug, cycle_id, task_id) -> Path`: create a worktree at `data/factory/worktrees/<slug>/<cycle_id>/` on branch `factory/<slug>/<task_id>` (reuse the branch if it already exists — idempotent re-runs). Returns worktree path.
- `cleanup(slug, cycle_id)`: `git worktree remove` + `git worktree prune` (run from the clone root, never from inside the worktree).
- `safe_push(worktree, branch)`: **branch-limited wrapper** — refuses any branch not matching `^factory/<slug>/`. The only push path the runner uses.

### `gates.py` (daemon-verified, fail-closed)
- `run_build(worktree) -> GateResult(ok, output)`: run the project's test/build command (default `python -m pytest -q`, overridable per-project) in the worktree; `ok = exit 0`.
- `run_security(worktree) -> GateResult(ok, findings)`: run `gitleaks detect` on the worktree (+ any present scanners; absent scanner = skipped with a note, never a crash); `ok = no findings`. Findings append to `known_issues.jsonl`.
- Both are objective; the agent never decides them. A malformed/missing tool → fail-closed (gate fails, task blocks).

### `pr.py`
- `open_pr(worktree, slug, task) -> str | None`: `git add -A` + commit (message from task), `worktree.safe_push`, then `gh pr create --head factory/<slug>/<task_id> --base main --title ... --body ...`. Returns the PR url. Reuses the authed `gh` (account `kevensjames`). Idempotent: if a PR for the branch already exists, return its url instead of erroring.

---

## 6. Carry-over fixes (from F1 whole-branch review)

- **Kill-criteria (retry-blocked-nightly):** add `state.requeue_oldest_blocked(slug) -> str | None` (resets the oldest `blocked` task → `pending` under `_CLAIM_LOCK`). In `run_cycle`, after `reclaim_orphans` and only if the project phase is not `blocked_red` and there is no ready `pending` task, requeue one blocked task so it is re-attempted. Each subsequent block bumps `consecutive_failures`; F1's `bump_failure` already flips to `blocked_red` at N=3, which `list_active` already excludes. Add an end-to-end test driving a project to `blocked_red`.
- **Budget pre-emption:** add `roles.estimated_cost(model) -> float` (rough per-call $ by tier). In `run_cycle`, pass that estimate into `budget.would_exceed(slug, est, month)` *before* each executable stage, so the ceiling pre-empts the overrun. Add the F1 boundary test pinning the behavior (queue before the over-budget stage runs).
- **Synthetic-data enforcement:** the runner builds the subprocess env from a **minimal allowlist** (PATH, HOME, claude-auth vars) — it never forwards secret-shaped vars or real-data paths into the agent. Test: assert the runner's constructed env contains no key matching `(KEY|SECRET|TOKEN|PASSWORD|DSN)` beyond the explicit claude-auth set. (Real PHI for F4 lives outside any repo.)
- **Type annotations:** `runner: AgentAdapter` (import from `core.portfolio.actions`) on `pipeline.run_cycle` and `scheduler.run_once`.

---

## 7. Testing strategy

- **Fake `claude` stub:** a small executable script (path via `FACTORY_CLAUDE_BIN`, default `claude`) that prints a canned `--output-format json` envelope (configurable success/failure/cost via env or argv) and optionally touches a file to simulate an edit. Lets tests assert the runner's real arg construction, allowlist string, model flag, cwd, JSON parse, cost extraction, and timeout — with no API, no network.
- **Local repo fixture:** tests create a throwaway git repo with a **local bare remote** so `worktree`, `safe_push`, commit, and (a faked) PR path run for real against local git. `gh pr create` is exercised via a fake `gh` stub (path via `FACTORY_GH_BIN`) in unit tests; the real `gh` only in the manual smoke.
- **Daemon gates:** `run_build` tested with a fixture repo whose pytest passes/fails; `run_security` tested with a fixture containing a planted fake secret (gitleaks present) and one with none.
- **One operator-gated real smoke (F2d):** behind `FACTORY_REAL_SMOKE=1`, run a real `claude -p` cycle on a throwaway repo → real branch + PR. Manual, costs real Claude $; not in the default suite.
- **No W-MOS regressions:** `tests/test_portfolio_*.py` stays green.

---

## 8. Build phases (one spec → phased plan)

- **F2a — roles + runner (fake stub):** `roles.py`, `runner.py` (verb routing, arg/allowlist/model construction, JSON+cost parse, timeout, agent-work `ok`). Tested entirely against the fake `claude` stub. Includes the R1 out-of-allowlist-denial check design (verified for real in F2d).
- **F2b — worktree + gates + PR (local repo):** `worktree.py`, `gates.py`, `pr.py` against a local repo + bare remote + fake `gh`. Branch-limited push enforced + tested. gitleaks gate tested with a planted secret.
- **F2c — carry-overs + opt-in wiring:** kill-criteria retry, budget pre-emption, synthetic-data env, annotations; wire `ClaudeCliRunner` into `cli.py` (`--real`) and `scheduler.start_worker` (opt-in param). Mock stays default.
- **F2d — operator-gated real smoke:** real `claude -p` + real `gh` end-to-end on a throwaway repo; confirm R1 denial behavior live; record real cost. Manual.

This spec covers **F2a–F2d**. F3 (dashboard/arm/observe) and F4 (medical tenant) remain separate specs.

---

## 9. Risks & open items
- **R1 — headless permission denial:** must confirm `--permission-mode acceptEdits` + `--allowedTools` actually denies out-of-allowlist tools non-interactively (no hang). *Mitigation:* F2a designs for it; F2d verifies live with a read-only role first.
- **R2 — cost:** real cycles cost real Claude $; your account has hit credit limits before. *Mitigation:* model-tier routing, per-stage timeout + `--max-turns` cap, budget pre-emption, nightly cadence, and the real runner stays opt-in/dormant until F3.
- **R3 — `gh`/clone auth for private repos:** clone + PR use ambient `gh` (account `kevensjames`). *Mitigation:* if a repo isn't reachable, `ensure_clone` fails the cycle cleanly with a clear error; a dedicated scoped token is a later hardening.
- **R4 — gitleaks-only security:** trivy is absent, so dependency/vuln scanning isn't covered in F2. *Mitigation:* documented; the gate degrades gracefully and is extended when scanners are installed (or when the Security Center is on-branch).
- **Q1:** Default per-project build command — assume `python -m pytest -q`, overridable via `project.json`? (Default: yes.)
- **Q2:** PR base branch — `main`? (Default: yes.)

---

## 10. Definition of done (F2)
- `ClaudeCliRunner` runs all verb classes; agent stages invoke real `claude -p`; build/security gates are daemon-verified and fail-closed.
- Worktree lifecycle (clone → worktree → cleanup) works; pushes are branch-limited to `factory/<slug>/*`.
- A cycle opens a real PR via `gh`; cost recorded from JSON.
- Carry-overs landed: retry-blocked kill-criteria (drives a project to `blocked_red`), budget pre-emption, synthetic-data env, annotations.
- Full deterministic suite green (fake stub + local repo), no W-MOS regressions; one operator-gated real smoke documented + passing.
- Real runner is opt-in; engine still dormant-by-default; nothing merges/deploys autonomously.
