# KAI Autonomous SWE Agent (operator runbook)

Builds on the #41 sandbox (`docs/swe_runtime.md`): an operator-approved, bounded
autonomous loop that plans a fix, runs it in the disposable container, produces a
reviewable patch, and — after a **second** approval — pushes it to a review
branch. Full design + decisions: `plans/PLAN-kai-autonomous-swe-agent.md`.

**Off by default. Non-prod only. Never an LLM tool. No merge, no deploy.**

## Enable (on a NON-production runner only)
```
KAI_SWE_RUNTIME_ENABLED=1
KAI_SWE_REPO_ALLOWLIST=/abs/path/to/repo        # deny-by-default
# scopes — enumerate individually; NEVER set the KAI_SCOPE_SWE wildcard
KAI_SCOPE_SWE_PLAN=1                             # create a task + plan (no exec)
KAI_SCOPE_SWE_BRAIN_EXECUTE=1                    # Gate 1: run the sandbox loop
KAI_SCOPE_SWEPUSH_EXECUTE=1                      # Gate 2: apply + push (disjoint root)
KAI_SWE_PUSH_TOKEN=github_pat_...                # fine-grained, contents:write, NO workflows
KAI_SWE_APPROVAL_TIMEOUT_HOURS=24
```
The routes are mounted only when `APP_ENV` is an explicitly non-prod value; a
prod/staging/unknown env refuses to mount them, on top of the flag above.

## Lifecycle
```
POST /admin/swe/tasks                 {goal, source_dir, commands:[...], task_id?}
     -> awaiting_plan_approval  (plan produced; LLM/heuristic only, NO exec)
GET  /admin/swe/tasks/{id}            status / approvers / attempts
GET  /admin/swe/tasks/{id}/plan       review the proposed steps  (GATE 1 payload)
POST /admin/swe/tasks/{id}/plan/approve   {approved:true, approver:"you"}
     -> runs the bounded sandbox loop -> awaiting_push_approval | failed
GET  /admin/swe/tasks/{id}/patch      review the produced diff   (GATE 2 payload)
POST /admin/swe/tasks/{id}/push/approve   {approved:true, approver:"you"}
     -> apply on a fresh clone + push kai/swe/<id> -> pushed | failed
POST /admin/swe/tasks/{id}/reject     {approver:"you"}   decline, or un-stick a
                                      crash-stranded executing/pushing row
```
All routes require `X-Admin-Token`. Both gates are `@audited` + `destructive` +
require a non-empty `approver`.

## Guarantees
- **Bounded**: 8 steps / 200k tokens / 900 s / $1.00 per mission (breach → failed).
- **Sandboxed**: every command runs in the #41 container (no network, no host
  mount, caps dropped, ephemeral). The brain has no exec path but `run_task`.
- **Two human gates**: nothing executes without Gate 1; nothing reaches a repo
  without Gate 2. `patch_sha256` binds a push to the exact reviewed patch.
- **Push is safe-by-refusal**: branch-only (`kai/swe/<id>`, never a protected
  branch, no `--force`); CI-poisoning patches (`.github/workflows/**`,
  `.gitlab-ci.yml`, `.gitlab/**`, `.git/hooks/**`) rejected via git's own
  affected-paths; no ambient git credential (explicit `KAI_SWE_PUSH_TOKEN` only,
  via in-env GIT_ASKPASS); fail-closed audit before the remote write.

## Deliberately deferred (see the plan)
LLM-backed planner (commands are operator-supplied in this MVP) and the OpenHands
adapter — both behind the same `AgentBrain` interface; per-human auth /
separation-of-duties (single shared admin token today — residual risk).

## Notes
- `source_dir` must be a clean git repo (patch base = HEAD).
- Execution is synchronous-in-request; a hard process kill can strand a row in
  `executing`/`pushing` — `reject` is the un-stick. No background worker by design.
- Tests: `tests/services/swe_runtime/` (policy/brain/endpoints/push, incl.
  real-git integration) + `tests/services/test_audit_value_redaction.py`.
