# KAI Self-Improvement (Part B, §15-53) + DEPLOYMENT_STATUS (Part A)

Evidence-driven, **PREPARE-only** self-repair. KAI can detect a defect, diagnose it, prepare a fix in an
isolated worktree, verify it independently, and leave it `READY_FOR_REVIEW` — the owner merges. It never
merges, deploys, rotates secrets, disables controls, or changes MONEY_MODE. Dormant on
`feat/kai-exec-appb-integration`; production unchanged.

## Modules
| File | Role |
|---|---|
| `holding/deployment_status.py` | DEPLOYMENT_STATUS — deployment truth, zero deploy authority |
| `holding/self_improvement.py` | SelfImprovementEngine — value gate, diagnosis, A2 preparation, diff limits |
| tests | `test_deployment_status.py` (10/10), `test_self_improvement.py` (10/10) |

## DEPLOYMENT_STATUS (Part A) — `CERTIFIED_READ_ONLY`
Answers what/current/succeeded/healthy/stale/likely-cause; **cannot** deploy/restart/rollback/scale/
change vars/domains (no such method exists). Provider resolved from service metadata (§1); uncertified
provider → BLOCKED, never substituted. Certified `LocalDeploymentProvider`: source SHA (git) vs a
server-configured deployed SHA, compared by **real git ancestry** with SHAs canonicalized first (short
vs full of the same commit → MATCH) → MATCH / DEPLOYMENT_BEHIND / AHEAD_OR_UNKNOWN / UNCOMPARABLE.
Services are **bound to a company** at registration (cross-company read denied). Evidence whitelisted —
no env vars / tokens / raw provider blobs (§6/§9). SHAs hex-validated before touching git (injection).

## SelfImprovementEngine (Part B)
`confirm()` decides whether a **software change** is warranted:
- **§18 value gate** — must support a measurable outcome (RELIABILITY/SECURITY/CORRECTNESS/…); else REJECTED.
- **§41 deployment-stale** (critical) — if the deployment is BEHIND source, the fix may already exist →
  BLOCKED / `DEPLOYMENT_STALE`, **no second fix written**.
- **§42 config** — a production-config issue → OWNER_REQUIRED (no autonomous config write).
- **§20/§30/§40 evidence** — a code change requires a *reproducing test*; else BLOCKED_EVIDENCE.

`prepare()` drives the **limited A2 framework** (isolated worktree → worker → git-derived authority gate
→ tests → independent review → READY_FOR_REVIEW) then adds grant-specific policy:
- **§26 dependency denial** — a change to requirements/pyproject/lock/Docker/CI → OWNER_REQUIRED.
- **§25 diff limits** — more than `MAX_FILES_CHANGED` (10) → OWNER_REQUIRED (policy v1.0.0).
- **§33 test-cheating heuristic** — a correctness/reliability fix touching **only** test files → OWNER_REQUIRED.
- **§34 self-authority** — a diff touching any authority surface → A2 gate → OWNER_REQUIRED (never prepared-clean).

The first grant is `SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1` (§21): non-production, one approved repo,
source/test/doc edits only. Completion is a **§36 owner review package** = ONE action (problem, evidence,
root cause, files, before/after tests, security review, rollback, limitations) — KAI already did the rest.

## Invariants (test-backed)
- **Never releases (§35):** `merged`/`deployed` always False; terminal state is READY_FOR_REVIEW.
- **Never trusts the worker:** the authority gate + diff limits read the **git-derived** diff, not the
  worker's self-report.
- **No self-approval:** implementer ≠ reviewer (`certify_worker_result`).
- **Bad fix (§39):** tests fail → FAILED, no retry, no escalation.
- **Autonomy off (§49):** no autonomous A2 self-improvement execution.

## Not yet (per §NEXT, all owner-gated)
BROWSER_VALIDATE (Playwright) · TECH_DOC_LOOKUP (Context7) · connect the engine to the persistent
scheduled cycle · a real CodingWorkerRouter/LLM worker (today the worker is the pluggable part) · UI ·
live-safe staging cert · production deployment only after explicit operator approval.
