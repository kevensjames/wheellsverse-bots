# Dark KAI — Implementation Plan

**Repo:** `/Users/jhonwheeler/wheellsverse-kai-audit` (backend at `backend/`)
**Written from:** branch `feat/kai-swe-agent`, HEAD `4850b0d`
**Date:** 2026-07-22

## 0. Provenance rules used in this document

Every component below is tagged with where it actually lives. Verified with:

```
git diff --name-only origin/istanbul...HEAD                        # PR #42 (+#41 stacked)
git diff --name-only origin/istanbul...fix/kai-governed-tool-loop  # PR #39
git diff --name-only origin/istanbul...fix/kai-code-intelligence   # PR #40
git diff --name-only origin/istanbul...fix/kai-swe-sandbox         # PR #41
```

| Tag | Meaning |
|---|---|
| **[istanbul]** | Already merged. Available today. |
| **[#39]** | Only on `fix/kai-governed-tool-loop`. Open PR. |
| **[#40]** | Only on `fix/kai-code-intelligence`. Open PR. |
| **[#41]** | Only on `fix/kai-swe-sandbox` (also present on `feat/kai-swe-agent`). Open PR. |
| **[#42]** | Only on `feat/kai-swe-agent`. Open PR. |

Nothing in #39/#40/#41/#42 is merged into `istanbul` (`git merge-base --is-ancestor <tip> origin/istanbul` → false for all four).

**Files on branch `fix/kai-code-intelligence` are NOT in this checkout.** `backend/app/services/code_intel/` here contains only stale `__pycache__/*.pyc` — no `.py` source. Any tool or reader that greps this working tree will falsely conclude code intelligence "exists locally". It does not; it exists on the #40 branch.

---

## 1. Reuse Ledger (mandatory — read before writing any code)

Directive §1.6: never duplicate money movement, auth, audit logging, or provider routing. This table is the enforcement of that rule. **Only rows marked BUILD-NEW may produce new modules.**

### 1a. Required properties

| # | Dark KAI requirement | Existing component that satisfies it | file:line | Where | Verdict |
|---|---|---|---|---|---|
| P1 | **Disabled by default** | `is_scope_enabled()` — deny-by-default env scope gate, no scope env set ⇒ `ScopeDenied` | `backend/app/services/governance/actions.py:46-63`, raised at `:97-108` | istanbul | **REUSE** |
| P1b | Disabled by default, *route-level* | `swe_admin_enabled()` allow-lists non-prod `APP_ENV`, `ENV=production` vetoes; routes not even mounted | `backend/app/services/swe_runtime/config.py:32-40`, mount at `backend/app/main.py:193-200` | #41 | **EXTEND** (same 9-line function, new flag `KAI_DARKKAI_ENABLED`) |
| P1c | Disabled by default, *execution-level* | `runtime_enabled()` + `DisabledSandbox` — the default backend refuses to execute anything | `config.py:18-19`, `sandbox.py:57-64` | #41 | **REUSE** |
| P2 | **All tool execution through a broker** | Governed `ToolRegistry.execute` — scope gate, default-deny `ctx.allow_writes` for `writes=True` tools, `record_action` on every path incl. block and error | `backend/app/services/tools/registry.py:22-30` (`_tool_writes`/`_tool_scope`), `:79-106` (`_audit`), `:108-120+` (`execute`) | **#39** | **REUSE — blocking dependency** |
| P2b | The single choke point the broker must own | `tool_result = tool_registry.execute(tc.name, tc.arguments, tool_context)` | `backend/app/services/router/router.py:374` | istanbul | **REUSE** |
| P3 | **Risky actions approval-gated** | `@audited(scope=..., destructive=True)` → `PendingApproval` unless `approved=True` | `actions.py:71-81` (decorator), `:109-120` (gate) | istanbul | **REUSE** |
| P3b | Approval bound to a *proven* identity (not a body string) | `require_approver` — SHA-256 of `X-Approver-Token` matched against `admin_users.password_hash`, returns the row's email as the audit actor | `backend/app/dependencies/approver.py:39-53` | #42 | **REUSE** |
| P3c | Approval expiry + TOCTOU re-validation | `_is_expired` (lazy, `KAI_SWE_APPROVAL_TIMEOUT_HOURS`, default 24h) `:75-85`; re-validated at approve time `:244-252`, `:313-319`; patch bound to reviewed `patch_sha256` `:279-280` | `backend/app/routers/admin_swe_tasks.py` | #42 | **REUSE** |
| P3d | Two-person separation of duties | `two_person_required()` / `KAI_SWE_REQUIRE_TWO_PERSON`, enforced at `admin_swe_tasks.py:311` | `approver.py:34-36` | #42 | **REUSE** |
| P4 | **Agents cannot run raw shell** | The only execution primitive is the container sandbox; command substrings denied before exec (`curl`, `wget`, `ssh`, `docker`, `sudo`, `~/.aws`, `~/.ssh`, `id_rsa`, `credentials`, …) | `config.py:50-58` (`DEFAULT_DENIED_SUBSTRINGS`), `backend/app/services/swe_runtime/policy.py` (24 lines, validation), re-validated inside `sandbox.py` | #41 | **REUSE** |
| P4b | Agent brain never calls `subprocess` itself | `SweBrain.execute` composes the approved plan into ONE sandbox run via `AgentRuntime`; `plan()` is explicitly "LLM/heuristic only, NO exec" | `backend/app/services/swe_runtime/brain.py:73-74`, `:92-140` | #42 | **REUSE** |
| P5 | **Sandbox network deny-by-default** | `build_create_args()` — `--network none`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--pull never`, memory/pids/cpu caps, no host bind mount (source copied in via `docker cp`), container force-removed | `backend/app/services/swe_runtime/sandbox.py:78-89`, header contract `:1-12` | #41 | **REUSE** |
| P6 | **No prod credentials in experiments** | (a) `--network none` makes an exfil call inert; (b) push runs with empty `HOME` + cleared `GIT_CONFIG_GLOBAL/SYSTEM` + `GIT_TERMINAL_PROMPT=0` so no ambient credential is ever used, and refuses to fall back | `sandbox.py:78-89`; `backend/app/services/swe_runtime/push.py:142-160`, refusal at `:204-206` | #41/#42 | **REUSE** |
| P6b | Credentialed tools excluded from the experiment registry | `build_default_registry()` registers `twenty_crm`/`dwolla`/`composio`/MCP/`video_gen` conditionally on env keys — but unconditionally for *all* callers | `backend/app/services/tools/__init__.py:46-160+` | istanbul | **EXTEND** (a filtered registry for Dark KAI — see M2; ~20 lines, no new tool code) |
| P7 | **Every claim carries provenance + confidence** | `grounding.verify_statement` — retrieve → LLM fact-check against ONLY the retrieved passages → blended confidence. Verdicts `supported/partial/unsupported/contradicted/no_sources/unknown`, confidence `high/medium/low` | `backend/app/services/grounding.py:1-27` (contract), `:25-26` (`VERDICTS`, `_CONF`), `:30-41` (system prompt) | istanbul | **REUSE** |
| P7b | Claim verification exposed as a tool the loop can call | `verify_claim` — returns verdict + confidence + supporting passages | `backend/app/services/tools/verify_claim.py:17-60` | istanbul | **REUSE** |
| P7c | Code-level provenance (path + symbol + line range + relevance) | `code_search` returns `{path, symbol, lang, lines, relevance, excerpt}` and instructs the model to cite `[code: <path>:<start>-<end>]`; retrieved code is data, never instructions | `backend/app/services/tools/code_search.py:15-34`, `:50-58` | **#40** | **REUSE — blocking dependency** |
| P7d | Finding record that *carries* provenance+confidence | `supreme.Finding` dataclass + severity + `save_proposal` | `backend/app/services/supreme/scanner.py:61`, `:374` | istanbul | **EXTEND** (add `provenance`/`confidence`/`verified_by` fields, or a Dark-KAI-local record; do NOT build a parallel scanner) |
| P8 | **High/Critical findings independently verified** | Two independent second-pass mechanisms already wired into a chat request: `self_correct` (critique→revise loop, `run_correction_loop`) and `verify` (real grounded verification, `grounding.verify_statement`, returns a `verification` block) | `backend/app/routers/admin_chat.py:144-152` (request fields), `:255-294` (self-correction), `:296-325` (verification) | istanbul | **EXTEND** (policy: severity ≥ High ⇒ `verify=True` required and a second-adapter pass; the machinery exists) |
| P9 | **Code changes branch-only** | `apply_and_push` — fresh clone, `kai/swe/<task_id>` review branch only, protected-branch refusal, `--force` never emitted, credential scoped, CI-path block, fsync'd fail-closed audit | `push.py:183-246`; branch name `review_branch_for` `:64`; protected refusal `:188-189`; contract `:4-22` | #42 | **REUSE** |
| P9b | "…and PR only" | **Not present.** `grep -rn "pulls\|create_pull\|gh pr" backend/app/services/swe_runtime/` → 0 hits. `apply_and_push` returns `{review_branch, remote, commit}` (`push.py:246`); a human opens the PR. | — | — | **BUILD-NEW (optional, defer)** — the branch push already satisfies "no direct-to-main"; PR automation is convenience, not containment |
| P10 | **No agent deploys to prod** | (a) SWE routes do not mount on a prod runner (`main.py:193-200`); (b) no deploy tool exists in the registry — the deploy surface is launchd + `deploy/start_nai.sh`, outside the app process | `config.py:32-40`, `main.py:193-200`; deploy topology in `deploy/launchd/com.wheellsverse.kai.plist`, `deploy/start_nai.sh` | #41 / istanbul | **REUSE** |
| P11 | **Kill switches** | Env flags read *per tick / per call*, not cached at import: `runtime_enabled()` `config.py:18-19`, `is_scope_enabled()` `actions.py:46-63`, scheduler re-checks each cycle (`self_heal_scheduler.py:45-58` pattern). Flip the env + restart-or-next-tick ⇒ stop. | as cited | istanbul/#41 | **REUSE** |
| P12 | **Cost ceilings** | `Budget` — 8 steps / 200k tokens / 900s / $1.00, `check()` called BEFORE each act, breach raises `BudgetBreach` and persists the task as `failed` (never silent) | `backend/app/services/swe_runtime/budget.py:30-68`; enforced `brain.py:94-119` | #42 | **REUSE** |
| P12b | Outer daily/monthly LLM ceiling | `SpendTracker` — `NAI_MAX_DAILY_SPEND_USD` $2.00 / `NAI_MAX_MONTHLY_SPEND_USD` $60.00; `over_daily_cap` consulted by the router | `backend/app/services/router/spend_tracker.py:18-19`; `router.py:106` | istanbul | **REUSE** (known limitation: soft — routes to local model, never refuses; evaluated once per turn) |
| P13 | **Immutable audit log** | `record_action` appends redacted JSONL to `KAI_AUDIT_LOG_PATH`. **It is append-only, not tamper-evident** — `grep -rn "prev_hash\|hmac\|chain" backend/app/services/governance/` → 0 hits — and the write is **fail-soft**: a failed write logs a warning and returns (`audit_log.py:79-84`). The only fail-closed writer in the repo is the SWE push (`push.py:161-179`, fsync-or-abort). | `backend/app/services/governance/audit_log.py:21-84`, redaction `:86-133` | istanbul (+ value-scrub hardening in #42) | **BUILD-NEW** — hash chain + a fail-closed mode. Extend `record_action` in place; do **not** create a second log. |

### 1b. Required modes

| Mode | Existing component | file:line | Where | Verdict |
|---|---|---|---|---|
| **Analysis** (read-only) | #39's default-deny `ctx.allow_writes` (read tools have `writes=False` and run freely; every write tool is blocked without operator write-authorization) + #40 `code_search` (`writes` defaults False, tenant-scoped `WHERE user_id = ctx.user_id`) + `grounding`/`verify_claim` | `registry.py:22-25`, `:108-120+` [#39]; `code_search.py:1-7`, `:41-47` [#40]; `grounding.py`, `verify_claim.py` [istanbul] | #39+#40 | **REUSE** — zero new code |
| **Lab** (disposable sandbox) | The #41 sandbox in full: ephemeral container, `--network none`, cap-drop, artifacts copied out with byte/file caps (`max_artifact_bytes` 2 MB, `max_artifact_files` 500) | `sandbox.py:78-89`, `config.py:61-83` | #41 | **REUSE** — zero new code |
| **Builder** (branch + PR only) | The #42 pipeline: task state machine (9 states, conditional transitions), plan gate → execute gate → push gate, `push.apply_and_push` | `backend/app/models/swe_task.py:26-30`; `admin_swe_tasks.py:107-350`; `push.py:183-246` | #42 | **REUSE** (see P9b for the PR-open gap) |
| **Sentinel** (monitoring) | `supreme` — 7 read-only scanners (process, port, log-error, API reachability, env completeness, disk, git state), `scan_once` → `save_proposal` → Telegram on ≥medium, in-process scheduler default OFF | `supreme/scanner.py:103-352`, `:374`, `:451-468`; scheduler `supreme/scheduler.py:30,45-57`; start `main.py:47-51` | istanbul | **REUSE** — add Dark-KAI scanners as new `Scanner` subclasses, not a new subsystem |
| **Simulation** | Nothing in the repo simulates adversarial scenarios. | — | — | **BUILD-NEW — defer.** Lab already runs arbitrary code in isolation; "Simulation" as a distinct mode is speculative until a concrete scenario exists. Do not build it in the first pass. |

---

## 2. What the directive already describes as "to build" but is ALREADY SHIPPED

Call these out to the operator before any work starts. **13 of the 18 ledger rows are REUSE.** Specifically:

1. **The broker exists.** PR #39 already turns `ToolRegistry.execute` into a governed broker with scope gate, default-deny writes, and audit-on-every-path (`registry.py:79-120+`). Dark KAI must call it, not replace it.
2. **The sandbox exists and is stronger than the directive asks.** #41 gives network-none *plus* cap-drop-ALL, no-new-privileges, `--pull never`, no host bind mount, pids/memory/cpu caps, wall-clock kill, and a command-substring denylist (`sandbox.py:78-89`, `config.py:50-58`).
3. **Approval gating with a proven identity exists.** `require_approver` (`approver.py:39-53`) is the only place in the entire repo where an approval names an identity the caller had to prove — better than the shared `X-Admin-Token` used everywhere else.
4. **Branch-only push with no ambient credential exists.** `push.py:142-160`, `:183-246`. Nothing to design.
5. **Cost ceilings exist at two levels.** Per-mission `Budget` (#42, `budget.py:30-68`) inside the daily `SpendTracker` cap (istanbul, `spend_tracker.py:18-19`).
6. **Provenance + confidence exist.** `grounding.verify_statement` + `verify_claim` (istanbul) + `code_search` citations (#40). No new retrieval or scoring code.
7. **Independent verification of findings exists as a mechanism.** `admin_chat.py:255-325` already runs a critique-revise loop and a real grounded verification pass. Dark KAI supplies the *policy* ("High/Critical ⇒ must run it"), not the machinery.
8. **Prod-veto and kill switches exist.** `swe_admin_enabled()` (`config.py:32-40`) + per-call env reads.
9. **Sentinel exists.** `supreme` is a complete read-only scanner framework with severity, persistence, and alerting.

**The genuinely new surface is small:** a tamper-evident audit chain, a Dark-KAI mode façade + filtered registry, a finding record that carries provenance/confidence/verification state, and (deferred) Simulation.

---

## 3. Milestones

Dependency reality: **Dark KAI cannot be safely built before #39 merges.** Without #39, `registry.py:58-84` on istanbul executes model-chosen tool calls with no scope check, no approval check, and no audit record — there is no broker to route through. Building Dark KAI on top of that would mean building a second broker, which the directive forbids.

### M0 — Unblock: land the open PRs (no Dark KAI code)

- **Scope:** Merge #39, then #40, then #41, then #42 into `istanbul`.
- **Files:** none new. Merge-only.
- **Dependencies:** #39 → #41 → #42 ordering is natural (#42 is stacked on #41 on this branch). #40 is independent of the SWE stack.
- **Risk — migration head collision (high, concrete):** three branches each define a revision with `down_revision = "0006_add_kai_api_keys"`:
  - `0007_add_kai_swe_tasks` (#42, `backend/alembic/versions/0007_add_kai_swe_tasks.py:24-25`)
  - `0007_add_kai_code_chunks` (#40, `0007_add_kai_code_chunks.py:19-20`)
  - `0007_sol_v1_data_model` (`origin/feat/sol-v1`, `:17-18`, which continues 0008…0020)

  Revision *ids* differ so alembic will not hard-collide on merge, but merging any two yields **multiple heads** and `alembic upgrade head` fails. #39 and #41 add no migrations.
- **Verify:** after each merge, on a scratch DB: `cd backend && alembic heads` returns **exactly one** line, and `alembic upgrade head` exits 0. Then `pytest tests/test_tool_governance.py tests/services/code_intel tests/services/swe_runtime -q` is green (per-PR suites: #39 `tests/test_tool_governance.py`; #40 5 files incl. `test_tenant_isolation.py`, `test_walker_jail.py`, `test_secrets_redaction.py`; #41/#42 74 tests across `tests/services/swe_runtime/`).

### M1 — Tamper-evident, fail-closed audit log (**the only true BUILD-NEW in the containment path**)

- **Scope:** Add a `prev_hash`/`hash` chain to `record_action`, and a fail-closed mode for high-consequence records. Today `audit_log.py:79-84` swallows a write failure — a dropped record is invisible. The directive's "immutable audit log" is currently false.
- **Files:** `backend/app/services/governance/audit_log.py` (extend `record_action`, `:21-84`) — **one file**. Reuse the fsync-or-raise pattern already proven at `backend/app/services/swe_runtime/push.py:161-179` rather than inventing one. Do not add a second log path; `KAI_AUDIT_LOG_PATH` stays the single sink.
- **Dependencies:** none — this is on merged `istanbul` and can proceed in parallel with M0. Land it *before* Dark KAI writes anything.
- **Risks:** (a) `record_action` is called from `@audited` on every governed action and (post-#39) from every tool call — a regression here breaks the whole governance surface; keep the default path fail-soft and make fail-closed opt-in per call, exactly as `push.py` does. (b) Chaining requires reading the last line on each append; on a large log that is O(file) unless the last hash is cached in memory — cache it, and re-read only on process start. (c) A single-writer assumption: the daemon is `--workers 1` (`deploy/start_nai.sh`), which the admin throttle and rate limiter already depend on. Note the dependency; do not silently rely on it.
- **Verify:** a new test asserting (1) each record's `prev_hash` equals the previous record's `hash`; (2) mutating any middle line makes verification fail at that line; (3) a fail-closed write to an unwritable path **raises** rather than warns. Run `pytest tests/services/test_audit_value_redaction.py tests/test_governance.py tests/test_audit.py -q` to prove no regression (19 + 7 existing tests).

### M2 — Dark KAI mode façade + experiment registry (EXTEND only)

- **Scope:** One module that (a) exposes `darkkai_enabled()` and `darkkai_admin_enabled()` copying `swe_runtime/config.py:18-19` and `:32-40` verbatim in shape, (b) builds a **filtered** tool registry per mode by wrapping `build_default_registry()` and dropping credentialed/operator-scoped tools (`twenty_crm`, `dwolla`, `composio`, `notion`, MCP, `video_gen`, `site_builder`, `browser`) — satisfying P6b. Modes map to existing primitives with no new execution code:
  - Analysis → filtered registry + `allow_writes=False` (#39 default)
  - Lab → `swe_runtime.runtime.AgentRuntime` + `sandbox`
  - Builder → `admin_swe_tasks` task flow + `push.apply_and_push`
  - Sentinel → new `Scanner` subclasses registered into `supreme.scan_once`
- **Files:** `backend/app/services/dark_kai/config.py` (mode flags + registry filter), `backend/app/routers/admin_dark_kai.py` (thin router, `dependencies=[Depends(require_admin_token)]` at router level like all 23 existing admin routers), conditional mount in `backend/app/main.py` mirroring `:193-200`.
- **Dependencies:** **#39 (broker), #40 (code_search for Analysis), #41 (sandbox for Lab), #42 (task flow + approver for Builder)** — all four. Sentinel-only mode could ship on istanbul alone if the others slip.
- **Risks:** (a) **Scope-wildcard bypass** — `is_scope_enabled` widens on the first segment (`actions.py:60-62`), so `KAI_SCOPE_DARKKAI=1` would enable every `darkkai.*` scope *including destructive ones*. Follow the precedent the SWE work set: put the destructive scope under a **disjoint root** (`admin_swe_tasks.py:273` uses `swepush.execute` precisely so `KAI_SCOPE_SWE` cannot reach it). Name the Dark KAI write scope e.g. `darkbuild.execute`, never `darkkai.build`. (b) Registry filtering by name is brittle if a tool is renamed — prefer filtering on the `#39` `writes`/`scope` class attributes (`registry.py:22-30`) with a small explicit denylist on top.
- **Verify:** a test asserting (1) with no env set, `darkkai_enabled()` is False and the router is not mounted; (2) `APP_ENV=production` (and `ENV=production`) refuse the mount even with the flag on — mirror `tests/services/swe_runtime/test_swe_admin_gating.py` (4 tests); (3) the Analysis registry contains `code_search`/`verify_claim`/`web_fetch` and contains **no** tool with `writes=True`; assert by iterating `registry.names()` and checking `getattr(tool, "writes", False)`.

### M3 — Finding record with provenance, confidence, and verification state (EXTEND)

- **Scope:** A finding is only emitted with: the claim, its provenance (file:line from `code_search`, or document passage from `grounding`), a confidence label from the existing `_CONF` vocabulary (`grounding.py:26`), and — for severity High/Critical — a `verified_by` field populated by an independent pass.
- **Files:** extend `backend/app/services/supreme/scanner.py:61` (`Finding`) with the three fields, or a Dark-KAI-local record that reuses the same severity vocabulary. **Do not build a second scanner framework** — `scan_once` (`:352`), `save_proposal` (`:374`), `_severity_counts` (`:388`), `format_findings_for_telegram` (`:425`), `run_full_cycle` (`:451`) already exist.
- **Dependencies:** #40 for code provenance. `grounding`/`verify_claim` are on istanbul.
- **Risks:** (a) Adding required fields to `Finding` breaks the 7 existing scanners and 29 `test_supreme.py` tests unless the new fields default to `None` — default them. (b) The independent-verification pass costs extra LLM calls per High/Critical finding; it must be charged against `Budget` (`budget.py:73-77` `charge_tokens`/`charge_cost`) or it escapes the ceiling.
- **Verify:** a test asserting a High-severity finding without `verified_by` is **rejected** at emit time, and that emitting it triggers a `grounding.verify_statement` call (mock the router; `verify_claim.py:50-56` shows the call shape). Plus `pytest tests/test_supreme.py -q` (29 tests) still green.

### M4 — Sentinel scanners for adversarial monitoring (EXTEND)

- **Scope:** New `Scanner` subclasses only. Candidates grounded in real gaps this audit found: audit-chain integrity (from M1), scope-wildcard exposure (does any `KAI_SCOPE_<PARENT>` env transitively enable a destructive scope — `actions.py:60-62`), and unexpected tool-registry membership.
- **Files:** `backend/app/services/dark_kai/scanners.py`; register in `supreme/scanner.py:352` (`scan_once`).
- **Dependencies:** M1 (chain to verify), M2 (registry filter to compare against). Runs on istanbul otherwise.
- **Risks:** the supreme scheduler is an in-process daemon thread (`main.py:47-51`, default OFF, `supreme/scheduler.py:30`) with a 900s default interval — a slow scanner blocks the whole cycle. Keep each scan read-only and bounded, as the existing 7 are.
- **Verify:** `scan_once()` with a deliberately corrupted audit line returns a Critical finding; with a clean log returns none. Assert against `_severity_counts` (`scanner.py:388`).

### M5 — Builder mode wiring (REUSE, thin)

- **Scope:** Route Dark KAI's Builder mode into the **existing** `admin_swe_tasks` flow. No new push code, no new approval code, no new task table.
- **Files:** `backend/app/routers/admin_dark_kai.py` only (delegating calls).
- **Dependencies:** #42 fully merged, M2.
- **Risks:** (a) `kai_swe_tasks` has **no `user_id` and no RLS** — "Single-operator model" is explicit at `backend/app/models/swe_task.py:9`. Anyone past the shared `X-Admin-Token` sees and acts on every task, including Dark KAI's. Accept it as a documented single-operator assumption or fix it in `swe_task.py`/`task_store.py` — do not paper over it in Dark KAI. (b) `swe_admin_enabled()` refuses `staging` (`config.py:28`), and the operator memo notes `APP_ENV=staging` is currently used as a prod workaround — Builder mode will be unavailable on that host by design. Confirm intent before "fixing" it.
- **Verify:** an end-to-end test through the three gates asserting a push attempt with no `X-Approver-Token` returns 403 (`approver.py:46`), an expired approval returns 409 (`admin_swe_tasks.py:252`), and a protected-branch target raises `PolicyDenied` (`push.py:188-189`). `tests/services/swe_runtime/test_admin_swe_tasks.py` (23 tests) + `test_push.py` (14 tests) cover most of this already — extend, don't duplicate.

### M6 (deferred) — Simulation mode

Not built in the first pass. Lab already provides isolated execution of arbitrary code. Revisit only when a concrete adversarial scenario exists that Lab cannot express.

---

## 4. Known weaknesses Dark KAI inherits (fix or accept explicitly — do not re-implement around)

1. **Scope wildcard widening** — `actions.py:60-62`: `KAI_SCOPE_<FIRST_SEGMENT>=1` enables every scope under it including destructive ones. `KAI_SCOPE_SOL` transitively enables `sol.transfer` (real ACH, `backend/app/routers/sol.py:340-352`), and `KAI_SCOPE_SOL` is exactly what the Sol scheduler requires (`services/sol/scheduler.py:60-62`). The SWE work defends against this with a disjoint `swepush` root; Sol, Dwolla, browser, and planning do not. Dark KAI must adopt the disjoint-root pattern (M2 risk (a)).
2. **`approved` is caller-supplied outside the SWE gates** — `actions.py:52` pops it from kwargs; routes forward it straight from the request body. Only `require_approver` (`approver.py:39-53`) binds approval to a proven identity. Dark KAI destructive actions must use `require_approver`, not body `approved`.
3. **One shared `X-Admin-Token` for the entire `/admin/*` surface** — `backend/app/dependencies/admin.py:99-110`; the audit `actor` defaults to the literal string `"operator"` (`actions.py:75`). Dark KAI attribution is only as good as this until `admin_users`-backed auth lands.
4. **`@audited` is sync-only** — `wrapper` at `actions.py:51` is a plain `def`; decorating an `async def` would log success against an un-awaited coroutine. Keep every Dark KAI audited entry point synchronous, or fix the decorator first.
5. **`web_fetch` SSRF guard is bypassable** — `backend/app/services/tools/web_fetch.py:62-78` string-prefix-matches the literal hostname then calls `httpx.get(..., follow_redirects=True)` with no re-check per hop; a public URL that 302s to `169.254.169.254` passes. If Analysis mode includes `web_fetch`, fix the guard (resolve + `ipaddress.ip_address(...).is_private/is_loopback/is_link_local`, re-check every hop) or exclude the tool.
6. **Spend cap is soft and evaluated once per turn** — `router.py:106` consults `over_daily_cap` at turn start; a multi-iteration tool loop (`DEFAULT_MAX_TOOL_ITERS = 5`, `router.py:25`) can run past the cap without re-checking, and over-cap degrades to a local model rather than refusing (`router.py:102-108`). `Budget.check()` (`budget.py:57-68`) is the real per-mission bound — rely on that.
7. **Streaming cost is estimated, not measured** — `router.py:215-228` (`len(text)//4`), tagged `estimated_tokens: True`. Dark KAI cost ceilings should not depend on streamed-turn accounting.

## 5. UNVERIFIED

- Whether `origin/feat/sol-v1`'s 0007–0020 migration chain is intended to merge at all; if it is, the head reconciliation in M0 is larger than described.
- `backend/app/services/self_correction/` internals (I read only its call sites in `admin_chat.py:255-294`). The claim that `run_correction_loop` constitutes an *independent* verifier — as opposed to the same model critiquing itself — needs a read of that module before M3 relies on it for P8.
- Whether the 966 test functions in `backend/tests/` pass; I did not execute the suite (this repo's `requirements.txt` is unsatisfiable and needs a curated venv + local Postgres). All test counts here are counts of `def test_`, not verified passes.
- Whether `celery beat` runs in production at all — no Procfile/Dockerfile in `backend/`; only `railway.json` (which starts a *different* app, `core/api.py`).
