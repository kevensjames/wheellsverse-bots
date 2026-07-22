# Dark KAI — Acceptance Criteria

Testable acceptance criteria for **Dark KAI**, a governed adversarial-research subsystem
built *inside* KAI. Every criterion is a checkable assertion with the test that proves it.

**Repo:** `/Users/jhonwheeler/wheellsverse-kai-audit` · **Branch of record:** `feat/kai-swe-agent` (PR #42)

## Provenance rules used in this document

Merge status was verified, not assumed:

- `git diff --name-only origin/istanbul...HEAD` — the only files on `feat/kai-swe-agent` that are
  not on merged `istanbul` are the SWE set (`backend/app/services/swe_runtime/*`,
  `app/routers/admin_swe.py`, `app/routers/admin_swe_tasks.py`, `app/dependencies/approver.py`,
  `app/models/swe_task.py`, `app/services/governance/audit_log.py`, `app/main.py`,
  `alembic/versions/0007_add_kai_swe_tasks.py`, `backend/.env.example`, and their tests).
- `git diff --name-only istanbul...fix/kai-governed-tool-loop` (PR #39),
  `...fix/kai-code-intelligence` (PR #40), `...fix/kai-swe-sandbox` (PR #41) — **none of these four
  branches is merged into `istanbul`.**

Every criterion below is tagged with where its evidence lives:

| Tag | Meaning |
|---|---|
| `[istanbul]` | On merged `istanbul` — available today |
| `[PR#39]` `[PR#40]` `[PR#41]` `[PR#42]` | Exists only on that open, unmerged branch |
| `[NEW]` | Does not exist anywhere I could verify — Dark KAI must build it |

**Status values:** `MET` (a real test file/case exists and asserts it) · `PARTIAL` (asserted for one
subsystem, not for Dark KAI's scope) · `NOT MET` (no test asserts it).

### Reuse mandate (directive §1.6)

Dark KAI must not duplicate money movement, auth, audit logging, or provider routing. The concrete
reuse map, verified by reading each file:

| Dark KAI need | Reuse this, do not rebuild |
|---|---|
| Tool broker + audit on every call | `app/services/tools/registry.py` as amended by **PR #39** |
| Disposable network-none sandbox | `app/services/swe_runtime/sandbox.py`, `policy.py`, `config.py` (**PR #41**) |
| Two human gates, branch-only push, budgets, kill switch | `app/routers/admin_swe_tasks.py`, `swe_runtime/{brain,budget,push}.py` (**PR #42**) |
| Proven approver identity | `app/dependencies/approver.py` (**PR #42**) |
| Scope + approval decorator | `app/services/governance/actions.py` `@audited` (**istanbul**) |
| Audit sink + redaction | `app/services/governance/audit_log.py` (**istanbul**; value-regex scrub is **PR#42**) |
| Semantic code search with provenance + tenant isolation | `app/services/code_intel/*`, `tools/code_search.py` (**PR #40**) |
| Cost ceiling | `app/services/router/spend_tracker.py` (**istanbul**) + `swe_runtime/budget.py` (**PR #42**) |

---

## 1. Default-off

| # | Assertion | Test | Status |
|---|---|---|---|
| DO-1 | With no `KAI_DARK_*` env set, no Dark KAI router is mounted on the app — `TestClient` GET/POST of every Dark KAI path returns 404, not 403. | `[NEW]` new `backend/tests/services/dark_kai/test_dark_gating.py::test_routes_not_mounted_by_default`. Model on `[PR#41]` `backend/tests/services/swe_runtime/test_swe_admin_gating.py::test_swe_admin_mount_allowlist` (asserts the SWE surface mounts only on an allow-listed non-prod `APP_ENV`, `swe_runtime/config.py:32-42`, wired at `app/main.py:192-200`). | NOT MET |
| DO-2 | `dark_runtime_enabled()` is False when its env var is unset. | `[NEW]`, mirroring `[PR#41]` `test_swe_policy.py::test_disabled_by_default` against `swe_runtime/config.py:18-19` (`runtime_enabled()` reads `KAI_SWE_RUNTIME_ENABLED`, default off). | NOT MET |
| DO-3 | Every governance scope Dark KAI declares is denied when its env var is unset. | `[istanbul]` `backend/tests/test_governance.py::test_scope_disabled_by_default` — proves `is_scope_enabled` (`governance/actions.py:56-63`) is deny-by-default for *any* scope, so this holds for Dark KAI scopes the moment they route through `@audited`. | **MET** (mechanism) |
| DO-4 | An explicit `ENV=production` marker vetoes Dark KAI even when `APP_ENV` looks non-prod. | `[PR#41]` `test_swe_admin_gating.py::test_env_prod_marker_vetoes_nonprod_app_env` proves the veto for SWE (`swe_runtime/config.py:29,32-42`); Dark KAI must be added to the same gate and get its own case. | PARTIAL |

---

## 2. Broker enforcement (no tool call escapes the broker)

The single model-driven execution point today is `app/services/router/router.py:374`
(`tool_result = tool_registry.execute(tc.name, tc.arguments, tool_context)`), which calls
`ToolRegistry.execute` at `app/services/tools/registry.py:58-84`. **On merged `istanbul` that path
has no scope check, no approval check and no audit record** — verified: `grep -rn "@audited"
backend/app/services/tools/` returns 0 matches. PR #39 is the fix.

| # | Assertion | Test | Status |
|---|---|---|---|
| BR-1 | Every call through the registry emits an audit record, including blocked and error paths. | `[PR#39]` `backend/tests/test_tool_governance.py::test_every_call_is_audited` and `::test_unknown_tool_errors_and_is_audited`. | MET **only if #39 merges** |
| BR-2 | A side-effecting tool is blocked unless the context explicitly authorizes writes (default-deny). | `[PR#39]` `test_tool_governance.py::test_write_tool_blocked_without_authorization` + `::test_safe_by_default`. | MET on #39 |
| BR-3 | A read-only tool runs regardless of the write flag (the broker is not a blanket kill switch). | `[PR#39]` `test_tool_governance.py::test_read_tool_executes_regardless_of_allow_writes`. | MET on #39 |
| BR-4 | A scoped write tool is blocked when its scope env is off and runs when on. | `[PR#39]` `test_tool_governance.py::test_scoped_write_blocked_when_scope_disabled` / `::test_scoped_write_allowed_when_scope_enabled`. | MET on #39 |
| BR-5 | Every real write tool declares `writes=True` — no tool silently mutates while classified read-only. | `[PR#39]` `test_tool_governance.py::test_real_write_tools_declare_writes`. Dark KAI must extend this case to its own tools. | PARTIAL |
| BR-6 | Dark KAI agents get a *restricted* registry: `dwolla`, `twenty_crm`, `composio`, `notion`, and MCP tools are absent from a Dark KAI `ToolContext`. | `[NEW]` `test_dark_registry.py::test_operator_credentialed_tools_absent`. Today `build_default_registry()` (`app/services/tools/__init__.py:46-160`) registers Composio/MCP/Twenty for any authenticated `/kai/chat` user; `backend/tests/test_tool_registry.py` (9 cases) only covers register/lookup/execute mechanics, not membership policy. | NOT MET |
| BR-7 | A Dark KAI agent cannot reach `ToolRegistry.execute` except through the broker entry point — no direct import of a tool module in agent code. | `[NEW]`, modelled on `[PR#42]` `backend/tests/services/swe_runtime/test_brain.py::test_brain_reaches_world_only_through_runtime`, which asserts exactly this containment property for the SWE brain. | NOT MET (pattern exists) |

---

## 3. Approval gating

| # | Assertion | Test | Status |
|---|---|---|---|
| AG-1 | A destructive action without `approved=True` raises `PendingApproval` and never executes; with approval it executes; non-destructive skips the check. | `[istanbul]` `tests/test_governance.py::test_destructive_without_approval_pending`, `::test_destructive_with_approval_runs`, `::test_non_destructive_skips_approval` (`governance/actions.py:96-120`). | **MET** |
| AG-2 | Approval is bound to a **proven identity**, not a caller-supplied boolean. | `[PR#42]` `test_admin_swe_tasks.py::test_approver_identity_is_not_self_declared`, `::test_gate1_requires_approver_token`, `::test_require_approver_resolves_token_to_admin_user` — `app/dependencies/approver.py:39-52` hashes `X-Approver-Token` (SHA-256) against `admin_users.password_hash` and returns the row's email as the audit actor. **This is the only place in the repo where approval names a proven identity**; everywhere else `approved` is popped from kwargs (`governance/actions.py:91`) and forwarded straight from the request body (e.g. `app/routers/sol.py:340-352`). Dark KAI MUST use `require_approver`, not a body flag. | MET for SWE; Dark KAI must adopt |
| AG-3 | Gate 1 (plan approval) does not execute anything while unapproved; approving twice is refused. | `[PR#42]` `test_admin_swe_tasks.py::test_gate1_unapproved_does_not_execute`, `::test_double_approve_blocked`, `::test_reject`; store-level `test_task_store.py::test_double_approve_is_blocked`. | MET for SWE |
| AG-4 | Gate 2 (apply/push approval) is a *separate* scope from Gate 1 and is not reachable by a wildcard parent. | `[PR#42]` `test_swe_admin_gating.py::test_swepush_scope_not_enabled_by_swe_wildcard` and `test_admin_swe_tasks.py::test_gate2_swe_wildcard_does_not_grant_push` — the push scope is deliberately named `swepush.execute` (`admin_swe_tasks.py:301`) so `KAI_SCOPE_SWE` cannot reach it. Dark KAI's apply scope must use a disjoint root for the same reason. | MET for SWE |
| AG-5 | The approved artifact is bound to what was reviewed — a patch whose sha256 changed after approval is refused. | `[PR#42]` `test_admin_swe_tasks.py::test_gate2_patch_sha_mismatch_blocks_push` (`admin_swe_tasks.py:279-280`). | MET for SWE |
| AG-6 | Separation of duties: the same approver cannot pass both gates when two-person mode is on. | `[PR#42]` `test_admin_swe_tasks.py::test_two_person_control_blocks_same_approver` (`approver.py:34`, enforced `admin_swe_tasks.py:311`). | MET for SWE |
| AG-7 | **`require_approver` filters on `role`.** Its own docstring prescribes `role='approver'` (`approver.py:19-20`) but the query at `approver.py:47-52` has no role filter — any `admin_users` row whose `password_hash` is a raw SHA-256 hex is an approver. | `[NEW]` `test_approver_role_filter.py::test_non_approver_role_rejected`. **This is a real defect in PR #42 that Dark KAI must not inherit.** | **NOT MET** |
| AG-8 | Approval expires: a gate approved longer ago than the timeout cannot be redeemed. | `[PR#42]` lazy expiry at `admin_swe_tasks.py:75-85` (`KAI_SWE_APPROVAL_TIMEOUT_HOURS`). No test case in `test_admin_swe_tasks.py` names expiry. | NOT MET |
| AG-9 | One approval never authorizes an unbounded downstream tool loop. | `[NEW]` `test_dark_no_blanket_approval.py`. Counter-example on `[istanbul]`: `POST /admin/planning/{id}/execute-next` is `@audited(scope="planning.execute", destructive=True)` (`app/routers/admin_planning.py:201-215, 323`) but then calls `build_default_registry()` and runs LLM-authored steps — one approval, no per-tool audit. Dark KAI must not repeat this shape. | **NOT MET** |

---

## 4. Sandbox isolation (Lab mode)

Reuse `[PR#41]` `app/services/swe_runtime/sandbox.py` verbatim. Its container args
(`sandbox.py:83-86`) are `--network none`, `--pids-limit`, `--cpus`, `--cap-drop ALL`,
`--security-opt no-new-privileges`, plus memory cap and a wall-clock `docker kill`.

| # | Assertion | Test | Status |
|---|---|---|---|
| SB-1 | The container is created with the full lockdown arg set. | `[PR#41]` `test_swe_policy.py::test_build_create_args_has_full_lockdown`. | MET on #41 |
| SB-2 | Network egress is actually impossible from inside the sandbox (not just asserted in args). | `[PR#41]` `test_swe_sandbox.py::test_network_is_cut`. | MET on #41 |
| SB-3 | The sandbox edits a disposable copy; the host source directory is unchanged after a run. | `[PR#41]` `test_swe_sandbox.py::test_edits_disposable_copy_and_captures_artifacts`, `::test_host_source_is_not_mutated`. | MET on #41 |
| SB-4 | A symlink pointing out of the workspace is not followed, and a symlink to a device does not hang the run. | `[PR#41]` `test_swe_sandbox.py::test_symlink_to_host_file_is_not_followed`, `::test_symlink_to_device_does_not_hang`. | MET on #41 |
| SB-5 | A run exceeding the wall clock is killed. | `[PR#41]` `test_swe_sandbox.py::test_wall_clock_timeout_kills`. | MET on #41 |
| SB-6 | Only allow-listed images run; the image allowlist has a safe default. | `[PR#41]` `test_swe_policy.py::test_policy_denies_disallowed_image`, `::test_image_allowlist_default` (`swe_runtime/config.py:45-46, 86-87`). | MET on #41 |
| SB-7 | Source roots are deny-by-default: with no `KAI_SWE_REPO_ALLOWLIST`, nothing is runnable; with one, only paths resolving under it. | `[PR#41]` `test_swe_policy.py::test_repo_allowlist_deny_by_default`, `::test_repo_allowlist_allows_only_under_root` (`config.py:90-102`). | MET on #41 |
| SB-8 | Agents cannot run raw shell: egress and credential-reading commands are refused at the policy boundary before the container starts. | `[PR#41]` `test_swe_policy.py::test_policy_denies_egress_and_credential_commands`, `::test_policy_allows_ordinary_command` (`swe_runtime/policy.py:16-24`, deny-by-substring). **Ceiling to state honestly:** substring matching is not a shell parser — it is defense-in-depth on top of `--network none`, as `policy.py:3-5` itself says. Dark KAI must not treat it as the primary control. | MET on #41, with named ceiling |
| SB-9 | A denied step aborts the mission rather than degrading to an unsandboxed path. | `[PR#42]` `test_brain.py::test_execute_policy_denied_step_fails`, `::test_execute_disabled_sandbox_fails`. | MET on #42 |
| SB-10 | Dark KAI's Lab mode uses this sandbox — no second container implementation exists. | `[NEW]` `test_dark_lab.py::test_lab_uses_swe_sandbox` (assert the import path). Enforces directive §1.6. | NOT MET |

---

## 5. Credential isolation (no prod credentials in experiments)

| # | Assertion | Test | Status |
|---|---|---|---|
| CI-1 | No ambient git credential is usable: a remote host without an explicit token refuses the push rather than falling back. | `[PR#42]` `test_push.py::test_remote_host_without_token_refuses_no_ambient`, `::test_resolve_credential` (`push.py:15-17, 141-160, 206`: empty `HOME`, cleared `GIT_CONFIG_GLOBAL`/`credential.helper`). | MET on #42 |
| CI-2 | Only `https` push URLs are accepted; `ssh`/`http` are refused so no ambient key is used. | `[PR#42]` `test_push.py::test_https_push_url_normalizes_and_refuses_insecure` (`push.py:109-111`). | MET on #42 |
| CI-3 | Credentials never appear in logs or audit output — remote userinfo is stripped. | `[PR#42]` `test_push.py::test_redact_remote_strips_userinfo` (`push.py:125-129`). | MET on #42 |
| CI-4 | Secrets embedded in audit *values* (not just secret-named keys) are scrubbed. | `[PR#42]` `backend/tests/services/test_audit_value_redaction.py` (3 cases: bearer token in a value, token in a positional-arg list, non-secret value untouched) against `audit_log.py:96, 128-131`. On merged `istanbul` only key-name redaction exists (`audit_log.py:107-121`), covered by `[istanbul]` `test_governance.py::test_secret_keys_redacted_in_inputs`. | MET on #42 |
| CI-5 | Source code indexed for search is secret-scrubbed before embedding or storage. | `[PR#40]` `backend/tests/services/code_intel/test_secrets_redaction.py` (9 cases: private key drops the whole chunk, AWS key, DB URL with creds, JWT, OpenAI/GitHub tokens incl. modern PAT forms, inline assignment, and `::test_ordinary_code_is_not_mangled`). | MET on #40 |
| CI-6 | The search *query* is redacted before it is sent to the embedding provider. | `[PR#40]` `test_tenant_isolation.py::test_search_redacts_query_before_embedding`. | MET on #40 |
| CI-7 | **No production credential is present in a Dark KAI experiment env.** Assert the Lab container env contains none of `DWOLLA_KEY`, `DWOLLA_SECRET`, `STRIPE_SECRET_KEY`, `ADMIN_TOKEN`, `SUPABASE_SECRET_KEY`, `TWENTY_API_KEY`, `COMPOSIO_API_KEY`, `KAI_SWE_PUSH_TOKEN`. | `[NEW]` `test_dark_credential_isolation.py::test_experiment_env_has_no_prod_secrets`. The sandbox has no host mount and no network, but I found **no test asserting the env allowlist**. | **NOT MET** |
| CI-8 | Dwolla cannot reach production without an explicit second latch. | `[istanbul]` `DwollaClient.__init__` raises `DwollaProductionLocked` unless `DWOLLA_ALLOW_PRODUCTION=1` (`app/services/dwolla/client.py:80-85`); `backend/tests/test_dwolla.py` (19 cases) covers the client. Dark KAI must never set that var. | MET (mechanism) |
| CI-9 | The Composio confused-deputy path is closed for Dark KAI. `app/services/tools/composio_auth.py:35-37` resolves *every* user's Composio calls to `COMPOSIO_USER_ID` when set, so one tenant's prompt acts as the operator. | `[NEW]` — covered for Dark KAI by BR-6 (exclude Composio entirely). | NOT MET |

---

## 6. Provenance and confidence on every claim

| # | Assertion | Test | Status |
|---|---|---|---|
| PC-1 | A search result carries provenance (repo/path/symbol/lines) and a citation note. | `[PR#40]` `backend/tests/services/code_intel/test_code_search_tool.py::test_returns_provenance_and_citation_note`. | MET on #40 |
| PC-2 | Text retrieved from a source is treated as **data, not instructions** — an injected instruction inside indexed content does not become a command. | `[PR#40]` `test_code_search_tool.py::test_injected_instruction_is_data_not_command`. This is the prompt-injection acceptance test Dark KAI needs for every retrieval tool it adds. | MET on #40 for `code_search` |
| PC-3 | The retrieval tool is registered read-only. | `[PR#40]` `test_code_search_tool.py::test_read_only_and_registered`. | MET on #40 |
| PC-4 | Chunk boundaries are stable and degrade safely on unsupported/malformed input (so line citations are trustworthy). | `[PR#40]` `test_chunking.py` (5 cases incl. `::test_malformed_source_does_not_crash`, `::test_unsupported_language_falls_back_without_error`). | MET on #40 |
| PC-5 | **Every Dark KAI finding record carries a `confidence` field and at least one provenance citation; a finding with neither is rejected at write time.** | `[NEW]` `test_dark_findings.py::test_finding_without_provenance_rejected`, `::test_confidence_required_and_bounded`. Nothing in the repo models a "finding" — `[istanbul]` `app/services/tools/verify_claim.py` is registered in `build_default_registry()` (`tools/__init__.py`) but I did **not** read it; whether it emits a confidence score is **UNVERIFIED** (needs a read of `verify_claim.py`). | **NOT MET** |

---

## 7. Independent verification of High/Critical findings

| # | Assertion | Test | Status |
|---|---|---|---|
| IV-1 | A finding rated High or Critical cannot reach `verified` state without a second verification pass by a *different* verifier than the one that produced it. | `[NEW]` `test_dark_verification.py::test_high_finding_requires_independent_pass`, `::test_same_agent_cannot_self_verify`. | **NOT MET** |
| IV-2 | The state machine enforces this — an illegal transition raises and leaves the row unchanged. | `[NEW]`, but the pattern is proven: `[PR#42]` `test_task_store.py::test_illegal_transition_raises_and_leaves_row_unchanged`, `::test_check_constraint_rejects_unknown_status`, `::test_unknown_target_status_rejected_before_db` over the 9-state CHECK constraint in `app/models/swe_task.py:26-30`. Dark KAI's finding lifecycle should be the same shape. | NOT MET (pattern exists) |
| IV-3 | A crash mid-verification marks the finding failed, never leaves it stranded in an in-progress state. | `[NEW]`, pattern from `[PR#42]` `test_admin_swe_tasks.py::test_execute_crash_marks_failed_not_stranded`, `::test_reject_unsticks_stranded_executing`, `::test_reject_unsticks_stranded_pushing`. | NOT MET (pattern exists) |
| IV-4 | Self-correction / verification passes are not silently unbounded LLM spend. `POST /admin/kai-chat` already runs optional self-correction + verification passes, each adding LLM calls (`app/routers/admin_chat.py:167-176`). | `[NEW]` tie to CC-2 below. | NOT MET |

---

## 8. Branch-only changes (Builder mode)

| # | Assertion | Test | Status |
|---|---|---|---|
| BO-1 | The push destination is always the derived review branch `kai/swe/<id>` — never the default branch. | `[PR#42]` `test_push.py::test_apply_and_push_creates_review_branch_not_default`, `::test_review_branch_for` (`push.py:64-70, 187`). | MET on #42 |
| BO-2 | A protected branch is refused before any filesystem work. | `[PR#42]` `test_push.py::test_protected_default`, `::test_protected_task_id_refused_before_fs` (`push.py:53-56, 188-189`, `KAI_SWE_PROTECTED_BRANCHES`). | MET on #42 |
| BO-3 | `--force` is never emitted — a non-fast-forward push fails rather than overwriting. | `[PR#42]` asserted in `push.py:8-9`; no test case in `test_push.py` names force. Add `test_push.py::test_no_force_flag_in_push_args`. | **NOT MET** (documented, untested) |
| BO-4 | An empty patch, or a dirty source tree, is refused. | `[PR#42]` `test_push.py::test_empty_patch_refused`, `::test_dirty_source_refused`. | MET on #42 |
| BO-5 | A patch touching CI paths is refused, including quoted-path and rename bypass attempts. | `[PR#42]` `test_push.py::test_patch_touches_ci`, `::test_ci_patch_refused_before_fs`, `::test_ci_quoted_path_bypass_blocked`, `::test_ci_rename_bypass_blocked` (`push.py:72-104`). | MET on #42 |
| BO-6 | A Builder run that produced no diff fails loudly rather than reporting success. | `[PR#42]` `test_brain.py::test_execute_no_changes_fails`, `::test_execute_nonzero_exit_fails`. | MET on #42 |

---

## 9. No agent deploys to production

| # | Assertion | Test | Status |
|---|---|---|---|
| ND-1 | Dark KAI routers are absent from the app when `APP_ENV`/`ENV` indicate production. | `[PR#41]` gate exists for SWE (`swe_runtime/config.py:32-42`, `main.py:192-200`), tested by `test_swe_admin_gating.py::test_swe_admin_mount_allowlist` + `::test_env_prod_marker_vetoes_nonprod_app_env`. `[NEW]` case needed for Dark KAI paths. | PARTIAL |
| ND-2 | No Dark KAI code path invokes a deploy mechanism. Assert by policy denylist: the sandbox command policy rejects `railway up`, `cloudflared`, `launchctl`, `docker push`, and `git push` to a non-review ref. | `[NEW]` `test_dark_policy.py::test_deploy_commands_denied`. The deploy surface is real: `deploy/start_nai.sh` + `deploy/launchd/com.wheellsverse.kai.plist` (LaunchDaemon, `KeepAlive true`) run the KAI daemon on the Mac mini; `railway.json` deploys a *different* app (`core/api.py`). Neither is currently covered by any test — I found no test exercising `deploy/health_check.sh` or `start_nai.sh`. | **NOT MET** |
| ND-3 | Dark KAI never writes to the host `.env` or restarts the daemon. Counter-example to stay away from: `[istanbul]` self-heal rewrites `OLLAMA_MODEL_MAP` in `.env` and `rmtree`s `__pycache__` (`app/services/self_heal.py:147-165`), scheduled by `main.py:56-60`. | `[NEW]` `test_dark_no_host_writes.py`. Note self-heal itself is covered by `[istanbul]` `backend/tests/test_self_heal.py`. | NOT MET |
| ND-4 | Dark KAI cannot enable `DWOLLA_ALLOW_PRODUCTION`, `KAI_SOL_AUTOPILOT`, or any `KAI_SCOPE_*` var at runtime. | `[NEW]` `test_dark_no_scope_escalation.py::test_agent_cannot_mutate_env`. | NOT MET |

---

## 10. Kill switches

| # | Assertion | Test | Status |
|---|---|---|---|
| KS-1 | Flipping the runtime flag off stops new work immediately, even for an already-created task — the flag is re-read per request, not cached at import. | `[PR#42]` `test_admin_swe_tasks.py::test_create_runtime_disabled` and `[PR#41]` `test_swe_policy.py::test_disabled_by_default` / `::test_enabled_selects_docker` (`config.py:14-19` reads `os.environ` per call). | MET on #41/#42 |
| KS-2 | Turning a scope off blocks execution at the gate even for an approved task. | `[PR#42]` `test_admin_swe_tasks.py::test_create_requires_scope`, `::test_gate1_requires_execute_scope`, `::test_gate2_requires_swepush_scope`. | MET on #42 |
| KS-3 | A scheduler kill switch is re-checked every tick, not only at startup. | `[istanbul]` proven pattern: `app/services/self_heal_scheduler.py:45-58` re-checks the enable flag *and* scope each tick; same in `digest/scheduler.py:37-58`, `sol/scheduler.py:42-62`, `checkin/scheduler.py:40-56`. Sentinel mode must follow this. `[NEW]` test for Dark KAI's Sentinel loop. | PARTIAL |
| KS-4 | **A wildcard parent scope cannot enable a Dark KAI destructive scope.** `is_scope_enabled` derives `parent = norm.split("_")[0]` (`governance/actions.py:56-63`), so `KAI_SCOPE_SOL=1` transitively enables `sol.transfer`, `KAI_SCOPE_PLANNING=1` enables `planning.execute`, `KAI_SCOPE_BROWSER=1` enables `browser.execute`. | `[istanbul]` `test_governance.py::test_scope_enabled_via_wildcard_parent` **asserts the widening as intended behavior** — it is a documented feature, not a bug caught by tests. Dark KAI must therefore use disjoint roots per destructive scope (the `swepush` trick, `[PR#42]` `test_swe_admin_gating.py::test_swepush_scope_not_enabled_by_swe_wildcard`) and add `test_dark_scopes.py::test_no_dark_destructive_scope_reachable_by_wildcard`. | **NOT MET** |
| KS-5 | An in-flight mission aborts on kill-switch flip (not just new missions blocked). | `[NEW]` `test_dark_kill_switch.py::test_inflight_mission_aborts`. Budget `check()` runs before each act (`swe_runtime/budget.py:56`), which is the natural hook. | NOT MET |

---

## 11. Cost ceilings

| # | Assertion | Test | Status |
|---|---|---|---|
| CC-1 | A per-mission budget bounds steps, tokens, wall time and dollars, and a breach stops the loop and is persisted as failed — never silent. | `[PR#42]` `test_brain.py::test_budget_check_raises_at_max_steps`, `::test_budget_check_raises_on_tokens_and_cost` against `swe_runtime/budget.py:33-37` (defaults 8 steps / 200k tokens / 900 s / $1.00) and `::test_execute_plan_too_long_fails`. | MET on #42 |
| CC-2 | The outer daily LLM cap is enforced. | `[istanbul]` `backend/tests/test_spend_tracker.py::test_over_daily_cap` (3 cases total in that file) against `spend_tracker.py:18-19`. **Honest limit:** the cap is *soft* — `router.py:106-108` routes over-cap traffic to a free local model rather than refusing, it is evaluated once at turn start, and a multi-iteration tool loop can run its full `DEFAULT_MAX_TOOL_ITERS` (`router.py:25`) past the cap without re-checking. `over_monthly_cap` (`spend_tracker.py:119`) is defined but never referenced in `router.py`. | PARTIAL |
| CC-3 | **Dark KAI refuses rather than degrades when over budget** (a research agent silently downgraded to a local model produces low-quality claims, which is worse than stopping). | `[NEW]` `test_dark_budget.py::test_over_cap_refuses_not_degrades`. | **NOT MET** |
| CC-4 | Streaming spend is measured, not estimated. `router.py:215-228` computes `len(text)//4` and tags `estimated_tokens: True`. | `[NEW]`, or: Dark KAI does not use the streaming path (`Router.stream` passes no registry, `router.py:171-228`, so it cannot reach tools anyway). | NOT MET |
| CC-5 | Unknown models cost $0.00 silently (`app/services/router/adapters/base.py:11-37` `calculate_cost`) — Dark KAI must fail closed on an unpriced model. | `[NEW]` `test_dark_budget.py::test_unpriced_model_refused`. | **NOT MET** |

---

## 12. Audit durability and immutability

| # | Assertion | Test | Status |
|---|---|---|---|
| AD-1 | Every governed action is audited on success, denial, and exception. | `[istanbul]` `test_governance.py::test_scope_denied_raises_and_audits`, `::test_exception_in_wrapped_function_is_audited`, `::test_audit_log_has_id_and_timestamp`, `::test_actor_can_be_overridden`. | **MET** |
| AD-2 | Audit records are queryable newest-first and filterable by scope, and a missing log is not an error. | `[istanbul]` `test_governance.py::test_list_actions_newest_first`, `::test_list_actions_filter_by_scope`, `::test_list_actions_empty_when_log_missing`; `[istanbul]` `tests/test_audit.py::test_audit_counts_sqlite_and_jsonl`, `::test_admin_audit_requires_token`. | **MET** |
| AD-3 | Long values are truncated so the log cannot be flooded by one record. | `[istanbul]` `test_governance.py::test_long_values_truncated_in_log`. | **MET** |
| AD-4 | **For irreversible actions, the audit record is fsync'd before the action, and a write failure aborts the action.** | `[PR#42]` `test_push.py` exercises `_write_push_audit_or_raise` (`push.py:161-179`, `os.fsync` at `:176`) — the only fail-closed audit in the repo. Everywhere else `record_action` is deliberately fail-soft: `[istanbul]` `test_governance.py::test_audit_write_failure_does_not_break_action` **asserts that a failed audit write silently drops the record and lets the action proceed.** Dark KAI's Builder/Lab writes must use the fail-closed variant. | PARTIAL — and the default is the wrong way round |
| AD-5 | **The audit log is tamper-evident** (hash chain or HMAC). `grep -rn "prev_hash\|chain\|hmac" backend/app/services/governance/` → no matches. It is plain appended JSON lines at `KAI_AUDIT_LOG_PATH` (`audit_log.py:36`), writable by the daemon, while `app/services/audit/auditor.py:31` advertises it as "tamper-evident". | `[NEW]` `test_audit_chain.py::test_modified_record_breaks_chain`. | **NOT MET — the claim in the code is currently false** |
| AD-6 | The audit log does not grow unbounded. `grep -rn "retention\|prune\|VACUUM\|DELETE FROM" backend/app` returns only a comment in `billing.py:203`, a docstring, and `planning/storage.py:406`. No rotation exists for `data/governance/audit.jsonl`, `data/failures.jsonl`, or the two digest JSONLs. | `[NEW]` `test_audit_retention.py`. | **NOT MET** |
| AD-7 | `@audited` is never applied to an `async def` (the wrapper at `governance/actions.py:90` is a plain `def` and would log success against an un-awaited coroutine). | `[NEW]` `test_governance.py::test_no_async_audited_targets` — a static scan. No current target is async, but nothing prevents it. | **NOT MET** |
| AD-8 | Dark KAI attributes actions to a real identity, not the constant `"operator"` (`governance/actions.py:75`) that the single shared `ADMIN_TOKEN` forces today. | `[NEW]`; the mechanism to reuse is `require_approver` (AG-2), which returns the `admin_users` row email. | NOT MET |

---

## 13. Tenant isolation

| # | Assertion | Test | Status |
|---|---|---|---|
| TI-1 | A user's semantic search returns only their own rows. | `[PR#40]` `test_tenant_isolation.py::test_user_sees_only_own_rows`. | MET on #40 |
| TI-2 | A spoofed `repo_id` cannot cross users, and a large `k` does not leak other tenants' rows. | `[PR#40]` `test_tenant_isolation.py::test_spoofed_repo_id_cannot_cross_users`, `::test_large_k_does_not_leak`. | MET on #40 |
| TI-3 | Delete is user-scoped; deleting another user's `repo_id` is a no-op; reindex removes stale chunks. | `[PR#40]` `test_tenant_isolation.py::test_delete_repo_is_user_scoped`, `::test_delete_other_users_repo_id_is_a_noop`, `::test_reindex_removes_stale_chunks`. | MET on #40 |
| TI-4 | The indexer stays inside an allow-listed root and does not follow symlinks out of it; deny-by-default with no allowlist. | `[PR#40]` `test_walker_jail.py` (6 cases: `::test_deny_by_default_when_no_allowlist`, `::test_requested_root_outside_allowlist_is_skipped`, `::test_symlink_escaping_root_is_not_indexed`, plus excluded-dir/oversize/binary skips). | MET on #40 |
| TI-5 | **Dark KAI's own tables carry a tenant key.** `[PR#42]` `kai_swe_tasks` deliberately has none — "Single-operator model — no user_id / RLS" (`app/models/swe_task.py:9`). Dark KAI must decide explicitly: either inherit the single-operator assumption *and* assert the routes are unreachable multi-tenant (ND-1), or add `user_id`. | `[NEW]` `test_dark_models.py::test_dark_tables_have_tenant_key_or_are_operator_only`. | **NOT MET** |
| TI-6 | Dark KAI does not write to the untenanted shadow stores. Ten SQLite DBs under `data/` have **zero `user_id` columns** — e.g. `data/sol/sol.db` holds member email, `dwolla_customer_id`, `funding_source_href` (`app/services/sol/storage.py:150-161`); likewise journal, EQ, KG, persona, twin, checkin, learning, planning, relationship. All four JSONL sinks are also untenanted. | `[NEW]` `test_dark_storage.py::test_no_writes_to_shadow_sqlite`. | **NOT MET** |
| TI-7 | Dark KAI does not add a migration that creates a competing `0007` head. Three already exist, all with `down_revision = "0006_add_kai_api_keys"`: `0007_add_kai_swe_tasks` (#42), `0007_add_kai_code_chunks` (#40), `0007_sol_v1_data_model` (`origin/feat/sol-v1`). Merging any two produces multiple alembic heads and `alembic upgrade head` fails. | `[NEW]` `test_migrations.py::test_single_alembic_head`. | **NOT MET** |

---

## Cross-cutting blockers Dark KAI inherits if these PRs do not land

1. **Without PR #39**, `ToolRegistry.execute` (`app/services/tools/registry.py:58-84`) is ungoverned:
   a plain Supabase-JWT user on `POST /kai/chat` (`app/routers/nai.py:49-91`) can drive
   `composio(action="execute", tool_slug="GMAIL_SEND_EMAIL")`, `twenty_crm` creates, `notion`
   page writes, and every MCP tool — with **no scope check, no approval, no audit record**. There is
   no tier gate on that registry (`grep` for `tier`/`gate` in `nai.py` and
   `app/services/nai_brain/` returns nothing), contradicting the comments at
   `app/services/mcp_tools.py:30-32` and `app/services/tools/__init__.py:126`.
   Dark KAI's broker requirement is unsatisfiable until this merges.
2. **Without PR #41/#42**, there is no sandbox and no approver identity to reuse — Dark KAI would be
   forced to rebuild both, violating the reuse mandate.
3. `web_fetch`'s SSRF guard string-matches the literal hostname against private prefixes then calls
   `httpx.get(..., follow_redirects=True)` (`app/services/tools/web_fetch.py:62-78`). A hostname
   resolving to a private IP, a decimal IP literal, or any public URL that 302s to
   `169.254.169.254` passes. Analysis mode must not use this tool until it resolves and re-checks
   every redirect hop.
4. No chat/stream/completions route is rate-limited — `app/core/rate_limit.py:19` sets
   `default_limits=[]` and `limiter.limit` appears only in `app/routers/auth.py:59,90,104`.
5. Single-worker uvicorn (`deploy/start_nai.sh`, `--workers 1`) is a **correctness** dependency:
   the admin brute-force throttle (`app/dependencies/admin.py:34-35`) and the rate limiter keep
   state in process memory.

## Explicitly UNVERIFIED

- Whether `app/services/tools/verify_claim.py` emits a confidence score (PC-5) — not read.
- Whether `app/services/alerts.py` sends to Telegram (referenced from `router.py:151,157,165,212`) — not read.
- Whether the `memories` table's FK to `profiles` exists in the live DB; the ORM deliberately omits
  it (`app/models/memory.py:26-28`) and only the migration declares it.
- No test in this document was executed. `backend/pytest.ini` configures no coverage plugin and no
  threshold; per the repo's test-env notes `backend/requirements.txt` is unsatisfiable without a
  curated venv plus local Postgres. Counts are counts of `def test_` symbols read from source.
