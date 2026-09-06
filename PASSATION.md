# PASSATION — KAI Omnipresent Holding Command OS

Handoff for a new session. Written 2026-09-06. Everything below was measured, not assumed; where
something is unproven it says so.

---

## 1. Where things are, exactly

| | |
|---|---|
| Worktree | `/Users/jhonwheeler/wheellsverse-cyberops` (durable — NOT `/private/tmp`, which a reset once wiped) |
| Branch | `feat/kai-cyber-operations` |
| HEAD | `4f5d8f9ca557f3be8284df75e5d3dea46aeefdc6` |
| Tree | clean |
| vs `main` | **285 ahead, 39 behind** |
| Remote | **never pushed.** No branch on origin, no PR, no CI has ever run on this work |
| Historical checkpoint | `66edfe3` — the dark-build §159 certification. Preserved, do not rewrite |

**The 285 vs "the mission" distinction matters.** Only 25 commits are the Omnipresence mission
(`d881cf2^..66edfe3`). Another 252 are pre-mission work on the same long-lived branch dating to
2026-06-26 (holding-os, capability fabric, nexus, sol-ui, cyber-ops A/B). The remaining 8 are this
review session. Never describe a release here as "merge 285 commits" without saying what they are.

## 2. What is deployed, and where

| Environment | Service | Running | Verified |
|---|---|---|---|
| **Staging App A** | `kai-appA-staging` (Railway project `kai-staging` `0dcd21ec-…`) | `9200706` | dashboard live, owner sign-in works end to end |
| **Staging App B** | `kai-staging`, same project | `9200706` | holding routes 403 unauth / 200 with owner cookie |
| **Production App A** | `wheellsverse-v2` (project `grateful-flexibility`) | `b0674ce` — **a 2-line nav link ONLY** | `/admin` healthy, link present |
| **Production App B** | `kai-prod` (project `kai-production`) | `4fbfb8e`, untouched | healthy |

Staging has its OWN Postgres and Redis. No production secret or customer data was ever copied into it.

**Production does NOT run the Holding OS.** It runs release #67 plus one nav link that points at the
staging dashboard. That link is labelled "(staging)" and opens in a new tab, and it needs the *staging*
key to sign in, not the production one.

**Staging URL:** https://kai-appa-staging-production.up.railway.app/admin/holding
**Production entry point:** https://app.wheellsverse.com/admin → sidebar → INTELLIGENCE → "Holding Command (staging)"

## 3. Flag posture — deployment is not enablement

All nine authority flags are `bool = False` in `backend/app/config.py`. On staging exactly ONE was
turned on: `KAI_HOLDING_ENABLED`, verified display-only before being set (it mounts a read-only router
and nothing else; `main.py:211`). Every consequential flag is unset, and the observable proof is that
`/admin/holding/voice/capabilities` and `/gesture/capabilities` still return **404** — their command
router is genuinely not mounted. Voice and camera are dark, not idle.

**Do not turn flags on to make UI appear.** `KAI_HOLDING_ENABLED` gates display; the others gate
execution. And note: on today's **production** App B, five of the nine are not declared in `config.py`
at all, and pydantic's `extra="ignore"` drops undeclared variables silently — so setting them there
before the code ships is a guaranteed no-op that looks like it should have worked.

## 4. THE BLOCKER — the merge cannot complete without you

`git push` is **rejected by GitHub secret scanning**. The branch history contains token-shaped strings
across many commits. Every one is a synthetic test fixture, deliberately shaped so the scanners under
test can be proven to catch them — but push protection cannot tell a fixture from a leak.

Known offenders in history (there may be more; GitHub reports them one at a time):

