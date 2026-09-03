# KAI Holding OS — Deployment Backlog & Reconciliation

**Generated:** 2026-09-03 · **Branch:** `feat/kai-exec-appb-integration` · **HEAD:** `23c3521`

## SHA reconciliation (no guessing — §8)
| Target | Service | SHA | Note |
|---|---|---|---|
| **Source (branch HEAD)** | — | `23c3521` | this release candidate |
| **Staging App B** | `kai-staging-appb` (proj kai-staging) | **`23c3521`** | **IN_SYNC** — deployed + verified this session |
| **Prod App A** | `app.wheellsverse.com` | on `production` branch (~`462adff`) | serves `/admin/holding`; **far behind** |
| **Prod App B** | `kai-prod` (proj kai-production) | on `production` branch (~`462adff`) | `env:production`, healthy; **far behind** |

**Drift:** `PRODUCTION_BEHIND` (both prod halves run the separate certified `production` branch; staging is current).

## Staging release delta (`dcb2b33 → 23c3521`) — 9 commits, now STAGING_LIVE
All Holding-OS, all read-only-or-dark, **MONEY_MODE=MOCK**, A2/self-improvement/signals all default OFF.

## Safe release units (grouped by risk class — §4/§11)
| Unit | Risk | Features | Runtime default | Prod eligibility |
|---|---|---|---|---|
| **U1 — dashboard truth** | **P0** | Improvement Watch UI, Deployment/Drift panel, Feature Registry, env badges | always-on presentation | eligible after visual cert |
| **U2 — read-only backend** | **P1** | DETECT_ONLY detection, repeated-job + capability-health signals, `/deployment` + `/improvement-watch` read APIs | detection ON (staging); **signals OFF** | eligible after cert + rollback proof; deploy **signals dark** |
| **U3 — dormant execution** | **P2** | A2 prepare-only, self-improvement PREPARE, PREPARE_ALLOWED guardrails | **all OFF** | deploy **DARK** (code visible, authority OFF) |
| **U4 — authority** | **P3** | enable A2 / enable PREPARE / enable signals | — | **NOT deployed-implied**; separate owner approval each |

## Production promotion — GENUINE GATE (not blindly deployable)
The operator-visible dashboard (`app.wheellsverse.com/admin/holding`) is **App A**, which fetches the view through the App A→App B bridge. Landing U1+U2+U3 in production therefore requires deploying to **both** live prod services (App A **and** App B), which currently run the **separate certified `production` branch**, not this feature branch.

Promoting is safe **only** via one of:
- **(A)** the operator authorizes deploying this feature branch's release units to the prod services (matching the disciplined phase-gated rollout used for the original prod deploy), or
- **(B)** the P0/P1/P2-dark units are landed onto the `production` branch (cherry-pick/merge) and deployed through the existing production path.

Per policy §32 ("never self-deploy an unreviewed unsafe release") and §2 ("stop for an irreversible production change"), I will **not** unilaterally replace the live customer app's certified stack with a divergent feature branch. This is `BUILD_COMPLETE_DEPLOYMENT_BLOCKED (production)` pending the operator's release strategy (A or B).

**What holds regardless:** production A2 OFF · production self-improvement OFF · financial OFF/MOCK · restricted-security OFF. Deploying these units never enables them.
