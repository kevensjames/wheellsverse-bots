# KAI Autonomous SWE Agent — Increment Implementation Plan

*Branch base: `fix/kai-swe-sandbox`. Migration head verified `0006_add_kai_api_keys`. Every factual claim below is grounded in a file read or a command run; unverified items are marked **UNVERIFIED**. Produced by a grounded design workflow (explore → design → adversarial critique → synthesize).*

---

## 1. Goal & scope

Turn KAI's existing single-command sandbox (`SandboxCommandRuntime.run_task` — `backend/app/services/swe_runtime/runtime.py:31-38`) into a **bounded, operator-approved autonomous SWE loop** that can plan a fix, execute it as a sequence of sandboxed commands, produce a unified-diff patch, and — only after a *second* human approval — push that patch to a **non-default review branch** using a repo-scoped, least-privilege credential. Ships in three feature-flagged-OFF increments (persistence → brain → push), all behind `KAI_SWE_RUNTIME_ENABLED` (default off — `config.py:20-21`) plus per-capability deny-by-default scopes.

**Explicitly deferred (not this increment):** the OpenHands `software-agent-sdk` adapter (brain ships KAI-native; SDK is ADAPT-not-adopt, gated — §5); any background worker/queue/daemon executor (execution stays synchronous-in-request, matching today's `_do_run` — `admin_swe.py:42-44`); any multi-tenant credential store (single-operator — §2/§6); any merge, PR-automerge, or deploy path (structurally absent from the state machine); async retry/backoff scheduling.

---

## 2. Non-negotiables checklist

| Invariant | How satisfied |
|---|---|
| **Deny-by-default; no silent activation** | Runtime gated by `runtime_enabled()` (default off → `DisabledSandbox` never executes, `sandbox.py:57-64`). Every privileged fn `@audited(scope=…)` → `ScopeDenied`/403 when env unset (`actions.py:96-107`). |
| **Push scope cannot be enabled by a module wildcard** | `is_scope_enabled` treats `parent = norm.split("_")[0]` as wildcard (`actions.py:56-60`), so `KAI_SCOPE_SWE=1` enables any `swe.*`. Push scope is named **`swepush.execute`** (root `SWEPUSH`, disjoint from `SWE`). Regression test asserts `KAI_SCOPE_SWE=1` does NOT enable it. |
| **Human approval before code runs AND before any real-branch write** | Two gates (§6). Gate 1 (`swe.brain.execute`, `destructive=True`) authorizes the sandbox loop → 409s without approval. Gate 2 (`swepush.execute`, `destructive=True`) authorizes the push. |
| **Brain has no exec path except the sandbox** | `DefaultBrain` touches the world only via `runtime.run_task` → `DockerSandbox.run`; no `subprocess`/`os.system`. Enforced by a security test. |
| **Sandbox stays contained** | Reused unchanged: `--network none` + `--cap-drop ALL` + no host mount + ephemeral `rm -f` (`sandbox.py:97-125`), `DEFAULT_DENIED_SUBSTRINGS`, image/repo allowlists. |
| **Never on production** | Hard startup guard refuses to mount SWE routers under a prod marker (`APP_ENV`/`ENV`∈{production,prod}); today non-prod is only *documented*, not enforced. |
| **Push is branch-only, no force, no CI-poisoning, no deploy** | Server-computed review branch `kai/swe/<task_id>`; protected-branch guard; `--force*` never emitted; patches touching `.github/workflows/**`, `.gitlab-ci.yml`, `.git/hooks/**` rejected; token carries no `workflows` permission. |
| **Credentials never leak** | Token resolved+injected strictly inside the push fn via in-memory `GIT_ASKPASS`, never an audited argument, never entering the sandbox; value-level regex scrubbing added to `_redact`. |
| **Every privileged action audited; audit fail-closed for push** | `@audited` records denied/pending/exception/success (`actions.py:96-143`); per-step `record_action`; push aborts if its audit line cannot be persisted. |
| **Bounded autonomy** | Per-mission `Budget` (steps/tokens/wall/USD) checked *before* each act; breach → fail + persist, never silent. |

**Honestly unresolved (residual, §10):** true separation of duties and authenticated approver identity require per-human auth, which does not exist (`require_admin_token` compares one shared `settings.admin_token`). We mitigate, we do not claim to solve.

---

## 3. Architecture

Brain is a **new layer above the existing `AgentRuntime` seam** (`runtime.py:27-29`), reached **only** through the governed `admin_swe` operator path — never the LLM tool loop (the SWE runtime is deliberately not on `ToolRegistry`).

```
 operator (X-Admin-Token)                          [ NON-PROD RUNNER ONLY ]
        │  HTTP (synchronous)
        ▼
 ┌──────────────── admin_swe_tasks router ────────────────┐
 │ require_admin_token  +  prod-guard mount check          │
 │                                                         │
 │ POST /tasks (plan)  POST /tasks/{id}/plan/approve       │
 │   @audited(swe.plan)   @audited(swe.brain.execute,      │
 │      │                          destructive=True)       │
 │      ▼                    ▼                              │
 │ DefaultBrain.plan()   DefaultBrain.execute() ─loop─┐    │
 │  (LLM only, no exec)   Budget.check() BEFORE act    │   │
 │      │                 record_action() per step      │   POST /tasks/{id}/push/approve
 │      ▼                 runtime.run_task(SweTask) ────┘   @audited(swepush.execute,
 │ awaiting_plan_approval  │  DockerSandbox.run                     destructive=True)
 │  + plan JSONB           ▼  --network none --cap-drop ALL     push.apply_and_push()
 │ ┌──────────────────┐  patch → awaiting_push_approval ──────►  fresh clone @ base_ref
 │ │ kai_swe_tasks(PG)│◄─ state persisted across requests        git switch -c kai/swe/<id>
 │ └──────────────────┘                                          git apply (CI-path guard)
 │                                                               git push (scoped token,
 │                                                               no-force, no-workflows) → pushed
 └─────────────────────────────────────────────────────────────────────────────────────┘
        │ every transition
        ▼  governance.record_action → append-only JSONL audit
```

Persistence exists because the three operator actions (create-plan / approve-plan-and-execute / approve-push) are **separate HTTP requests**; the table carries state between them. There is **no** background worker, lease, or sweeper.

---

## 4. Subsystem A — Task persistence

**Reconciliation (cuts from the raw designs):** dropped `user_id` + `profiles.id` FK + the inert RLS block (single shared operator token; the per-tenant credential selection was the root of a critical finding, and RLS was inert without `FORCE RLS`+non-owner role+`SET app.user_id` wiring nothing implements) → **tenant isolation is not claimed; single-operator is the model.** Dropped async-worker columns (`lease_owner`/`lease_expires_at`/`SKIP LOCKED`) — execution is synchronous. Dropped a redundant `approved` boolean (derive from `status`) and a duplicate audit layer. **Kept** `plan`/`patch`/`tokens_used`/`cost_usd` — load-bearing because this increment ships the brain (Gate 1 reviews `plan`, Gate 2 reviews `patch`).

**Migration `backend/alembic/versions/0007_add_kai_swe_tasks.py`** (`down_revision="0006_add_kai_api_keys"`). *If the sibling `fix/kai-code-intelligence` `0007_add_kai_code_chunks` merges first, renumber to `0008` and rechain at merge time — do not guess now.*

Table `kai_swe_tasks` (Postgres, JSONB, `TIMESTAMP(tz) DEFAULT NOW()`, PK `gen_random_uuid()`):

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK `gen_random_uuid()` | row id |
| `task_id` | String(200) NOT NULL, UNIQUE | operator/brain handle **and** idempotency key |
| `goal` | Text NOT NULL | mission objective |
| `source_dir` | Text NOT NULL | must pass `repo_allowed()` |
| `image` | Text NULL | must pass `image_allowed()` |
| `policy` | JSONB NOT NULL | serialized `SandboxPolicy` |
| `status` | String(24) NOT NULL DEFAULT `'awaiting_plan_approval'` | state machine (CHECK) |
| `plan` | JSONB NULL | brain's proposed steps (Gate 1 payload) |
| `patch` | Text NULL | produced unified diff (Gate 2 payload) |
| `patch_sha256` | String(64) NULL | binds Gate-2 approval to the exact patch (blocks post-approval swap) |
| `review_branch` | Text NULL | server-computed `kai/swe/<task_id>`; client can never supply |
| `plan_approved_by`/`plan_approved_at` | Text/TIMESTAMP NULL | Gate-1 attestation |
| `push_approved_by`/`push_approved_at` | Text/TIMESTAMP NULL | Gate-2 attestation |
| `attempts` | Integer NOT NULL DEFAULT 0 | plain execution counter |
| `tokens_used`/`cost_usd` | Integer/Numeric(10,4) DEFAULT 0 | per-mission budget accounting |
| `exit_code`/`stdout`/`stderr`/`timed_out`/`artifacts`/`error` | last `SandboxResult` | Integer/Text/Text/Boolean/JSONB/Text |
| `created_at`/`updated_at` | TIMESTAMP(tz) NOT NULL DEFAULT NOW() | lifecycle |

Constraints: `UNIQUE(task_id)`; `CHECK status IN ('awaiting_plan_approval','plan_approved','executing','awaiting_push_approval','pushing','pushed','rejected','failed','expired')`; `Index(status)`. **No RLS block.** Companion ORM `app/models/swe_task.py` (`SweTaskRecord`, SQLAlchemy-2.0 `Mapped`/`mapped_column`).

**State machine (9 states):**

| State | Meaning | Terminal |
|---|---|---|
| `awaiting_plan_approval` | created; `plan` produced (LLM only, **no** exec). Default. | no |
| `plan_approved` | Gate 1 passed; execution authorized | no |
| `executing` | transient: sandbox loop running in-request | no |
| `awaiting_push_approval` | patch produced, `patch_sha256` set | no |
| `pushing` | transient: push subprocess running | no |
| `pushed` | remote confirmed the ref update | **yes** |
| `rejected` | operator declined at either gate | **yes** |
| `failed` | non-zero exit / budget breach / push error | **yes** |
| `expired` | pending approval older than `KAI_SWE_APPROVAL_TIMEOUT_HOURS`, refused at approve-time (lazy, no daemon) | **yes** |

- **Transitions are conditional UPDATEs:** `UPDATE … SET status=:to WHERE id=:id AND status=:from RETURNING id`; zero rows → 409. Closes double-approve/approve-after-reject races with no lock table.
- **Idempotency (opt-in):** create does `INSERT … ON CONFLICT (task_id) DO NOTHING RETURNING id`; on conflict, explicit `SELECT` returns the existing row. Works only if the caller passes a stable `task_id` (omitting it → random, disables idempotency).
- **Expiry (lazy, fail-closed):** approve endpoints check `age(now, created_at) > KAI_SWE_APPROVAL_TIMEOUT_HOURS` first; if exceeded → `expired` + 409. Silence never becomes yes; no daemon.

---

## 5. Subsystem B — Agent brain

**ADOPT vs ADAPT → ADAPT (thin, pinned, sandboxed adapter later; ship KAI-native brain now). Do NOT adopt the OpenHands loop as a straight dependency.** Grounded: every audit doc classifies OpenHands as **ADAPT/ISOLATED-SERVICE (gated)** (`kai-external-repository-evaluation.md` row 49; overlap matrix; roadmap rank 3, Net −2). KAI exposes no code-exec to the LLM "by deliberate design"; adopting the SDK's own loop imports an unbounded exec surface. **Two grounded reasons the SDK adapter is not this increment:** (1) **UNVERIFIED loop contract** — docs name the SDK tools (`TerminalTool`/`FileEditorTool`/`TaskTrackerTool`), MIT license, ephemeral-sandbox model, but not its action/observation event schema; closing that requires reading `software-agent-sdk` source (out of scope). (2) **Sequencing** — even as ADAPT it is gated behind roadmap rank-0 (close the ungoverned LLM-tool-loop gap) and rank-1 (semantic code-search index).

MVP = **KAI-native `DefaultBrain`** behind an SDK-agnostic `AgentBrain` Protocol; `OpenHandsBrainAdapter` is a documented future drop-in behind the same Protocol (`KAI_SWE_BRAIN=native|openhands`, default `native`). **License scan is a hard gate before any SDK vendoring** (MIT SDK only; the `enterprise/` dir is separately licensed — never vendor it).

**Interface `backend/app/services/swe_runtime/brain.py`** — the brain *consumes* the existing `AgentRuntime`, does not implement it:

```python
@dataclass(slots=True)
class Mission:
    task_id: str
    source_dir: str          # must pass repo_allowed()
    goal: str
    image: str | None = None # must pass image_allowed()
    budget: Budget = field(default_factory=Budget.default)

@dataclass(slots=True)
class Step:
    n: int; command: str; rationale: str

@dataclass(slots=True)
class BrainResult:
    task_id: str
    status: str              # EXACTLY 'awaiting_push_approval' | 'failed'
    steps: list[Step]
    last: SandboxResult | None
    patch: str | None
    error: str | None = None

@runtime_checkable
class AgentBrain(Protocol):
    def plan(self, mission: Mission) -> list[Step]: ...        # LLM only, NO sandbox exec
    def execute(self, mission: Mission, plan: list[Step],
                runtime: AgentRuntime) -> BrainResult: ...     # the bounded act/observe loop
```

`BrainResult.status` is constrained to the persisted CHECK states — a budget breach maps to `failed`, no unmapped strings leak. **plan/execute split is the approval resolution:** `plan()` runs at create time with NO sandbox execution → `awaiting_plan_approval`; `execute()` only runs after Gate 1, and its operator entrypoint is `@audited(destructive=True)` so the loop cannot run without approval.

**Bounded loop (`execute`):** `budget.start()` → for each step (and bounded re-plans): `budget.check()` **before** acting (raises `BudgetBreach`) → local policy-validate the command → per-step `record_action(scope="swe.brain.step", …)` → `result = runtime.run_task(SweTask(...))` (**sole** side effect) → charge tokens/cost, tick step → observe → on done collect patch from `result.artifacts`. Two hard rules: no shell/`subprocess`; never writes a real branch (emits a diff and stops).

**Hard limits `backend/app/services/swe_runtime/budget.py`** (no aggregate cross-task budget exists today — the `SandboxPolicy` caps bound a single container only):

| Bound | Default | Enforced |
|---|---|---|
| max steps | 8 | `tick_step()` before each act |
| max tokens | 200_000 | `charge_tokens()` per LLM turn |
| max wall | 900 s | mission-level, distinct from per-container `timeout_seconds` |
| **max cost (per-mission)** | $1.00 | per-mission accumulator, checked before each turn; `SpendTracker.over_daily_cap` ($2.00) is an *additional outer* ceiling, never the mission bound |

`Budget.check()` raises `BudgetBreach(reason, spent)` **before** each act. On breach: loop stops, persist `status='failed'`, `error=<reason>`, bump `attempts`; `@audited` records the breach path.

---

## 6. Subsystem C — Approve-before-push

**Endpoints — router `app/routers/admin_swe_tasks.py`, `dependencies=[Depends(require_admin_token)]`:**

| Method + Path | Purpose | `@audited` scope | Destructive | Transition |
|---|---|---|---|---|
| `POST /admin/swe/tasks` | create + run `plan()` (LLM only) | `swe.plan` | no | ∅ → `awaiting_plan_approval` |
| `GET /admin/swe/tasks/{id}` | status, approvers, attempts | — | no | any |
| `GET …/{id}/plan` | proposed steps | — | no | ≥`awaiting_plan_approval` |
| `GET …/{id}/patch` | diff + last logs | — | no | ≥`awaiting_push_approval` |
| `POST …/{id}/plan/approve` | **Gate 1** → run `execute()` | `swe.brain.execute` | **yes** | `awaiting_plan_approval` → `plan_approved`→`executing`→`awaiting_push_approval`/`failed` |
| `POST …/{id}/push/approve` | **Gate 2** → apply+push | `swepush.execute` | **yes** | `awaiting_push_approval` → `pushing` → `pushed`/`failed` |
| `POST …/{id}/reject` | decline at either gate | `swe.plan` | no | `awaiting_*_approval` → `rejected` |

Exception→HTTP mapping copied from `admin_swe.py:71-80`: `ScopeDenied`→403, `PendingApproval`→409, `PolicyDenied`→400, illegal transition→409, unknown→404, else→503; runtime-disabled→409. Gate handlers wrap `@audited` inner fns threaded with `approved=body.approved`.

**Scope names:** `swe.plan`, `swe.brain.step`, `swe.brain.execute` share root `SWE`; the **destructive push uses root `SWEPUSH`** so `KAI_SCOPE_SWE=1` cannot enable it. Docs must warn: never set the `KAI_SCOPE_SWE` wildcard on the runner — enumerate `KAI_SCOPE_SWE_PLAN=1` etc.

**Two human gates:** Gate 1 runs *before any sandbox execution*; the `execute()` loop is unreachable until `plan_approved`. Gate 2 runs *before any `git push`*; re-checks `patch_sha256` against the stored patch (a post-approval swap invalidates the approval).

**Approver identity — honest bounds:** `require_admin_token` compares one shared token; it authorizes but does not identify a human (UNVERIFIED that per-human tokens exist). Each gate **requires** a non-empty `approver` (400 if missing, so no approval is anonymous), persisted + threaded as `actor=` into `@audited`. This is a **recorded attestation, not authenticated identity, and not separation of duties.** Partial out-of-band control: destructive scopes must be set in the runner env by someone with shell access, distinct from an API caller.

**Git push — branch-only, single scoped credential** (`app/services/swe_runtime/push.py`). Push happens on the host, outside the sandbox, against a **fresh clone at base_ref** (never a live checkout): `clone(repo, base_ref) → git switch -c kai/swe/<task_id> → git apply <patch> → git commit → git push <scoped-remote> kai/swe/<task_id>`.

- **Non-default branch only.** `review_branch` computed server-side; client cannot supply. Guard → `PolicyDenied`/400 if the target resolves to remote `HEAD` or any name in `KAI_SWE_PROTECTED_BRANCHES` (default `main,istanbul,master`). `--force`/`--force-with-lease` never emitted.
- **CI-poisoning block.** Before `git apply`, reject any patch touching `.github/workflows/**`, `.gitlab-ci.yml`, `.gitlab/**`, `.git/hooks/**`. Independently, the push token is minted **without** `workflows` permission (`contents:write` only). **UNVERIFIED:** exact GitHub token-minting API/scope names — confirm against GitHub docs before build.
- **Single least-privilege credential, no ambient fallback.** `resolve_push_credential(repo)` returns a repo-scoped token from a secret env (`KAI_SWE_PUSH_TOKEN` or an App-token mint). No credential → `PolicyDenied`/403; **never** falls back to a process-wide `GITHUB_TOKEN`/`credential.helper`/`~/.git-credentials` (push runs with empty `GIT_CONFIG_GLOBAL`). Token injected only into the push subprocess via in-memory `GIT_ASKPASS`, never on disk, never in the sandbox, never an audited argument.

**Audit trail — two existing layers (no third):** (1) `@audited` on `_do_execute`/`_do_push`/`plan`; (2) per-command `record_action(scope="swe.brain.step")`. For `_do_push` the audit write is **fail-closed** — push aborts if its pre-action audit line cannot be persisted (overriding `record_action`'s never-raise for this one path). Add value-level regex scrubbing (`Bearer\s+\S+`, `gh[ps]_\w+`, `x-access-token:\S+`) to `_redact` (today matches dict keys only).

**Copy-in symlink hardening:** `DockerSandbox.run` copies source in with `docker cp {source_dir}/. {cid}:/work` which **follows symlinks** (only copy-out is hardened). Add a pre-copy check in `run` that rejects/strips any symlink under `source_dir` before copy-in, so an allowlisted repo containing `secret → /etc/passwd` cannot materialize a host file into the sandbox.

---

## 7. Build increments (ordered, each independently verifiable, all flagged OFF)

> Global gate: `KAI_SWE_RUNTIME_ENABLED` (default off) **plus** a new prod-refusal startup guard. Routers not mounted under a prod marker; brain never registered on `ToolRegistry`.

**Inc 0 — Prod guard + scope hygiene (prerequisite).** Startup guard refuses to mount SWE routers if `APP_ENV`/`ENV`∈{production,prod}. Register scopes in the governance docstring. **Verify:** with `APP_ENV=production` the app starts but SWE routes 404/disabled; `KAI_SCOPE_SWE=1` enables `swe.plan` but **NOT** `swepush.execute`.

**Inc 1 — Persistence (lands first).** `0007_add_kai_swe_tasks.py` + `app/models/swe_task.py` + `app/services/swe_runtime/task_store.py` (create-with-ON-CONFLICT, conditional-UPDATE transition helpers). **Verify:** `alembic upgrade head`→`downgrade` round-trips; duplicate `task_id` returns the existing row; wrong-`from` transition returns zero rows (→409); CHECK rejects unknown status.

**Inc 2 — Brain + Gate 1 (needs Inc 1).** `brain.py` (`AgentBrain`, `Mission`, `Step`, `BrainResult`, `DefaultBrain`), `budget.py`; `openhands_adapter.py` **absent/deferred** (documented, not stubbed). `admin_swe_tasks.py`: `POST /tasks`, reads, `POST /tasks/{id}/plan/approve` (`_do_execute`, `destructive=True`), `reject`. **Verify:** fake runtime returns scripted `SandboxResult`; loop stops at `max_steps`; budget breach persists `failed`; `plan/approve` without `approved=True` → 409 and **no** `run_task` called; `DefaultBrain` has no `subprocess`/`os.system` (security test).

**Inc 3 — Approve-before-push + Gate 2 (needs Inc 2).** `push.py` (fresh-clone → apply → scoped push, protected-branch guard, CI-path guard, `resolve_push_credential`); `POST /tasks/{id}/push/approve` (`_do_push`, `destructive=True`, `swepush.execute`); `patch_sha256` re-check; copy-in symlink hardening; `_redact` value-regex; fail-closed push audit. **Verify (deterministic):** push to protected → `PolicyDenied`; patch touching `.github/workflows/x.yml` → `PolicyDenied`; push/approve without scope → 403, without approval → 409; `patch_sha256` mismatch → rejected; no ambient git credential read; `_redact("Authorization: Bearer ghs_abc")` scrubbed. **Verify (integration):** real ephemeral local bare repo — push creates the review branch, never `main`, no force.

---

## 8. Open decisions for the human — RESOLVED (operator locked all four to the recommended default, 2026-07-21)

1. **OpenHands adapter — LOCKED: defer entirely.** Ship `DefaultBrain` behind an SDK-agnostic `AgentBrain` Protocol. Add `OpenHandsBrainAdapter` only after (a) the two roadmap prerequisites land and (b) an SPDX + transitive-dependency license scan of the MIT `software-agent-sdk` (excluding `enterprise/`) passes.
2. **Autonomy bound — LOCKED: 8 steps / $1.00 / 900 s per mission**, with the daily `SpendTracker` cap ($2.00) as the outer ceiling.
3. **Approval granularity — LOCKED: loop-level Gate 1.** Gate 1 authorizes the bounded budgeted loop; per-command `record_action` gives after-the-fact granularity; Gate 2 guards the only host-affecting op (the push).
4. **Credential model — LOCKED: single repo-scoped token now.** One fine-grained `contents:write`, no-`workflows`, short-TTL token resolved by repo; no tenant isolation and no true two-person approval claimed until per-human auth exists (residual risk §10.1).

---

## 9. Test strategy

Mirrors the existing sandbox (deterministic unit + real-container integration).

**Deterministic unit (no Docker, no network):** persistence (migration round-trip, ON-CONFLICT idempotency, conditional-transition zero-row, CHECK); governance (`KAI_SCOPE_SWE=1` does not enable `swepush.execute`; `destructive` fn 409s without `approved`; scope-off 403s); brain (fake `AgentRuntime` → each of steps/tokens/wall/cost trips a `BudgetBreach`→`failed`; `plan()` never calls `run_task`; no `subprocess` import in `DefaultBrain`); push guards (protected-branch, CI-path, `patch_sha256` mismatch, missing-credential, scope/approval → correct typed error; `_redact` value-regex); prod guard (`APP_ENV=production` → SWE routes not mounted).

**Real-container / integration (Docker, `runtime_enabled()` on a non-prod runner):** end-to-end on a throwaway local bare git repo — create → approve plan → `DefaultBrain` runs 1-2 real sandboxed commands → diff → approve push → assert review branch `kai/swe/<id>` exists, `main` untouched, no force, `.github/workflows` unchanged. Copy-in symlink rejection test. Confirm `--network none` still blocks egress and `DEFAULT_DENIED_SUBSTRINGS` still rejects `curl` inside the loop.

---

## 10. Residual risks (dangerous even after this increment)

1. **No separation of duties / no authenticated approver (mitigated, not solved).** The same shared admin token can submit *and* approve; `approved=True` is an in-band boolean; `approver` is a self-declared string. A leaked admin token can self-approve. Real fix = per-human auth + distinct approver identity (Decision 4). Mitigation: destructive scopes enabled out-of-band in the runner env; Gate 2 binds to `patch_sha256`; everything audited.
2. **Prompt-injection steering the plan.** Gate 1 authorizes a bounded loop, not each command; a malicious `goal`/injected repo content can steer the brain to emit a hostile patch. Containment: patch cannot reach a real branch without Gate 2, CI paths blocked, sandbox network-isolated — but a plausible-looking malicious diff could still be approved by a rushed operator.
3. **Single push token blast radius.** One repo-scoped `contents:write` token, if exfiltrated from the host, can write any non-protected branch in that repo. Short TTL + no-`workflows` limit but do not eliminate.
4. **Synchronous long-running requests.** The `execute` loop (≤900 s) runs inside one HTTP request. An in-process error is now caught and moves the row `executing → failed` (Inc 2 crash-guard), but a HARD process kill (SIGKILL/OOM) mid-run can still strand it in transient `executing` — there is no auto-reclaim (no sweeper/lease by design). Recovery: `POST /tasks/{id}/reject` un-sticks a stranded `executing` row. `pushing` (Inc 3) has the same shape.
5. **Audit is a local JSONL file.** Even fail-closed for push, the log has no cryptographic tamper-evidence or off-host durability; a host compromise can rewrite history.
6. **UNVERIFIED external facts the build must close:** the GitHub fine-grained-PAT / App-token scope names for a no-`workflows` `contents:write` credential; the OpenHands SDK action/observation loop contract and transitive-dependency licenses (both required before any SDK adapter work).
7. **`SpendTracker` semantics reused but not re-verified** for the per-mission interaction; the per-mission accumulator is the real bound, the daily cap only an outer guard.
