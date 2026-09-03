# Continuous Self-Improvement — Policy Decision Package (READY FOR OWNER APPROVAL)

**Status:** READY FOR OWNER APPROVAL. **Nothing in this package is enabled.** Approving it authorizes a
*mode*, not a code change that self-activates.

**Evidence banked (staging, non-prod, prepare-only):**
`A0_HOSTED_CERTIFIED` · `RUN_INTERNAL_TEST_CERTIFIED_A1_HOSTED` · `LIMITED_A2_HOSTED_CERTIFIED` ·
`A2_WORKER_PERSISTENCE_STAGING_CERTIFIED` · `SELF_IMPROVEMENT_HOSTED_CERTIFIED_NONPROD` ·
`HOSTED_SELF_IMPROVEMENT_BEFORE_AFTER_CERTIFIED` · `A2_WORKER_LIVE_LEASE_RECLAIM_CERTIFIED` ·
`A2_WORKER_REBOOT_SURVIVAL_CERTIFIED` *(pending the operator reboot + verifier run)*.

Hosted certification proved KAI *can* detect a real defect, confirm it against a byte-identical certified
suite, and prepare a source-only fix to `READY_FOR_REVIEW` with 0 merge / 0 deploy. It did **not** decide
*when* KAI may do that on its own. That is this decision.

## The mode model — detection and preparation are SEPARATE permissions
The existing brakes already express three modes without new mode-enum architecture. **Detection** (run a
suite, gather evidence, confirm, notify) is read-only and needs no A2 authority. **Preparation** (turn a
confirmed candidate into an A2 `READY_FOR_REVIEW`) is gated by the existing `KAI_SELF_IMPROVEMENT_ENABLED`
brake, which is itself subordinate to the three A2 brakes. A future detection *scheduler* (a cron, never a
busy loop) is the only new piece, built only if a detect-capable mode is approved.

| Mode | Detection scheduler | `KAI_SELF_IMPROVEMENT_ENABLED` (prepare) | Behavior |
|---|---|---|---|
| **OFF** (current) | not running | false | No autonomous detection, no preparation. Operator-triggered only. |
| **DETECT_ONLY** | running (read-only) | **false** | KAI detects + confirms + **notifies the owner**; prepares nothing. |
| **PREPARE_ALLOWED** | running | true | KAI additionally dispatches confirmed candidates → `READY_FOR_REVIEW`. |

**Invariant:** preparation requires the three A2 brakes; the scheduler can never open them. Turning the
scheduler off, or `KAI_SELF_IMPROVEMENT_ENABLED=false`, or any parent A2 brake off, stops the corresponding
layer immediately. Merge/deploy are never in any mode.

## The decisions (A–I)
**A. Detection authority** — *Recommend: eligible after certification.* Detection is read-only (RUN_INTERNAL_TEST
+ evidence). Safe to schedule under DETECT_ONLY once you accept the review/notification load.

**B. Preparation authority** — *Separately controllable (it already is).* `KAI_SELF_IMPROVEMENT_ENABLED` is the
code-writing gate; keep it OFF until you explicitly move to PREPARE_ALLOWED.

**C. Frequency** — Scheduled cadence, **no busy loop**. *Recommend:* detection at most every 6h, staging only.
Implemented as a cron/scheduled task, not a poll loop.

**D. Attempt budget** — *Recommend initial:* ≤ 3 confirmed candidates dispatched/day; ≤ 1 concurrent A2 job;
worker wall-clock ≤ 10 min/job; per-job coding-CLI token ceiling if measurable. A hard ceiling, refuse beyond it.

**E. Eligible problem types** — narrow allowlist: deterministic **correctness** regression, a **failing certified
internal test**, **documentation accuracy**, a bounded **maintainability** defect with a measurable outcome.
**Excluded initially:** architecture rewrites, dependency upgrades, auth, security policy, finance, deployment
policy, credentials, governance. (These are also blocked in code by the A2 authority/dependency gates.)

**F. Priority** — customer/holding operational work **outranks** self-improvement. Self-improvement yields the
single concurrent worker slot to any operational A2 job.

**G. Duplication** — one active candidate per root problem (dedupe by problem signature); never multiple
branches for the same defect.

**H. Owner notification** — notify on `READY_FOR_REVIEW`, `BLOCKED_OWNER`/`OWNER_REQUIRED`, and material
repeated failure. **Not** every detection cycle (a daily digest instead).

**I. Release** — unchanged: **MERGE = owner/higher class; DEPLOY = owner/higher class.** KAI never releases.

## Initial operational recommendation (after all evidence closes)
- Persistent worker: **ON** (reliability; already certified).
- Observation (A0/A1): **ON**.
- Self-improvement **detection**: eligible for automatic bounded operation → **DETECT_ONLY**.
- A2 **preparation**: **remain separately gated** (`KAI_SELF_IMPROVEMENT_ENABLED=false`) until you explicitly
  approve PREPARE_ALLOWED after watching DETECT_ONLY's candidate quality.
- Production self-improvement: **OFF**. Production A2: **OFF**. (Both stay OFF regardless of staging mode.)

## Rollout
1. **Operator-triggered** (current): you open the window, run one candidate, review. Do this on a few real
   defects to judge candidate quality.
2. **DETECT_ONLY** (fixed trial, e.g. 1 week): scheduler on, prepare OFF, notifications on. Measure
   false-positive rate + review burden. No code is written autonomously.
3. **PREPARE_ALLOWED**: only if DETECT_ONLY's signal-to-noise is acceptable — still staging, still prepare-only,
   still one owner merge per change.

**Decision required:** approve the mode to authorize (recommend DETECT_ONLY) and the initial A–I values, or
keep OFF (operator-triggered only). Approval authorizes building/enabling the detection scheduler for the
chosen mode; it does not enable preparation unless you set PREPARE_ALLOWED.