| Commit | Fixture |
|---|---|
| `8799db9` | GitHub PAT-shaped strings (round-5 credential-detection tests) |
| `749fa78`, `58a4227`, `cd3b96d` | `AKIAIOSFODNN7EXAMPLE` (AWS's own published documentation example key), an OPENSSH PRIVATE KEY header |
| `0fed354`, `345607b`, `b69702e`, `b82b873`, `a932706` | `ghp_…` strings inside prompt-injection test fixtures from earlier missions |

I already split the literals in the **current** file (`4f5d8f9`) so the working tree is clean, but that
does not help: the strings remain in history.

**Your options, in order of preference:**

1. **Allow them via GitHub's unblock URL** (the push output prints one per secret). Correct if you
   accept these are synthetic fixtures — which they are. Fastest path, no history rewrite.
2. **Rewrite history to purge them.** Invasive across 285 commits, and you explicitly said not to
   rewrite history. Not recommended.
3. **Leave the branch local.** Everything works; there is simply no PR or CI record.

Until one of these happens there is **no PR, no CI, and no merge**. That is the single thing standing
between this work and a normal release process.

## 5. Two production variables are stale — production is misreporting itself

Production runs `b0674ce` but reports `4fbfb8e`. Both variables need updating; my attempts were blocked
by the environment's permission classifier:

```bash
railway variables --service wheellsverse-v2 \
  --set "GIT_SHA=b0674ce2b5a8e23573cc288c09f46b7e3f609ff7" \
  --set "RAILWAY_GIT_COMMIT_SHA=b0674ce2b5a8e23573cc288c09f46b7e3f609ff7"
```

`GIT_SHA` feeds `/api/health`; `RAILWAY_GIT_COMMIT_SHA` (or `GIT_COMMIT_SHA`) feeds the drift
calculation — they are read by different code (`railway.json` start command vs
`holding_deployment.py:17`). Setting only one leaves the other quietly wrong. This is the same defect
class as §7 below.

## 6. Also outstanding

- **Rotate the staging `API_KEY`** on `kai-appA-staging`. A 422 from the login endpoint echoed it into
  a session transcript when the wrong field name (`key` instead of `secret`) was used. Staging only;
  production credentials were never handled.
- **Timeline is blank by construction** — `timeline.ingest()` has no caller outside its own test. The
  panel will stay empty however it is deployed or flagged. Not a bug to chase; a feature to finish.
- **Missions/`working_now` stay empty** while the A2 brakes are off; `worker_jobs` are only produced by
  `a2_dispatch`.
- Jobs #1–#7 were dispatched from the Decisions panel but **no worker has checked in**, so they will
  not run. They are read-only re-probes either way.

## 7. What this session actually found — read this before trusting a green test run

Six defects were found **by a human looking at the running system**, none reachable by any test:

| Commit | Defect |
|---|---|
| `655ef81` | The one standing backend failure was a genuine negative control, but **nothing asserted which failure was expected** — the directory was permanently red and a real regression would have hidden inside it |
| `45aa5bd` | `/admin/holding` had **zero inbound links anywhere**; a stale backend rendered every panel "unavailable" indistinguishably from an outage; the sign-in operators would naturally use never mints the required cookie |
| `64166f4` | A pasted key was not trimmed, so a **correct** key returned 401; every failure showed one catch-all message |
| `8378876` | The voice reason printed twice, reading as two faults |
| `06a41a6` | Panels did not refresh on sign-in — you signed in and still read HTTP 401 on nineteen cards |
| `9200706` | **The Operational Self Model claimed `environment: production` while running on staging.** Hardcoded at both call sites, never read from anywhere. The module whose entire purpose is honest self-description was wrong about the most important fact about itself, and contradicted the deployment panel in the same payload |

The pattern to carry forward: **iterated adversarial refutation**, where each round's reviewer attacks
the *previous round's fix* with a growing probe corpus (128 → 201 → 451 assertions). That found four
HIGH defects and one self-inflicted regression after single-pass review had passed the same code clean.
The OS-Lab credential leak took **five rounds** to close; every intermediate round's tests passed and
every one believed it was done. Round 2's own fix (`MappingProxyType` for a deep freeze) silently
disabled `redact()` because a proxy is not a `dict` subclass — a fix worse than the defect it closed.

**Stopping rule that works:** stop when a round yields bounded, *named* residuals rather than reachable
defects. NOT "tests pass" and NOT "fewer findings than last round" — both were true of `749fa78` while
three HIGH defects remained.

## 8. Verification baseline (re-measure, do not inherit)

At `9200706`, measured with an isolated database (`pgcrypto`, `vector`, `citext` extensions required):

- **84 backend modules, 1721 checks, 1720 pass.** The single failure is `test_si_calc_guard`
  `bucket(0)`, the intentional seeded fixture, now guarded by `test_si_calc_seed_harness` (13 checks).
- **18 frontend node suites, 263 checks**, all pass.
- `backend/tests` 723 pass / 137 fail / 19 errors and root `tests` 593 pass / 44 fail — **failure sets
  byte-identical to the mission base**. Zero regressions. Those failures are environmental (missing
  `cachetools`/`chromadb`, unconfigured admin token) and pre-existing.
- **No type checking or linting exists in this repo.** No mypy, ruff or black configured. `.flake8`
  exists but is not installed and no CI invokes it. Do not claim a clean lint.

Harness notes: many suites are zero-framework scripts that `raise SystemExit` at import, so `pytest`
over a whole directory INTERNALERRORs — run those per-file with `python3 -m app.services.holding.<mod>`.
`test_certification` additionally needs the repo root on `PYTHONPATH` for `core.security_scanner`.

```bash
cd /Users/jhonwheeler/wheellsverse-cyberops/backend
PYTHONPATH="$PWD:$(dirname $PWD)" DATABASE_URL="postgresql://…" python3 -m app.services.holding.<module>
```

## 9. Governance documents

`docs/KAI_OMNIPRESENCE_*.md` — CERTIFICATION (§159 verdict), REQUIREMENTS (§161 ledger, 167 rows),
EVIDENCE_MATRIX (§162), DECISIONS (§163, ADR-001…024), BASELINE, THREAT_MODEL, OS_LAB,
COMPARTMENTALIZATION, STAGING_DEPLOYMENT.

Ledger status at last reconciliation: 80 SATISFIED / 73 PARTIAL / 7 GAP / 6 DEFERRED / 1 N-A.
**SATISFIED means implemented + tested + adversarially reviewed, DARK AND UNDEPLOYED.** It never
implies deployed or enabled. An independent audit disputed several rows — notably §5 (the dashboard had
no navigation entry, since fixed) and §12 (`arrival.py` has zero non-test importers; the shipped
arrival is client-side). Treat the ledger as reviewed, not infallible.

## 10. If you do nothing else

1. Decide the secret-scanning unblock so the branch can be pushed and a PR opened.
2. Fix the two stale production SHA variables.
3. Rotate the staging `API_KEY`.

Production is safe as it stands: release #67 plus one nav link, nothing enabled, no schema change, and
rollback is redeploying `b6ccb004-eca`.
