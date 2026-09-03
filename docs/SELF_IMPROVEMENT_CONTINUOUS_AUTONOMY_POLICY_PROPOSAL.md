# Self-Improvement Continuous-Autonomy Policy — Operator Proposal (§44)

**Status:** PROPOSAL for operator decision. Nothing here is enabled.
**Prereq met:** `SELF_IMPROVEMENT_HOSTED_CERTIFIED_NONPROD` (staging, prepare-only) — hosted capability proven.
**This document does NOT authorize continuous use.** Hosted certification proved KAI *can* prepare an
improvement safely; it did not decide *when* it *should* be allowed to do so on its own.

## The distinction this policy exists to hold
- **Persistent worker online** = reliability/availability. Safe to leave on. (`A2_WORKER_PERSISTENCE_STAGING_CERTIFIED`)
- **A2 / self-improvement write authority** = permission to originate code changes. Stays a brake, OFF by
  default. It is opened only inside an explicit window, and only for the classes of work a policy permits.

Continuous autonomy means standing that window open on a schedule. That is a *policy* decision, not a
capability gap — so it is put to the operator here rather than wired in.

## Proposed initial policy (conservative; tighten before you loosen)
| Dimension | Proposed initial value | Rationale |
|---|---|---|
| **Frequency** | At most 1 origination attempt per 6h, staging only | Bounds blast radius + review load; A0/A1 observation stays continuous |
| **Daily attempt budget** | ≤ 3 confirmed candidates dispatched/day | A hard ceiling independent of frequency; refuse beyond it |
| **Priority order** | 1) reproduced failing certified test → 2) material observer finding → 3) verified internal inconsistency | Evidence strength, highest first (§24) |
| **Eligible problem types** | CORRECTNESS, RELIABILITY, TEST_COVERAGE, OBSERVABILITY on **non-authority** source only | The boring, bounded classes (§23). Never auth/payments/deploy/security-gate/autonomy-control |
| **Resource budget** | ≤ 1 concurrent A2 job; worker CPU/wall ≤ 10 min/job | One coding job at a time; a job that overruns is BLOCKED |
| **Notification** | Every dispatch + every READY_FOR_REVIEW → operator (Telegram/queue); daily digest of attempts+outcomes | The owner always knows before reviewing; no silent preparation |
| **Merge/deploy** | NEVER autonomous. READY_FOR_REVIEW → one owner review item, always | Unchanged from the cert; the terminal boundary |
| **Kill** | `KAI_SELF_IMPROVEMENT_ENABLED=false` (or any parent A2 brake) → 0 originations, immediately | Single-flip stop |

## What stays invariant regardless of the policy chosen
- Production `KAI_A2_EXECUTION_ENABLED=false`, `KAI_SELF_IMPROVEMENT_ENABLED=false`. Prod untouched.
- Every origination still passes the full certified chain: confirm() evidence gate → subordinate brake →
  the three A2 brakes + grant + base_sha → real-git diff authority gate → shared authority/dependency/
  binary/oversized gates → independent review → KAI verify. The policy only decides *how often the window
  is open and for which problem classes* — it can never weaken a gate.
- KAI reports "I prepared an improvement for review," never "I upgraded myself" (§34): deployed code is
  unchanged until the owner merges.

## Recommended rollout (before any schedule)
1. **Operator-triggered only** (current): you open the window, dispatch one candidate, review the result.
   Do this a handful of times on real (not fixture) defects to build confidence in candidate quality.
2. **Supervised cadence**: enable the 6h/≤3-per-day schedule for a fixed trial (e.g. 1 week) with the
   Telegram notifications on; review every prepared change; measure false-positive rate (candidates that
   were not real defects) and review burden.
3. **Standing policy**: only if the trial's signal-to-noise is acceptable, adopt the schedule as standing —
   still staging, still prepare-only, still one owner merge per change.

## Open questions for the operator
- Which subsystems are in-scope first? (Recommend the smallest, best-tested, non-authority ones.)
- Acceptable weekly review burden? (This caps the daily budget more than anything technical.)
- Telegram vs. the in-app owner queue vs. both for notifications?
- A per-attempt token/cost ceiling for the coding worker?

**Decision required:** approve/modify the initial values above and the rollout stage to authorize, or keep
self-improvement operator-triggered-only for now.
