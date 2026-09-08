# PR #70 — release-record evidence closure

Closes the four evidence gaps the owner identified after accepting the deployment
(`PR70_PRODUCTION_OPERATIONALLY_ACCEPTED`). Read-only: no code, data, credential or authority
changed while producing it.

Production head `073c9a46c39f2fa9969f8126f9c06bf004a75cf3`. Eight authority flags OFF.

---

## 1. App B artifact-to-source attestation

A runtime SHA variable is self-reported and proves nothing about which bytes built the image, so the
deployed files were hashed **inside the running container** and compared against the git tree.

| | |
|---|---|
| Deployment | `aa05058c-7551-4c5e-bd5c-b8a40a4e154e` |
| Image digest | `sha256:8ee012e50386fb7730d717c6eeb87399a37284d2e971368de6faf125c0f9dc5e` |
| Source | `073c9a46c39f2fa9969f8126f9c06bf004a75cf3` |
| Files compared (`backend/`, `core/`, `frontend/`, `docs/`) | **1006** |
| **Content mismatches** | **0** |
| **Files in container not tracked in git** | **0** |
| Aggregate manifest digest, git side | `7cc2c17d029abc70c3681f51ba81f36c83878227824d82685261206eaaf08ee0` |
| Aggregate manifest digest, container side | `7cc2c17d029abc70c3681f51ba81f36c83878227824d82685261206eaaf08ee0` |

Identical aggregate digests with zero untracked files means the running image's source bytes derive
from `073c9a46`. This is empirical attestation, not a trusted variable.

122 tracked files are absent from the image. Every one is explained by an ignore rule, verified with
`git check-ignore`:

| Count | Paths | Rule |
|---:|---|---|
| 114 | `frontend/blog/_archive/…` | `.gitignore:173` |
| 4 | `frontend/tiktok*.txt` | `.gitignore:193` |
| 2 | `frontend/admin/nexus-assets/*.mp4` | `.gitignore:69`, also `.dockerignore`/`.railwayignore` |
| 1 | `frontend/blueprint.pdf` | `.gitignore:74` (`*.pdf`) |
| 1 | `backend/.env.example` | `.dockerignore` (`.env.*`) |

None is backend or `core/` code. **Every deployed backend file matches source exactly.**

## 2. Rollout ordering (UTC)

From Railway deployment records and App B's own deployment logs:

| Time (UTC) | Event |
|---|---|
| 04:22:18.228Z | App B deployment `aa05058c` created |
| 04:23:53.261Z | App B container starts |
| 04:23:54.165Z | `Running upgrade 0006_add_kai_api_keys -> 0007_add_holding_action_nonces` |
| 04:23:55.583Z | `Application startup complete` · `Uvicorn running on http://0.0.0.0:8080` |
| **04:25:15.481Z** | **App B first `GET /health` → 200** |
| **04:26:17Z** | **`production` ref updated / PR #70 merged** |
| 04:26:17.907Z | App A git-triggered deployment `f0d5527a` created (`commitHash 073c9a46c39f`, branch `production`) |
| — | App A `SUCCESS`, health 200 |

App B was serving healthy traffic **62 seconds before** the production ref moved, and App A started
only after it. Ordering is proven, not asserted.

## 3. Workers check — terminal result

**It failed. It is not passing and is not reported as passing.**

| Commit | Check | Conclusion | Completed |
|---|---|---|---|
| `073c9a46` (this release) | Workers Builds: wheellsverse-bots | **failure** | 2026-09-08T04:35:53Z |
| `5e767a4` (prior production) | Workers Builds: wheellsverse-bots | **failure** | 2026-09-07T01:24:20Z |
| `073c9a46` | Cloudflare Pages | success | 2026-09-08T04:26:33Z |
| `5e767a4` | Cloudflare Pages | success | 2026-09-07T01:14:17Z |

The failure is **identical to the pre-release baseline**, so this release neither caused nor fixed
it. It controls no live hostname and `production` carries no branch protection, so it blocks nothing —
but it remains a genuine failing check, recorded here as failing.

## 4. Production truth tuple

Captured by calling the application's own `deployment_view()` inside the production container —
read-only, no owner credential, no HTTP.

| Field | Observed |
|---|---|
| environment | `production` |
| production SHA | `073c9a46c39f` |
| staging SHA | `UNKNOWN` (module wording for "not sourced") |
| app_a / app_b / source_head SHAs | `UNKNOWN` — not sourced at runtime |
| drift | `UNKNOWN` — *"source head not known at runtime"* |
| feature count | **19** |
| features by verification | `LOCAL_ONLY` × 19 |
| features by endpoint state | `NOT_APPLICABLE` × 14, `UNKNOWN` × 5 |
| eight authority flags | all `DISABLED`, **0 on** |
| flag misconfigurations | none |

### Two honest deviations from the expected tuple

**a) Features report `PRE_DEPLOY` × 19, not `LIVE_PROD` × 19.**
`deployment_state` derives from `hosted_route_verified()`, which reads an **in-process** set populated
by `mark_hosted_route_served()`. A `railway ssh` probe is a *separate* Python process from the uvicorn
worker, so it can never observe routes the server has served — it will always answer `PRE_DEPLOY`.
Reading the live worker's own view requires an owner-authenticated HTTP request, which is not
authorized. So the value is **unavailable by this method**, not `LIVE_PROD` and not disproven.

This is itself evidence for the open Phase 0 item *hosted-verification binding*: hosted-route evidence
lives in memory rather than in a durable, attributable store, so it cannot survive a process boundary.

**b) `deployment_view` reports `money_mode: MOCK` while `MONEY_MODE` is undeclared.**
The cause is a literal default substitution:

```python
money = getattr(settings, "MONEY_MODE", "MOCK")   # holding_deployment.deployment_view
```

The certified resolver, asked in the same container at the same moment, answers correctly:

> `holding_financial_authority: UNAVAILABLE` — *"MONEY_MODE is not declared in this app's Settings"*,
> with the note *"previously reported MOCK — that was a getattr() default presented as runtime state,
> not an observed value"*.

So `money_state.py` is right and `deployment_view` still does the exact thing that note describes.
The money fix landed in the resolver but **one reader was not migrated to it**. This is a real
residual for Phase 0 ("one authoritative resolver, every reader"), not a deployment defect — no money
authority is enabled either way.

## Other observations (not release blockers)

- The Railway CLI upload honours `.gitignore`, contrary to the comment at the top of `.railwayignore`
  which states it does not. Consequence: `data/store_payment_links.json` — which that comment says
  "MUST ship with the image" — is **absent** from the App B image. App B does not use it; flagged so
  the stale comment gets corrected rather than trusted.
- App B logs show repeated `POST /admin/holding/workers/heartbeat` and `/worker-jobs/claim` returning
  **403**. Consistent with authority flags OFF; recorded as expected refusal, not an incident.

## Status

| Gap | State |
|---|---|
| App B artifact-to-source attestation | **CLOSED** — 1006 files, 0 mismatches, 0 untracked |
| Rollout ordering | **CLOSED** — App B healthy 62 s before the ref moved |
| Workers check terminal result | **CLOSED** — failure, identical to baseline, recorded as failing |
| Production truth tuple | **CLOSED with two documented deviations** (a) and (b) above |
